"""Durable internal scenario grants; real JSON resolver and SQLite ledger."""

import socket
import subprocess
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
import test_chat_scenario_grant_staging as staging
from fastapi.testclient import TestClient
from test_chat_tool_storage import admission

from aiddos.api import chat_tool_storage
from aiddos.api.app import create_app
from aiddos.api.chat_models import encoded, now
from aiddos.api.chat_tool_models import GrantRequest, instant
from aiddos.api.chat_tool_storage import CAPS, POOL_BYTES, TURN_RESERVATION
from aiddos.api.errors import DraftError


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Grant staging attempted network/DNS/process execution")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(state_path=tmp_path / "draft.json"),
                    base_url="http://localhost") as connection:
        yield connection


def test_direct_v4_admission_has_no_writes(client):
    runtime, body, _ = staging.bootstrap(client)
    grant, _ = staging.issue(client, runtime, body)

    def exercise():
        session, _ = runtime.storage.session(body["session_id"])
        advanced, turn, commitment = admission(session, body["turn_request_id"])
        turn.update(user_text=body["text"], created_at=now())
        commitment["text"] = body["text"]
        before = list(runtime.storage.db.iterdump())
        try:
            runtime.ledger.admit(grant["id"], advanced, turn, commitment)
        except DraftError as exc:
            assert exc.code == "CHAT_TOOL_GRANT_INVALID"
        else:
            raise AssertionError("v4 admission did not refuse")
        assert list(runtime.storage.db.iterdump()) == before
        assert runtime.ledger.grant(grant["id"]) == grant

    client.portal.call(exercise)


def legacy_body(body, version):
    if version == 4:
        return deepcopy(body)
    result = {k: v for k, v in body.items() if k not in {"schema_version", "scope", "intent"}}
    if version != 1:
        result.update(
            schema_version=version, scope={2: "target_create", 3: "skill_create"}[version]
        )
    return result


def issue_version(client, runtime, body, version):
    if version == 4:
        return staging.issue(client, runtime, body)
    value = GrantRequest.model_validate(legacy_body(body, version)).root
    return client.portal.call(runtime.create_grant, value)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_validated_request_instances_remain_supported(client, version):
    runtime, body, _ = staging.bootstrap(client)
    value = GrantRequest.model_validate(legacy_body(body, version))
    grant, replay = client.portal.call(runtime.ledger.create_grant, value)
    assert not replay and grant["schema_version"] == version
    assert client.portal.call(runtime.ledger.create_grant, value) == (grant, True)


@pytest.mark.parametrize("prior,next_version", [
    (a, b) for a in range(1, 5) for b in range(1, 5) if a != b
])
def test_all_cross_version_request_conflicts(client, monkeypatch, prior, next_version):
    runtime, body, _ = staging.bootstrap(client)
    grant, _ = issue_version(client, runtime, body, prior)

    def forbidden(*args, **kwargs):
        raise AssertionError("request conflict performed a fresh lookup")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_CONFLICT"):
        issue_version(client, runtime, body, next_version)
    assert client.portal.call(runtime.ledger.grant, grant["id"]) == grant


def test_mixed_legacy_v4_reopen_expires_only_pending_and_replays(client, monkeypatch):
    runtime, body, _ = staging.bootstrap(client)
    records = []
    for version in (1, 2, 3):
        grant, _ = issue_version(client, runtime, body | {"request_id": str(uuid4())}, version)
        records.append(client.portal.call(runtime.revoke_grant, grant["id"]))
    grant, _ = staging.issue(client, runtime, body)
    assert (instant(grant["expires_at"]) - instant(grant["created_at"])).total_seconds() == 300

    def reopen():
        runtime.storage.close()
        assert runtime.storage.open()
        runtime.storage.validate()
        assert runtime.storage.db.execute("PRAGMA user_version").fetchone() == (2,)
        return runtime.ledger.grant(grant["id"])

    assert client.portal.call(reopen) == grant | {"status": "expired"}
    for old in records:
        assert client.portal.call(runtime.ledger.grant, old["id"]) == old

    def forbidden(*args, **kwargs):
        raise AssertionError("expired replay touched domain")

    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", forbidden)
    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    assert staging.issue(client, runtime, body) == (grant | {"status": "expired"}, 200)


@pytest.mark.parametrize("mutation", [
    "digest", "extra", "scope", "session", "profile", "settings", "identity", "ttl",
    "operator_inputs", "sequence", "consumed", "bound_consumed", "bound_revoked",
])
def test_tampered_reopen_rejected_before_any_recovery(client, mutation):
    runtime, body, _ = staging.bootstrap(client)
    grant, _ = staging.issue(client, runtime, body)

    def tamper():
        changed = deepcopy(grant)
        if mutation.startswith("bound_"):
            runtime.ledger.revoke(grant["id"])
            old, _ = runtime.ledger.create_grant(
                legacy_body(body | {"request_id": str(uuid4())}, 1)
            )
            session, _ = runtime.storage.session(body["session_id"])
            advanced, turn, commitment = admission(session, body["turn_request_id"])
            turn.update(user_text=body["text"], created_at=now())
            commitment["text"] = body["text"]
            runtime.ledger.admit(old["id"], advanced, turn, commitment)
            changed.update(id=old["id"], request_id=old["request_id"], status=mutation[6:])
            runtime.storage.db.execute("DELETE FROM tool_grants WHERE key=?", (grant["id"],))
        elif mutation == "digest":
            changed["inputs_digest"] = "f" * 64
        elif mutation == "extra":
            changed["extra"] = 1
        elif mutation == "scope":
            changed["proposal_tools"] = ["scenario_append"]
        elif mutation == "session":
            changed["session_id"] = str(uuid4())
        elif mutation == "profile":
            changed["profile_id"] = "other"
        elif mutation == "settings":
            changed["settings_revision"] += 1
        elif mutation == "identity":
            changed["id"] = str(uuid4())
        elif mutation == "ttl":
            changed["expires_at"] = (
                instant(grant["expires_at"]) + timedelta(seconds=1)
            ).isoformat()
        elif mutation == "operator_inputs":
            changed["resolved_inputs"]["policy_version"] = "wrong"
        elif mutation == "sequence":
            changed["expected_sequence"] = 65
        else:
            changed["status"] = "consumed"
        key = changed["id"] if mutation.startswith("bound_") else grant["id"]
        runtime.storage.db.execute(
            "UPDATE tool_grants SET data=? WHERE key=?", (encoded(changed).decode(), key)
        )
        runtime.storage.db.commit()
        runtime.storage.close()
        before = runtime.storage.path.read_bytes()
        try:
            runtime.storage.open()
        except DraftError as exc:
            assert exc.code == "CHAT_STORAGE_ERROR"
        else:
            raise AssertionError("invalid staging graph reopened")
        assert runtime.storage.path.read_bytes() == before
        assert runtime.storage.db is None

    client.portal.call(tamper)


def test_one_pending_expiry_and_missing_resolution_fail_closed(client):
    runtime, body, _ = staging.bootstrap(client)
    grant, _ = staging.issue(client, runtime, body)
    with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_CONFLICT"):
        staging.issue(client, runtime, body | {"request_id": str(uuid4())})

    def exercise():
        other = body | {"request_id": str(uuid4())}
        before = list(runtime.storage.db.iterdump())
        try:
            runtime.ledger.create_grant(other)
        except DraftError as exc:
            assert exc.code == "CHAT_TOOL_GRANT_INVALID"
        else:
            raise AssertionError("new v4 grant trusted missing source resolution")
        assert list(runtime.storage.db.iterdump()) == before
        resolved = {k: grant[k] for k in ("resolved_inputs", "inputs_digest")}
        new, replay = runtime.ledger.create_grant(
            other, resolved=resolved, timestamp=grant["expires_at"]
        )
        assert not replay and new["status"] == "pending"
        assert runtime.ledger.grant(grant["id"])["status"] == "expired"
        assert runtime.ledger.create_grant(body) == (grant | {"status": "expired"}, True)

    client.portal.call(exercise)


def test_sqlite_grant_write_fault_fires_and_preserves_transaction_truth(client):
    runtime, body, _ = staging.bootstrap(client)
    fired = []

    def install():
        runtime.storage.db.create_function("fault", 0, lambda: fired.append(True) or 1)
        runtime.storage.db.execute(
            "CREATE TEMP TRIGGER grant_fault BEFORE INSERT ON tool_grants "
            "BEGIN SELECT fault(); SELECT RAISE(ABORT, 'owned fault'); END"
        )

    client.portal.call(install)
    with pytest.raises(DraftError, match="CHAT_COMMIT_UNCERTAIN"):
        staging.issue(client, runtime, body)
    assert fired == [True] and runtime.storage.fenced

    def inspect():
        assert not runtime.storage.db.in_transaction
        assert runtime.storage.db.execute("SELECT count(*) FROM tool_grants").fetchone() == (0,)
        assert runtime.storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)

    client.portal.call(inspect)
    assert runtime.grant_deadlines == {} and not runtime.preparing


@pytest.mark.parametrize("fault", ["digest", "extra", "missing", "inputs"])
def test_internal_resolution_codec_fails_closed(client, fault):
    runtime, body, _ = staging.bootstrap(client)

    async def exercise():
        session, _ = runtime.storage.session(body["session_id"])
        resolved = await runtime.worker.resolve_scenario_intent(
            body["intent"], session["settings_revision"]
        )
        if fault == "digest":
            resolved["inputs_digest"] = "f" * 64
        elif fault == "extra":
            resolved["extra"] = True
        elif fault == "missing":
            del resolved["inputs_digest"]
        else:
            resolved["resolved_inputs"]["policy_version"] = "not the operator input"
        before = list(runtime.storage.db.iterdump())
        try:
            runtime.ledger.create_grant(body, resolved=resolved)
        except (DraftError, ValueError):
            pass
        else:
            raise AssertionError("inconsistent resolved input published")
        assert list(runtime.storage.db.iterdump()) == before

    client.portal.call(exercise)


@pytest.mark.parametrize("limit", ["count", "pool"])
def test_real_grant_quota_rollback_and_no_extra_identity(client, monkeypatch, limit):
    runtime, body, _ = staging.bootstrap(client)
    grant, _ = staging.issue(client, runtime, body)
    resolved = {k: grant[k] for k in ("resolved_inputs", "inputs_digest")}
    assert CAPS["tool_grants"] == 8192
    assert POOL_BYTES == 2097152 and TURN_RESERVATION == 1048576

    def fill():
        previous = grant
        # Every occupancy record is created by the real ledger, not SQL seeds.
        # The same immutable real resolution is internal actor input for pool v4.
        for _ in range(2047):
            request = body | {"request_id": str(uuid4())}
            if limit == "count":
                request = legacy_body(request, 1)
            before = list(runtime.storage.db.iterdump())
            try:
                new, replay = runtime.ledger.create_grant(
                    request, resolved=resolved if limit == "pool" else None,
                    timestamp=previous["expires_at"],
                )
            except DraftError as exc:
                assert limit == "pool" and exc.code == "CHAT_TOOL_LIMIT"
                assert list(runtime.storage.db.iterdump()) == before
                assert runtime.ledger.grant(previous["id"])["status"] == "pending"
                assert runtime.ledger.usage()["actual"] <= POOL_BYTES
                break
            assert not replay
            previous = new
        else:
            assert limit == "count"
            assert len(runtime.ledger._rows("tool_grants")) == 2048

            def forbidden():
                raise AssertionError("full count allocated another grant identity")

            monkeypatch.setattr(chat_tool_storage, "uuid4", forbidden)
            before = list(runtime.storage.db.iterdump())
            try:
                runtime.ledger.create_grant(
                    body | {"request_id": str(uuid4())}, resolved=resolved,
                    timestamp=previous["expires_at"],
                )
            except DraftError as exc:
                assert exc.code == "CHAT_TOOL_LIMIT"
            else:
                raise AssertionError("grant table exceeded 2048 records")
            assert list(runtime.storage.db.iterdump()) == before
        runtime.storage.validate()

    client.portal.call(fill)
