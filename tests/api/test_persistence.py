import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app

TARGET = {"name": "Lab", "address": "localhost", "kind": "DUT"}


@pytest.mark.parametrize(
    "raw",
    [
        b"broken",
        b"{}",
        b"[]",
        b"null",
        b'{"format_version":1,"format_version":1}',
        b'{"format_version":2}',
        b"\xff",
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_corrupt_state_is_not_empty_success_or_overwritten(client, state_path, raw):
    state_path.write_bytes(raw)
    for method, route, payload in [("get", "workspace", None), ("post", "targets", TARGET)]:
        response = getattr(client, method)(
            f"/api/v1/{route}", **({"json": payload} if payload else {})
        )
        assert response.status_code == 503
        assert response.json() == {
            "code": "STATE_CORRUPT",
            "message": "Draft state is invalid; restore it before editing.",
        }
        assert str(state_path) not in response.text
        assert state_path.read_bytes() == raw
    assert client.get("/api/v1/health").status_code == 200  # Liveness, not a storage health claim.
    assert client.post("/api/v1/runs", json={}).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        "unknown_field",
        "oversized_name",
        "unknown_agent_skill",
        "duplicate_id",
        "bad_timestamp",
        "live_flag",
        "wrong_total",
        "missing_field",
        "bool_version",
        "oversized_skills",
    ],
)
def test_persisted_state_is_readmitted_under_closed_schema(client, state_path, change):
    assert client.post("/api/v1/targets", json=TARGET).status_code == 201
    value = json.loads(state_path.read_text())
    if change == "unknown_field":
        value["secret"] = "private-value"
    elif change == "oversized_name":
        value["targets"][0]["name"] = "x" * 121
    elif change == "unknown_agent_skill":
        value["agent_profile"]["skill_ids"] = ["missing"]
    elif change == "duplicate_id":
        value["targets"].append(value["targets"][0])
    elif change == "bad_timestamp":
        value["targets"][0]["created_at"] = "yesterday"
    elif change == "live_flag":
        value["agent_profile"]["execution_enabled"] = True
    elif change == "wrong_total":
        value["audit_total"] = 0
    elif change == "missing_field":
        del value["targets"][0]["status"]
    elif change == "bool_version":
        value["format_version"] = True
    elif change == "oversized_skills":
        value["skills"] = [None] * 101
    raw = json.dumps(value).encode()
    state_path.write_bytes(raw)
    with TestClient(
        create_app(state_path=state_path),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as restarted:
        response = restarted.get("/api/v1/workspace")
        assert response.status_code == 503
        assert response.json()["code"] == "STATE_CORRUPT"
        assert restarted.post("/api/v1/targets", json=TARGET).status_code == 503
    assert state_path.read_bytes() == raw


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_failed_atomic_write_preserves_committed_state_and_cleans_temporary_file(
    client, state_path, monkeypatch, failure
):
    assert client.post("/api/v1/targets", json=TARGET).status_code == 201
    before = state_path.read_bytes()
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise OSError("private filesystem path /do-not-leak")

    with monkeypatch.context() as context:
        context.setattr(os, failure, fail)
        response = client.post("/api/v1/targets", json={**TARGET, "name": "Uncommitted"})
    assert calls
    assert response.status_code == 503
    assert response.json() == {
        "code": "STATE_UNAVAILABLE",
        "message": "Draft storage is unavailable.",
    }
    assert state_path.read_bytes() == before
    assert list(state_path.parent.glob(".ui-drafts-*")) == []
    snapshot = client.get("/api/v1/workspace").json()
    assert len(snapshot["targets"]) == len(snapshot["audit"]) == 1


def test_directory_sync_failure_reports_uncertain_commit_not_false_rollback(
    client, state_path, monkeypatch
):
    assert client.post("/api/v1/targets", json=TARGET).status_code == 201
    original_fsync = os.fsync
    calls = 0

    def fail_directory_sync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory persistence failure")
        original_fsync(descriptor)

    with monkeypatch.context() as context:
        context.setattr(os, "fsync", fail_directory_sync)
        response = client.post("/api/v1/targets", json={**TARGET, "name": "Published"})
    assert calls == 2
    assert response.status_code == 503
    assert response.json()["code"] == "STATE_COMMIT_UNCERTAIN"
    workspace = client.get("/api/v1/workspace").json()
    assert len(workspace["targets"]) == 2
    assert workspace["targets"][-1]["name"] == "Published"
    assert len(workspace["audit"]) == 2
    assert list(state_path.parent.glob(".ui-drafts-*")) == []


def test_oversized_state_is_rejected_and_never_overwritten(client, state_path):
    with state_path.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    response = client.get("/api/v1/workspace")
    assert response.status_code == 503
    assert response.json()["code"] == "STATE_CORRUPT"
    assert client.post("/api/v1/targets", json=TARGET).status_code == 503
    assert state_path.stat().st_size == 16 * 1024 * 1024 + 1


def test_state_symlink_is_never_followed_or_replaced(client, state_path):
    actual = state_path.with_name("owner.json")
    actual.write_text("private original bytes")
    state_path.symlink_to(actual)
    response = client.post("/api/v1/targets", json=TARGET)
    assert response.status_code == 503
    assert state_path.is_symlink()
    assert actual.read_text() == "private original bytes"


@pytest.mark.parametrize(
    "change",
    [
        "skill_name",
        "skill_description",
        "skill_instructions",
        "template_shadow",
        "skill_status",
        "skill_permission",
        "skill_safety",
        "translation",
        "audit_action",
        "audit_reference",
    ],
)
def test_replay_cannot_invent_catalog_authority_or_unbounded_guidance(client, state_path, change):
    skill = client.post(
        "/api/v1/skills",
        json={
            "name": "Review",
            "description": "Local",
            "instructions": "Read only",
            "category": "analysis",
        },
    ).json()
    assert skill["status"] == "draft"
    value = json.loads(state_path.read_text())
    item = value["skills"][0]
    if change == "skill_name":
        item["name"]["en"] = "x" * 121
    elif change == "skill_description":
        item["description"]["en"] = "x" * 1001
    elif change == "skill_instructions":
        item["instructions"]["en"] = "x" * 8001
    elif change == "template_shadow":
        item["id"] = "policy-validation"
    elif change == "skill_status":
        item["status"] = "template"
    elif change == "skill_permission":
        item["allowed_operations"] = ["execute_anything"]
    elif change == "skill_safety":
        item["safety_rules"] = []
    elif change == "translation":
        item["instructions"]["ko"] = "Invented translation"
    elif change == "audit_action":
        value["audit"][0]["action"] = "run.succeeded"
    elif change == "audit_reference":
        value["audit"][0]["entity_id"] = "unknown"
    raw = json.dumps(value).encode()
    state_path.write_bytes(raw)
    response = client.get("/api/v1/workspace")
    assert response.status_code == 503
    assert response.json()["code"] == "STATE_CORRUPT"
    assert state_path.read_bytes() == raw


def test_environment_path_is_used_without_import_time_write(tmp_path, monkeypatch):
    path = tmp_path / "configured" / "drafts.json"
    monkeypatch.setenv("AIDDOS_UI_STATE_PATH", str(path))
    with TestClient(
        create_app(), base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        assert not path.exists()
        assert client.post("/api/v1/targets", json=TARGET).status_code == 201
    assert path.exists()


def test_same_process_factories_share_lock_and_preserve_concurrent_writes(state_path):
    with (
        TestClient(
            create_app(state_path=state_path),
            base_url="http://localhost",
            raise_server_exceptions=False,
        ) as one,
        TestClient(
            create_app(state_path=state_path),
            base_url="http://localhost",
            raise_server_exceptions=False,
        ) as two,
    ):

        def create(index):
            return (one if index % 2 else two).post(
                "/api/v1/targets", json={**TARGET, "name": str(index)}
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(create, range(24)))
        assert all(response.status_code == 201 for response in responses)
        workspace = one.get("/api/v1/workspace").json()
        assert len(workspace["targets"]) == len(workspace["audit"]) == 24
        assert {target["name"] for target in workspace["targets"]} == {str(i) for i in range(24)}
