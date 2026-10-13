"""Validated synthetic manifest variants; no DB, worker, asset reads or traffic.

Only the initial snapshot comes from captured HTTP bytes. Repeated pure calls
are not real worker retry attempts or a fresh producer-parity corpus.
"""

import hashlib
import json
from copy import deepcopy
from itertools import combinations, product
from pathlib import Path

import pytest

from aiddos.api.catalog import PROFILES_V1
from aiddos.runs import offline

ROOT = Path(__file__).resolve().parents[2]
ROLES = ("ingress_pcap", "egress_pcap", "dut_events", "service_probe", "resource_metrics")
POLICIES = (
    ("ALLOW", "ALLOW", False),
    ("ALLOW", "ALLOW", True),
    ("BLOCK", "BLOCK", False),
    ("BLOCK", "BLOCK", True),
    ("ALERT", "ALLOW", True),
    ("ALERT", "BLOCK", True),
)
TRAFFIC = tuple(
    ("tcpreplay-policy", protocol, declared, status)
    for protocol in ("TCP", "UDP", "DNS")
    for declared, status in ((False, "NOT_DECLARED"), (True, "DECLARED_UNVERIFIED"))
) + (("k6-http", "HTTP", False, "NOT_APPLICABLE"),)


def encode(value):
    # Independent test encoder implements the published canonical JSON contract.
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(encode({k: v for k, v in value.items() if k != "digest"})).hexdigest()


def variants():
    for traffic, policy, resources in product(TRAFFIC, POLICIES, product((False, True), repeat=3)):
        required = {"service_probe"}
        if traffic[0] == "tcpreplay-policy":
            required.update(("ingress_pcap", "egress_pcap"))
        if policy[2]:
            required.add("dut_events")
        if any(resources):
            required.add("resource_metrics")
        optional = tuple(role for role in ROLES if role not in required)
        for size in range(len(optional) + 1):
            for extra in combinations(optional, size):
                evidence = tuple(role for role in ROLES if role in required or role in extra)
                label = "-".join((
                    traffic[1], traffic[3], policy[0], policy[1], str(policy[2]),
                    "".join(str(int(flag)) for flag in resources), "+".join(evidence),
                ))
                yield pytest.param(traffic, policy, resources, evidence, id=label)


@pytest.fixture(scope="module")
def captured_snapshot():
    corpus = ROOT / "tests/fixtures/runs/h1"
    index = json.loads((corpus / "selected-index.json").read_text())
    entry = next(item for item in index if item["state"] == "QUEUED")
    body = (corpus / entry["body"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]
    return json.loads(body)["snapshot"]


@pytest.mark.parametrize("traffic,policy,resources,evidence", tuple(variants()))
def test_valid_manifest_variants_have_exact_repeatable_bytes(
    captured_snapshot, traffic, policy, resources, evidence
):
    profile, protocol, declared, asset_status = traffic
    action, delivery, detection = policy
    snapshot = deepcopy(captured_snapshot)
    scenario = snapshot["scenario"]
    definition = scenario["definition"]
    definition.update(
        profile_id=profile,
        protocol=protocol,
        expected_action=action,
        delivery_expectation=delivery,
        detection_required=detection,
        pcap_asset={"label": "declared only", "sha256": "a" * 64, "size_bytes": 64}
        if declared else None,
        evidence_requirements=list(evidence),
    )
    criteria = {
        "minimum_delivery_pct": 90 if delivery == "ALLOW" else 0,
        "maximum_delivery_pct": 100 if delivery == "ALLOW" else 5,
        "detection_deadline_ms": 60000 if detection else None,
    }
    definition["success_criteria"] = deepcopy(criteria)
    for field, enabled, limit in zip(
        ("max_cpu_pct", "max_memory_pct", "max_sessions"),
        resources, (75, 80, 1000), strict=True,
    ):
        definition["stop_conditions"][field] = limit if enabled else None
    scenario["profile_snapshot"] = deepcopy(next(p for p in PROFILES_V1 if p["id"] == profile))
    scenario["digest"] = digest(scenario)
    snapshot["digest"] = digest(snapshot)
    source_bytes = encode(snapshot)
    verified = offline.verify(source_bytes)  # Every generated variant must be valid.

    expected = {
        "schema_version": 1,
        "kind": "offline_preparation",
        "snapshot_digest": snapshot["digest"],
        "checks": ["SNAPSHOT_INTEGRITY", "POLICY_CONSISTENCY", "REQUIREMENTS_COMPILED"],
        "expected_policy": {
            "expected_action": action,
            "delivery_expectation": delivery,
            "detection_required": detection,
        },
        "success_criteria": criteria,
        "declared_limits": {
            "traffic_budget": deepcopy(definition["traffic_budget"]),
            "stop_conditions": deepcopy(definition["stop_conditions"]),
        },
        "evidence_requirements": [
            {"role": role, "availability": "NOT_INGESTED"} for role in evidence
        ],
        "asset_status": asset_status,
        "evaluation": "NOT_EVALUATED",
        "defense_verdict": None,
        "measurements": None,
    }
    expected["digest"] = digest(expected)
    first = offline.compile_manifest(verified)
    assert first == encode(expected)
    assert len(first) <= 8192
    assert encode(verified) == source_bytes  # Compilation must not mutate its input.
    assert offline.compile_manifest(offline.verify(source_bytes)) == first
