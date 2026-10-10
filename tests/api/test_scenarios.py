"""S01 API behavior; the inherited autouse fixture forbids external execution."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from scenario_producer import definition, digest, register_targets

from aiddos.api.app import create_app
from aiddos.api.catalog import PROFILES_V1


def test_empty_read_creates_no_files(client, state_path):
    response = client.get("/api/v1/scenarios")
    assert response.status_code == 200
    assert response.json() == {
        "revision": 0,
        "total": 0,
        "offset": 0,
        "limit": 50,
        "items": [],
        "execution_enabled": False,
    }
    assert response.headers["cache-control"] == "no-store"
    assert not list(state_path.parent.iterdir())


def test_create_append_reopen_preserves_complete_history(client, state_path):
    targets = register_targets(client)
    before = state_path.read_bytes()
    value = definition(targets)
    created = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert set(receipt) == {"revision", "scenario", "execution_enabled"}
    assert receipt["revision"] == 1 and receipt["execution_enabled"] is False
    first = receipt["scenario"]
    assert str(UUID(first["id"])) == first["id"]
    assert first["version"] == 1
    assert first["definition"] == value
    assert first["target_snapshot"] == targets[0]
    assert first["sink_snapshot"] == targets[1]
    assert first["profile_snapshot"] == PROFILES_V1[0]
    assert first["catalog_version"] == "1.0.0"
    assert first["status"] == "definition" and first["execution_enabled"] is False
    assert first["digest"] == digest(first)
    changed = deepcopy(value)
    changed["policy_version"] = " policy-2 "
    changed["profile_id"] = "k6-http"
    changed["protocol"] = "HTTP"
    response = client.put(
        f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": changed}
    )
    assert response.status_code == 200, response.text
    second = response.json()["scenario"]
    assert response.json()["revision"] == 2
    assert second["version"] == 2 and second["id"] == first["id"]
    assert second["definition"] == changed and second["profile_snapshot"] == PROFILES_V1[2]
    assert second["digest"] == digest(second) != first["digest"]
    with TestClient(create_app(state_path=state_path), base_url="http://localhost") as reopened:
        history = reopened.get(f"/api/v1/scenarios/{first['id']}")
        assert history.status_code == 200
        assert history.json() == {
            "revision": 2,
            "scenario_id": first["id"],
            "versions": [first, second],
            "execution_enabled": False,
        }
        page = reopened.get("/api/v1/scenarios").json()
        assert page["items"] == [second] and page["total"] == 1 and page["revision"] == 2
    assert state_path.read_bytes() == before


def registry_path(state_path):
    return state_path.with_name(state_path.name + ".scenarios.json")


def assert_error(response, status, code):
    from aiddos.api.errors import ERRORS

    assert response.status_code == status, response.text
    assert response.json() == {"code": code, "message": ERRORS[code][1]}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method", ["post", "put"])
def test_stale_cas_precedes_references_and_never_writes(client, state_path, method):
    value = definition(register_targets(client))
    first = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}).json()
    before = registry_path(state_path).read_bytes(), state_path.read_bytes()
    value["target_id"] = "missing"
    url = "/api/v1/scenarios" + ("/absent" if method == "put" else "")
    assert_error(
        getattr(client, method)(url, json={"revision": 0, "definition": value}),
        409,
        "SCENARIO_CONFLICT",
    )
    assert before == (registry_path(state_path).read_bytes(), state_path.read_bytes())
    assert client.get(f"/api/v1/scenarios/{first['scenario']['id']}").status_code == 200


@pytest.mark.parametrize("mutation", ["missing", "swapped", "same"])
def test_invalid_target_roles_deny_before_publication(client, state_path, mutation):
    value = definition(register_targets(client))
    if mutation == "missing":
        value["target_id"] = "absent"
    elif mutation == "swapped":
        value["target_id"], value["sink_id"] = value["sink_id"], value["target_id"]
    else:
        value["sink_id"] = value["target_id"]
    before = state_path.read_bytes()
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        422,
        "INVALID_REFERENCE",
    )
    assert state_path.read_bytes() == before and not registry_path(state_path).exists()


def test_missing_identity_is_distinct_from_invalid_reference(client, state_path):
    value = definition(register_targets(client))
    assert_error(client.get("/api/v1/scenarios/absent"), 404, "SCENARIO_NOT_FOUND")
    assert_error(
        client.put("/api/v1/scenarios/absent", json={"revision": 0, "definition": value}),
        404,
        "SCENARIO_NOT_FOUND",
    )
    value["sink_id"] = "absent"
    assert_error(
        client.put("/api/v1/scenarios/absent", json={"revision": 0, "definition": value}),
        422,
        "INVALID_REFERENCE",
    )
    assert not registry_path(state_path).exists()


@pytest.mark.parametrize("source_change", ["removed", "corrupt", "unavailable", "changed"])
def test_history_has_no_current_draft_dependency(client, state_path, source_change, monkeypatch):
    from aiddos.api import store

    value = definition(register_targets(client))
    first = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}).json()[
        "scenario"
    ]
    retained = registry_path(state_path).read_bytes()
    if source_change == "removed":
        state_path.unlink()
    elif source_change == "corrupt":
        state_path.write_bytes(b"broken source")
    elif source_change == "changed":
        state = json.loads(state_path.read_bytes())
        state["targets"][0]["name"] = "Renamed current DUT"
        state_path.write_text(json.dumps(state))
    else:
        original_open = store.os.open

        def deny_source(path, *args, **kwargs):
            if path == state_path:
                raise PermissionError("private filesystem message")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(store.os, "open", deny_source)
    draft_before = state_path.read_bytes() if state_path.exists() else None
    page = client.get("/api/v1/scenarios")
    assert page.status_code == 200 and page.json()["items"] == [first]
    history = client.get(f"/api/v1/scenarios/{first['id']}")
    assert history.status_code == 200 and history.json()["versions"] == [first]
    response = client.put(
        f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
    )
    if source_change == "changed":
        assert response.status_code == 200
        assert response.json()["scenario"]["target_snapshot"]["name"] == "Renamed current DUT"
        assert client.get(f"/api/v1/scenarios/{first['id']}").json()["versions"][0] == first
    else:
        code = {
            "removed": "INVALID_REFERENCE",
            "corrupt": "STATE_CORRUPT",
            "unavailable": "STATE_UNAVAILABLE",
        }[source_change]
        assert_error(response, 422 if source_change == "removed" else 503, code)
        assert registry_path(state_path).read_bytes() == retained
    assert (state_path.read_bytes() if state_path.exists() else None) == draft_before


def test_competing_app_instances_have_one_cas_winner(client, state_path):
    value = definition(register_targets(client))
    barrier = Barrier(2)

    def save():
        with TestClient(
            create_app(state_path=state_path),
            base_url="http://localhost",
            raise_server_exceptions=False,
        ) as peer:
            barrier.wait(timeout=5)
            return peer.post("/api/v1/scenarios", json={"revision": 0, "definition": value})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save(), range(2)))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert_error(next(r for r in results if r.status_code != 201), 409, "SCENARIO_CONFLICT")
    assert client.get("/api/v1/scenarios").json()["revision"] == 1


def set_field(value, path, replacement):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[part]
    value[parts[-1]] = replacement


@pytest.mark.parametrize("action", ["ALLOW", "BLOCK", "ALERT"])
@pytest.mark.parametrize("delivery", ["ALLOW", "BLOCK"])
@pytest.mark.parametrize("detection", [False, True])
@pytest.mark.parametrize(
    "profile,protocol",
    [
        (profile, protocol)
        for profile in ("tcpreplay-policy", "k6-http")
        for protocol in ("TCP", "UDP", "DNS", "HTTP")
    ],
)
def test_policy_profile_truth_table(
    client, state_path, action, delivery, detection, profile, protocol
):
    value = definition(register_targets(client))
    value.update(
        expected_action=action,
        delivery_expectation=delivery,
        detection_required=detection,
        profile_id=profile,
        protocol=protocol,
    )
    value["success_criteria"].update(
        minimum_delivery_pct=0, detection_deadline_ms=60000 if detection else None
    )
    value["evidence_requirements"] = [
        "resource_metrics",
        "service_probe",
        "dut_events",
        "egress_pcap",
        "ingress_pcap",
    ]
    valid = ((action == "ALERT" and detection) or action == delivery) and (
        (profile == "k6-http") == (protocol == "HTTP")
    )
    response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    if valid:
        assert response.status_code == 201, response.text
        assert response.json()["scenario"]["definition"] == value
    else:
        assert_error(response, 422, "VALIDATION_ERROR")
        assert not registry_path(state_path).exists()


@pytest.mark.parametrize(
    "path,replacement",
    [
        ("ip_version", 4.0),
        ("ip_version", 6.0),
        ("ip_version", True),
        ("ip_version", "4"),
        ("stop_conditions.management_loss", 1),
        ("stop_conditions.management_loss", 1.0),
        ("stop_conditions.management_loss", False),
        ("stop_conditions.management_loss", "true"),
        ("detection_required", 0),
        ("detection_required", "false"),
        ("success_criteria.detection_deadline_ms", 1),
        ("success_criteria.minimum_delivery_pct", 100),
        ("success_criteria.maximum_delivery_pct", 99),
        ("stop_conditions.max_cpu_pct", 20),
        ("stop_conditions.max_memory_pct", 20),
        ("stop_conditions.max_sessions", 20),
        ("evidence_requirements", ["ingress_pcap", "egress_pcap"]),
        ("evidence_requirements", ["ingress_pcap", "service_probe"]),
        ("evidence_requirements", ["egress_pcap", "service_probe"]),
        (
            "evidence_requirements",
            ["ingress_pcap", "egress_pcap", "service_probe", "service_probe"],
        ),
        ("evidence_requirements", []),
        ("evidence_requirements", ["service_probe", "unknown"]),
        ("profile_id", "tcpdump-observer"),
        ("pcap_asset", {"label": "asset", "sha256": "A" * 64, "size_bytes": 1}),
        ("pcap_asset", {"label": "asset", "sha256": "a" * 64, "size_bytes": 1, "path": "/private"}),
        ("pcap_asset", {"label": "asset", "sha256": "a" * 64, "size_bytes": 67108865}),
        ("name", " \t "),
        ("name", "x\n"),
        ("name", "x\u200b"),
        ("name", "😀" * 121),
        ("objective", "x\u0000"),
        ("objective", "a" * 2001),
    ],
)
def test_invalid_definition_is_rejected_without_write(client, state_path, path, replacement):
    value = definition(register_targets(client))
    # Minimum > maximum is independently invalid rather than merely a stricter bound.
    if path == "success_criteria.minimum_delivery_pct":
        value["success_criteria"]["maximum_delivery_pct"] = 99
    set_field(value, path, replacement)
    before = state_path.read_bytes()
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    assert state_path.read_bytes() == before and not registry_path(state_path).exists()


@pytest.mark.parametrize("revision", [True, False, 0.0, "0", -1, 9007199254740991, None])
def test_revision_is_strict_bounded_integer(client, state_path, revision):
    value = definition(register_targets(client))
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": revision, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    assert not registry_path(state_path).exists()


@pytest.mark.parametrize(
    "scope",
    ["input", "definition", "traffic_budget", "success_criteria", "stop_conditions", "pcap_asset"],
)
def test_every_field_required_and_no_extras(client, state_path, scope):
    value = definition(register_targets(client))
    value["pcap_asset"] = {"label": "declared only", "sha256": "a" * 64, "size_bytes": 1}
    payload = {"revision": 0, "definition": value}

    def select(data):
        return (
            data
            if scope == "input"
            else (data["definition"] if scope == "definition" else data["definition"][scope])
        )

    for field in select(payload):
        invalid = deepcopy(payload)
        del select(invalid)[field]
        assert_error(client.post("/api/v1/scenarios", json=invalid), 422, "VALIDATION_ERROR")
    invalid = deepcopy(payload)
    select(invalid)["unexpected"] = False
    assert_error(client.post("/api/v1/scenarios", json=invalid), 422, "VALIDATION_ERROR")
    assert not registry_path(state_path).exists()


NUMERIC_BOUNDS = [
    ("traffic_budget.max_pps", 1, 1000000000),
    ("traffic_budget.max_bps", 1, 1000000000000),
    ("traffic_budget.max_packets", 1, 1000000000000),
    ("traffic_budget.max_bytes", 1, 1000000000000),
    ("traffic_budget.max_connections", 1, 1000000),
    ("traffic_budget.duration_seconds", 1, 3600),
    ("success_criteria.minimum_delivery_pct", 0, 100),
    ("success_criteria.maximum_delivery_pct", 0, 100),
    ("success_criteria.detection_deadline_ms", 1, 60000),
    ("stop_conditions.max_legitimate_loss_pct", 0, 100),
    ("stop_conditions.max_service_latency_ms", 1, 60000),
    ("stop_conditions.max_cpu_pct", 1, 100),
    ("stop_conditions.max_memory_pct", 1, 100),
    ("stop_conditions.max_sessions", 1, 1000000),
    ("pcap_asset.size_bytes", 1, 67108864),
]


@pytest.mark.parametrize("path,low,high", NUMERIC_BOUNDS)
def test_numeric_exact_boundaries_and_wrong_types(client, state_path, path, low, high):
    value = definition(register_targets(client))
    value["pcap_asset"] = {"label": " metadata, not a file ", "sha256": "a" * 64, "size_bytes": 1}
    value["detection_required"] = True
    value["success_criteria"] = {
        "minimum_delivery_pct": 0,
        "maximum_delivery_pct": 100,
        "detection_deadline_ms": 1,
    }
    if path.endswith("maximum_delivery_pct"):
        value.update(expected_action="BLOCK", delivery_expectation="BLOCK")
    value["evidence_requirements"] += ["dut_events", "resource_metrics"]
    for bad in (low - 1, high + 1, True, False, float(low), str(low), None):
        invalid = deepcopy(value)
        set_field(invalid, path, bad)
        # Nullable thresholds/deadline are covered separately, not invalid when null by itself.
        if bad is None and path in {
            "stop_conditions.max_cpu_pct",
            "stop_conditions.max_memory_pct",
            "stop_conditions.max_sessions",
        }:
            continue
        assert_error(
            client.post("/api/v1/scenarios", json={"revision": 0, "definition": invalid}),
            422,
            "VALIDATION_ERROR",
        )
    assert not registry_path(state_path).exists()
    for revision, bound in enumerate((low, high)):
        valid = deepcopy(value)
        set_field(valid, path, bound)
        response = client.post(
            "/api/v1/scenarios", json={"revision": revision, "definition": valid}
        )
        assert response.status_code == 201, response.text
        assert response.json()["scenario"]["definition"] == valid


def test_text_codepoints_multiline_and_declared_asset_are_literal(client):
    value = definition(register_targets(client))
    value.update(
        name="😀" * 120,
        objective=" \r\n\t" + "x" * 1995 + " ",
        dut_version=" v1 ",
        policy_version=" Straße Σς İ ",
    )
    value["pcap_asset"] = {
        "label": " ../../metadata only 😀 ",
        "sha256": "a" * 64,
        "size_bytes": 67108864,
    }
    response = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    assert response.status_code == 201, response.text
    assert response.json()["scenario"]["definition"] == value


def test_http_profile_cannot_claim_replay_asset(client, state_path):
    value = definition(register_targets(client))
    value.update(
        profile_id="k6-http",
        protocol="HTTP",
        pcap_asset={"label": "asset", "sha256": "a" * 64, "size_bytes": 1},
    )
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    assert not registry_path(state_path).exists()


@pytest.mark.parametrize(
    "query",
    [
        "offset=-1",
        "offset=101",
        "limit=0",
        "limit=101",
        "offset=00",
        "limit=01",
        "offset=+1",
        "limit=%2B1",
        "offset=1.0",
        "offset=1e0",
        "offset=true",
        "offset=",
        "offset=%201",
        "offset=１",
        "limit=",
        "offset=0&offset=0",
        "limit=1&limit=2",
        "other=0",
        "limit=1&other=0",
        "offset=99999999999999999999999999999999999999999",
    ],
)
def test_strict_pagination(client, state_path, query):
    assert_error(client.get("/api/v1/scenarios?" + query), 422, "VALIDATION_ERROR")
    assert not list(state_path.parent.iterdir())


@pytest.mark.parametrize("identity", ["UPPER", "has.dot", "a" * 65, "%20", "한글"])
def test_malformed_identity(client, identity):
    assert_error(client.get("/api/v1/scenarios/" + identity), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    "method,path",
    [
        ("delete", "/api/v1/scenarios"),
        ("patch", "/api/v1/scenarios"),
        ("delete", "/api/v1/scenarios/absent"),
        ("post", "/api/v1/scenarios/absent"),
    ],
)
def test_no_destructive_or_hidden_methods(client, state_path, method, path):
    assert_error(client.request(method, path, json={}), 405, "METHOD_NOT_ALLOWED")
    assert not list(state_path.parent.iterdir())


def test_scenario_transport_retains_shared_boundary_and_execution_denials(client, state_path):
    from scenario_producer import canonical

    value = definition(register_targets(client))
    valid = canonical({"revision": 0, "definition": value})
    malformed = [
        valid.replace(b'"revision":0', b'"revision":0,"revision":0'),
        valid.replace(b'"revision":0', b'"revision":0,"\\u0072evision":0'),
        valid.replace(b'"ip_version":4', b'"ip_version":4.0'),
        valid.replace(b'"ip_version":4', b'"ip_version":4e0'),
        valid.replace(b'"max_pps":10', b'"max_pps":1e1'),
        valid.replace(b'"revision":0', b'"revision":NaN'),
        b"\xff",
        b"[" * 33 + b"]" * 33,
    ]
    for raw in malformed:
        assert_error(
            client.post(
                "/api/v1/scenarios", content=raw, headers={"Content-Type": "application/json"}
            ),
            422,
            "VALIDATION_ERROR",
        )
    for headers, content, status, code in [
        (
            {"Origin": "https://foreign.invalid", "Content-Type": "application/json"},
            b"broken",
            403,
            "ORIGIN_NOT_ALLOWED",
        ),
        (
            {"Host": "foreign.invalid", "Content-Type": "application/json"},
            valid,
            403,
            "HOST_NOT_ALLOWED",
        ),
        ({"Content-Type": "text/plain"}, valid, 415, "JSON_REQUIRED"),
        (
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
            valid,
            415,
            "UNSUPPORTED_ENCODING",
        ),
        ({"Content-Type": "application/json"}, b" " * (256 * 1024 + 1), 413, "BODY_TOO_LARGE"),
    ]:
        assert_error(
            client.post("/api/v1/scenarios", content=content, headers=headers), status, code
        )
    assert not registry_path(state_path).exists()
    before = state_path.read_bytes()
    for route, code in [
        ("runs", "LIVE_NOT_AVAILABLE"),
        ("agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
        ("ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"),
        ("ai-settings/models", "AI_CONNECTION_NOT_AVAILABLE"),
    ]:
        for raw in (valid, b"broken"):
            assert_error(
                client.post(
                    "/api/v1/" + route, content=raw, headers={"Content-Type": "application/json"}
                ),
                409,
                code,
            )
    assert state_path.read_bytes() == before and not registry_path(state_path).exists()


def test_required_detection_evidence_and_block_lower_bound(client):
    value = definition(register_targets(client))
    value.update(expected_action="ALERT", delivery_expectation="BLOCK", detection_required=True)
    value["success_criteria"].update(
        minimum_delivery_pct=0, maximum_delivery_pct=0, detection_deadline_ms=1
    )
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    value["evidence_requirements"].append("dut_events")
    value["success_criteria"].update(minimum_delivery_pct=1, maximum_delivery_pct=1)
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    value["success_criteria"]["minimum_delivery_pct"] = 0
    assert (
        client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}).status_code
        == 201
    )


def test_mutation_validation_and_source_error_precedence(client, state_path):
    value = definition(register_targets(client))
    state_path.write_bytes(b"broken draft source")
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 100, "definition": value}),
        503,
        "STATE_CORRUPT",
    )
    registry_path(state_path).write_bytes(b"broken registry")
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 100, "definition": value}),
        503,
        "SCENARIO_STATE_CORRUPT",
    )
    del value["name"]
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 100, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    assert state_path.read_bytes() == b"broken draft source"
    assert registry_path(state_path).read_bytes() == b"broken registry"


def test_version_quota_does_not_publish_eleventh_version(client, state_path):
    value = definition(register_targets(client))
    created = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value})
    identity = created.json()["scenario"]["id"]
    for revision in range(1, 10):
        assert (
            client.put(
                f"/api/v1/scenarios/{identity}", json={"revision": revision, "definition": value}
            ).status_code
            == 200
        )
    before = registry_path(state_path).read_bytes()
    assert_error(
        client.put(f"/api/v1/scenarios/{identity}", json={"revision": 10, "definition": value}),
        409,
        "SCENARIO_LIMIT_REACHED",
    )
    assert registry_path(state_path).read_bytes() == before


def test_reachable_identity_version_quotas_and_full_pagination(client, state_path):
    value = definition(register_targets(client))
    source = state_path.read_bytes()
    records = []
    for revision in range(100):
        response = client.post(
            "/api/v1/scenarios", json={"revision": revision, "definition": value}
        )
        assert response.status_code == 201, response.text
        records.append(response.json()["scenario"])
    before = registry_path(state_path).read_bytes()
    assert_error(
        client.post("/api/v1/scenarios", json={"revision": 100, "definition": value}),
        409,
        "SCENARIO_LIMIT_REACHED",
    )
    assert registry_path(state_path).read_bytes() == before
    first_page = client.get("/api/v1/scenarios").json()
    assert first_page["items"] == records[:50] and first_page["total"] == 100
    for offset, limit in ((0, 100), (37, 63), (100, 100)):
        page = client.get(f"/api/v1/scenarios?offset={offset}&limit={limit}")
        assert page.status_code == 200 and len(page.content) <= 1024 * 1024
        assert page.json() == {
            "revision": 100,
            "total": 100,
            "offset": offset,
            "limit": limit,
            "items": records[offset : offset + limit],
            "execution_enabled": False,
        }
    revision = 100
    for first in records:
        versions = [first]
        for version in range(2, 11):
            response = client.put(
                f"/api/v1/scenarios/{first['id']}", json={"revision": revision, "definition": value}
            )
            assert response.status_code == 200, response.text
            revision += 1
            assert response.json()["revision"] == revision
            record = response.json()["scenario"]
            assert record["version"] == version and record["digest"] == digest(record)
            versions.append(record)
        before = registry_path(state_path).read_bytes()
        assert_error(
            client.put(
                f"/api/v1/scenarios/{first['id']}", json={"revision": revision, "definition": value}
            ),
            409,
            "SCENARIO_LIMIT_REACHED",
        )
        assert registry_path(state_path).read_bytes() == before
        history = client.get(f"/api/v1/scenarios/{first['id']}")
        assert history.json()["versions"] == versions and len(history.content) <= 256 * 1024
    assert revision == 1000
    persisted = json.loads(registry_path(state_path).read_bytes())
    assert persisted["revision"] == sum(len(s["versions"]) for s in persisted["scenarios"]) == 1000
    assert len(registry_path(state_path).read_bytes()) <= 16 * 1024 * 1024
    assert state_path.read_bytes() == source


def test_complete_record_utf8_byte_limit_exact_and_plus_one(client, state_path, monkeypatch):
    from scenario_producer import canonical

    from aiddos.api import scenario_store

    monkeypatch.setattr(scenario_store, "timestamp", lambda: "2026-10-09T00:00:00+00:00")
    value = definition(register_targets(client))
    first = client.post("/api/v1/scenarios", json={"revision": 0, "definition": value}).json()[
        "scenario"
    ]
    candidate = deepcopy(first)
    candidate["definition"]["objective"] = ""
    available = 8192 - len(canonical(candidate))
    value["objective"] = "😀" * (available // 4) + "a" * (available % 4)
    assert len(value["objective"]) <= 2000
    response = client.put(
        f"/api/v1/scenarios/{first['id']}", json={"revision": 1, "definition": value}
    )
    assert response.status_code == 200, response.text
    assert len(canonical(response.json()["scenario"])) == 8192
    before = registry_path(state_path).read_bytes()
    value["objective"] += "a"
    assert_error(
        client.put(f"/api/v1/scenarios/{first['id']}", json={"revision": 2, "definition": value}),
        422,
        "VALIDATION_ERROR",
    )
    assert registry_path(state_path).read_bytes() == before
