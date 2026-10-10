"""Real API scenario inputs shared by tests and the producer oracle."""

import hashlib
import json
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(record):
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "digest"})).hexdigest()


def register_targets(client):
    targets = []
    for kind, address in (("DUT", "Unresolved.Example."), ("SINK", "2001:db8::1")):
        response = client.post(
            "/api/v1/targets", json={"name": f" {kind} 장비 ", "address": address, "kind": kind}
        )
        assert response.status_code == 201, response.text
        targets.append(response.json())
    return targets


def definition(targets):
    return {
        "name": " 검증 😀 ",
        "objective": " Preserve literals\n\t정책 검증\r\n ",
        "target_id": targets[0]["id"],
        "sink_id": targets[1]["id"],
        "dut_version": " declared firmware ",
        "policy_version": "policy-1",
        "profile_id": "tcpreplay-policy",
        "protocol": "TCP",
        "ip_version": 4,
        "expected_action": "ALLOW",
        "delivery_expectation": "ALLOW",
        "detection_required": False,
        "pcap_asset": None,
        "traffic_budget": {
            "max_pps": 10,
            "max_bps": 1000,
            "max_packets": 100,
            "max_bytes": 10000,
            "max_connections": 1,
            "duration_seconds": 10,
        },
        "success_criteria": {
            "minimum_delivery_pct": 90,
            "maximum_delivery_pct": 100,
            "detection_deadline_ms": None,
        },
        "stop_conditions": {
            "max_legitimate_loss_pct": 1,
            "max_service_latency_ms": 100,
            "max_cpu_pct": None,
            "max_memory_pct": None,
            "max_sessions": None,
            "management_loss": True,
        },
        "evidence_requirements": ["ingress_pcap", "egress_pcap", "service_probe"],
    }


def generate_samples(output: Path) -> dict:
    """Capture actual response bytes from in-process HTTP; never create a listener.

    Output must be a new directory. IDs/timestamps are genuinely producer-generated,
    so repeated runs have new bytes; every run binds receipts to its source hashes.
    """
    from fastapi.testclient import TestClient

    import aiddos.api.app as app_module
    from aiddos.api.app import create_app

    root = Path(__file__).resolve().parents[2]
    assert Path(app_module.__file__).resolve() == root / "src/aiddos/api/app.py"
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "transport": "in-process ASGI HTTP (no listener)",
        "samples": [],
        "producer_origin": str(Path(app_module.__file__).resolve()),
        "source_manifest": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "src/aiddos/api").glob("*.py"))
        },
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("Producer attempted network, DNS or process execution")

    with ExitStack() as guards:
        for target in ("socket.socket.connect", "socket.getaddrinfo", "subprocess.Popen"):
            guards.enter_context(patch(target, forbidden))
        temporary = guards.enter_context(
            TemporaryDirectory(prefix="scenario-producer-", dir=output.parent)
        )
        state_path = Path(temporary) / "drafts.json"
        client = guards.enter_context(
            TestClient(create_app(state_path=state_path), base_url="http://localhost")
        )

        def capture(name, kind, method, path, status, payload=None):
            kwargs = {} if payload is None else {"json": payload}
            response = client.request(method, path, **kwargs)
            assert response.status_code == status, response.text
            assert response.headers["cache-control"] == "no-store"
            file = name + ".json"
            (output / file).write_bytes(response.content)
            receipt["samples"].append(
                {
                    "file": file,
                    "kind": kind,
                    "method": method,
                    "path": path,
                    "request": deepcopy(payload),
                    "status": status,
                    "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
            )
            return response.json()

        capture("empty-list", "page", "GET", "/api/v1/scenarios", 200)
        targets = register_targets(client)
        before = state_path.read_bytes()
        value = definition(targets)
        value["name"] = "😀" * 120
        value["objective"] = ' literal <>& \\" \n\t\r 한글 Straße Σς İ \u2028\u2029 '
        first = capture(
            "replay-create",
            "mutation",
            "POST",
            "/api/v1/scenarios",
            201,
            {"revision": 0, "definition": value},
        )
        identity = first["scenario"]["id"]
        path = f"/api/v1/scenarios/{identity}"
        updated = deepcopy(value)
        updated.update(
            expected_action="ALERT",
            delivery_expectation="BLOCK",
            detection_required=True,
            ip_version=6,
            protocol="DNS",
            dut_version=" firmware 2 ",
            policy_version="정책 2",
        )
        updated["traffic_budget"] = {
            "max_pps": 1000000000,
            "max_bps": 1000000000000,
            "max_packets": 1000000000000,
            "max_bytes": 1000000000000,
            "max_connections": 1000000,
            "duration_seconds": 3600,
        }
        updated["pcap_asset"] = {
            "label": "declared identity only",
            "sha256": "f" * 64,
            "size_bytes": 67108864,
        }
        updated["success_criteria"] = {
            "minimum_delivery_pct": 0,
            "maximum_delivery_pct": 0,
            "detection_deadline_ms": 60000,
        }
        updated["stop_conditions"] = {
            "max_legitimate_loss_pct": 100,
            "max_service_latency_ms": 60000,
            "max_cpu_pct": 100,
            "max_memory_pct": 100,
            "max_sessions": 1000000,
            "management_loss": True,
        }
        updated["evidence_requirements"] = [
            "resource_metrics",
            "dut_events",
            "service_probe",
            "egress_pcap",
            "ingress_pcap",
        ]
        acknowledgement = capture(
            "replay-update", "mutation", "PUT", path, 200, {"revision": 1, "definition": updated}
        )
        later = deepcopy(updated)
        later["policy_version"] = "concurrent later declaration"
        capture(
            "concurrent-update", "mutation", "PUT", path, 200, {"revision": 2, "definition": later}
        )
        history = capture("history-after-concurrent", "history", "GET", path, 200)
        assert history["versions"][0] == first["scenario"]
        assert history["versions"][1] == acknowledgement["scenario"]
        assert history["revision"] > acknowledgement["revision"]
        http = definition(targets)
        http.update(
            profile_id="k6-http",
            protocol="HTTP",
            ip_version=6,
            name=" HTTP 등록 ",
            evidence_requirements=["service_probe"],
        )
        created_http = capture(
            "http-create",
            "mutation",
            "POST",
            "/api/v1/scenarios",
            201,
            {"revision": 3, "definition": http},
        )
        capture(
            "http-history",
            "history",
            "GET",
            f"/api/v1/scenarios/{created_http['scenario']['id']}",
            200,
        )
        capture("populated-list", "page", "GET", "/api/v1/scenarios?limit=100", 200)
        capture("second-page", "page", "GET", "/api/v1/scenarios?offset=1&limit=1", 200)
        capture("conflict", "error", "PUT", path, 409, {"revision": 1, "definition": updated})
        capture("not-found", "error", "GET", "/api/v1/scenarios/absent", 404)
        invalid = deepcopy(http)
        invalid["ip_version"] = 6.0
        capture(
            "invalid-definition",
            "error",
            "POST",
            "/api/v1/scenarios",
            422,
            {"revision": 4, "definition": invalid},
        )
        assert state_path.read_bytes() == before
    receipt["sample_count"] = len(receipt["samples"])
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def producer_oracle(raw: bytes) -> dict:
    """JSONL oracle: {kind: definition|version|state, value: ...} -> accepted.

    This is producer-derived validation, not an independent browser implementation.
    """
    from aiddos.api.encoding import strict_json
    from aiddos.api.scenarios import ScenarioDefinition, ScenarioState, ScenarioVersion

    models = {"definition": ScenarioDefinition, "version": ScenarioVersion, "state": ScenarioState}
    try:
        request = strict_json(raw)
        if not isinstance(request, dict) or set(request) != {"kind", "value"}:
            return {"accepted": False}
        kind = request["kind"]
        if not isinstance(kind, str) or kind not in models:
            return {"accepted": False}
        models[kind].model_validate(request["value"])
    except (ValueError, RecursionError):
        return {"accepted": False}
    return {"accepted": True}


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", type=Path, help="New directory for real API bytes and receipt")
    mode.add_argument(
        "--oracle", action="store_true", help="Validate producer models via JSONL stdin"
    )
    args = parser.parse_args()
    if args.oracle:
        for raw in sys.stdin.buffer:
            print(json.dumps(producer_oracle(raw)))
    else:
        receipt = generate_samples(args.out)
        print(
            json.dumps(
                {"receipt": str(args.out / "receipt.json"), "sample_count": receipt["sample_count"]}
            )
        )


if __name__ == "__main__":
    main()
