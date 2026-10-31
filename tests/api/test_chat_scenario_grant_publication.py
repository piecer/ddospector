"""Original-clock probe: real ledger work, ordinary delayed async completion.

No product clock/SQL/result/transaction is replaced. Native stores and the real
resolver are used. A final settings await is delayed within its existing budget;
all work after it is unchanged production code, observed via SQLite tracing.
"""

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import threading
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest
import test_chat_scenario_grant_staging as staging
from fastapi.testclient import TestClient
from test_chat_scenario_grant_ledger import legacy_body

from aiddos.api import chat_tool_storage
from aiddos.api.app import create_app
from aiddos.api.chat_models import now
from aiddos.api.chat_scenario_models import GrantInputV4
from aiddos.api.chat_tool_models import GrantRequest, instant
from aiddos.api.errors import DraftError


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("independent review attempted network/DNS/process")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as c:
        yield c


@pytest.mark.parametrize("mode", ["on_time", "near_deadline"])
def test_sync_ledger_cannot_publish_after_original_clock(client, monkeypatch, mode, tmp_path):
    runtime, body, _ = staging.bootstrap(client)

    # Ordinary retained legacy history, produced/revoked through the actual
    # ledger. No SQL seeding, extra DB owner, fake records, or quota changes.
    def seed():
        for _ in range(768):
            grant, replay = runtime.ledger.create_grant(
                legacy_body(body | {"request_id": str(uuid4())}, 1)
            )
            assert not replay
            runtime.ledger.revoke(grant["id"])
        runtime.storage.validate()
        return len(runtime.ledger._rows("tool_grants"))

    initial_count = client.portal.call(seed)
    monkeypatch.setattr(runtime, "turn_seconds", 0.5)
    real_snapshot = runtime.worker.ai_snapshot
    observations = {"mode": mode, "initial_count": initial_count, "snapshots": [], "sql": []}

    async def final_read_delay(**kwargs):
        result = await real_snapshot(**kwargs)
        observations["snapshots"].append({"deadline": kwargs["deadline"], "returned": monotonic()})
        if len(observations["snapshots"]) == 2:
            observations["deadline"] = kwargs["deadline"]
            if mode == "near_deadline":
                # Leave time for the caller's actual pre-ledger check. The
                # unchanged retained-row scans then consume the final budget.
                await asyncio.sleep(max(0, kwargs["deadline"] - monotonic() - 0.004))
            observations["final_await_return"] = monotonic()
        return result

    monkeypatch.setattr(runtime.worker, "ai_snapshot", final_read_delay)

    def trace(sql):
        if sql.startswith(("BEGIN IMMEDIATE", "INSERT INTO tool_grants", "COMMIT", "ROLLBACK")):
            observations["sql"].append({"operation": sql.split(" VALUES")[0], "time": monotonic()})

    async def exercise():
        runtime.storage.db.set_trace_callback(trace)
        try:
            try:
                grant, status = await runtime.create_grant(GrantInputV4.model_validate(body))
                observations.update(outcome="success", status=status, grant_id=grant["id"])
            except DraftError as exc:
                observations.update(outcome="error", code=exc.code)
            observations["finished"] = monotonic()
        finally:
            runtime.storage.db.set_trace_callback(None)
        rows = runtime.ledger._rows("tool_grants")
        observations["final_count"] = len(rows)
        observations["retained_new"] = [g for _, g in rows if g["request_id"] == body["request_id"]]
        observations["grant_deadlines"] = dict(runtime.grant_deadlines)
        observations["preparing"] = runtime.preparing
        observations["in_transaction"] = runtime.storage.db.in_transaction
        observations["fenced"] = runtime.storage.fenced
        runtime.storage.validate()

    client.portal.call(exercise)
    Path(os.environ.get("REVIEW_OUTPUT", str(tmp_path)), mode + ".json").write_text(
        json.dumps(observations, indent=2) + "\n"
    )
    print(
        "CLOCK_PROBE",
        json.dumps({k: v for k, v in observations.items() if k != "retained_new"}),
        flush=True,
    )
    assert len(observations["snapshots"]) == 2
    assert len({s["deadline"] for s in observations["snapshots"]}) == 1
    assert not observations["preparing"] and not observations["in_transaction"]
    if mode == "on_time":
        assert observations["outcome"] == "success"
        assert observations["status"] == 201 and observations["final_count"] == initial_count + 1
        assert observations["finished"] < observations["deadline"]
    else:
        # First prove the required interleaving, independent of the verdict.
        begins = [x for x in observations["sql"] if x["operation"] == "BEGIN IMMEDIATE"]
        assert begins and begins[0]["time"] < observations["deadline"], (
            "probe did not enter synchronous ledger on time"
        )
        assert observations["finished"] > observations["deadline"], (
            "probe did not cross original deadline"
        )
        assert observations["outcome"] == "error" and observations["code"] == "CHAT_TIMEOUT", (
            "late grant publication returned success"
        )
        assert observations["final_count"] == initial_count and observations["retained_new"] == []
        assert observations["grant_deadlines"] == {}


def durable_image(runtime):
    """Observe committed bytes without reopening/migrating the owning facade."""
    with closing(sqlite3.connect(runtime.storage.path.as_uri() + "?mode=ro", uri=True)) as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("sessions", "turns", *chat_tool_storage.TABLES)
        }


def seed_expirable(client, runtime, body):
    def seed():
        grant, replay = runtime.ledger.create_grant(
            legacy_body(body | {"request_id": str(uuid4())}, 1),
            timestamp=(instant(now()) - timedelta(seconds=301)).isoformat(),
        )
        assert not replay and grant["status"] == "pending"
        return grant

    return client.portal.call(seed)


def assert_no_runtime_publication(runtime):
    assert runtime.grant_deadlines == {}
    assert not runtime.preparing and not runtime.worker.busy
    assert runtime.active is None and runtime.task is None
    assert not runtime.storage.db.in_transaction
    assert runtime.ledger._rows("tool_bindings") == []
    assert runtime.ledger._rows("tool_reservations") == []
    assert runtime.storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)


@pytest.mark.parametrize("phase", ["before_publication", "after_pool"])
@pytest.mark.parametrize(
    "cause,code",
    [
        ("timeout", "CHAT_TIMEOUT"),
        ("stop", "CHAT_CANCELLED"),
        ("shutdown", "CHAT_SHUTTING_DOWN"),
    ],
)
def test_runtime_guard_after_real_preparation_rolls_back(client, monkeypatch, phase, cause, code):
    """Explicit seam injection; real clocks, preparation, INSERT and pool meter.

    Unlike the unmodified retained-history probe above, this deliberately changes
    authority at a named synchronous boundary to cover both callback obligations.
    """
    runtime, body, _ = staging.bootstrap(client)
    old = seed_expirable(client, runtime, body)
    before = durable_image(runtime)
    monkeypatch.setattr(runtime, "turn_seconds", 0.5)
    captured = {}
    fired = []
    real_snapshot = runtime.worker.ai_snapshot

    async def snapshot(**kwargs):
        result = await real_snapshot(**kwargs)
        captured.update(kwargs)
        return result

    def invalidate():
        assert not fired
        fired.append(True)
        assert runtime.storage.db.in_transaction
        if cause == "timeout":
            sleep(max(0, captured["deadline"] - monotonic()) + 0.002)
        else:
            captured["stop"].set()
            # Authority is the locally captured Event, not a later replacement.
            runtime.stop_signal = threading.Event()
            if cause == "shutdown":
                runtime.stopping = True

    real_json = chat_tool_storage.json_value
    real_usage = runtime.ledger.usage

    def json_then_invalidate(value):
        result = real_json(value)
        invalidate()
        return result

    def usage_then_invalidate():
        result = real_usage()
        if runtime.storage.db.execute(
            "SELECT 1 FROM tool_grants WHERE json_extract(data, '$.request_id')=?",
            (body["request_id"],),
        ).fetchone():
            invalidate()
        return result

    monkeypatch.setattr(runtime.worker, "ai_snapshot", snapshot)
    if phase == "before_publication":
        monkeypatch.setattr(chat_tool_storage, "json_value", json_then_invalidate)
    else:
        monkeypatch.setattr(runtime.ledger, "usage", usage_then_invalidate)
    try:
        with pytest.raises(DraftError) as exc:
            staging.issue(client, runtime, body)
        assert exc.value.code == code and fired == [True]
        assert durable_image(runtime) == before
        client.portal.call(assert_no_runtime_publication, runtime)
        assert client.portal.call(runtime.ledger.grant, old["id"]) == old
        assert not runtime.storage.fenced
    finally:
        monkeypatch.setattr(chat_tool_storage, "json_value", real_json)
        monkeypatch.setattr(runtime.ledger, "usage", real_usage)
        runtime.stopping = False
    grant, status = staging.issue(client, runtime, body)
    assert status == 201 and grant["status"] == "pending"
    assert client.portal.call(runtime.ledger.grant, old["id"])["status"] == "expired"
    client.portal.call(runtime.storage.validate)


@pytest.mark.parametrize("check_number", [1, 2])
@pytest.mark.parametrize("error_type", [DraftError, ValueError, asyncio.CancelledError])
def test_callback_original_error_and_runtime_cleanup(client, monkeypatch, check_number, error_type):
    """Explicit same-process callback fault; the real ledger/transaction run."""
    runtime, body, _ = staging.bootstrap(client)
    old = seed_expirable(client, runtime, body)
    before = durable_image(runtime)
    marker = error_type("CHAT_CANCELLED" if error_type is DraftError else "owned callback fault")
    real_create = runtime.ledger.create_grant
    seen = []

    def create_with_fault(value, **kwargs):
        original_guard = kwargs["publication_guard"]

        def guard():
            original_guard()
            seen.append(True)
            if len(seen) == check_number:
                raise marker

        return real_create(value, **(kwargs | {"publication_guard": guard}))

    monkeypatch.setattr(runtime.ledger, "create_grant", create_with_fault)

    async def exercise():
        with pytest.raises(error_type) as exc:
            await runtime.create_grant(GrantInputV4.model_validate(body))
        assert exc.value is marker
        assert durable_image(runtime) == before
        assert_no_runtime_publication(runtime)
        assert runtime.ledger.grant(old["id"]) == old
        assert not runtime.storage.fenced

    client.portal.call(exercise)
    assert len(seen) == check_number
    monkeypatch.setattr(runtime.ledger, "create_grant", real_create)
    assert staging.issue(client, runtime, body)[1] == 201
    client.portal.call(runtime.storage.validate)


def test_guard_rollback_failure_retains_original_error_and_fence(client, monkeypatch):
    """Real SQLite authorizer denies ROLLBACK; no fake connection or ledger."""
    runtime, body, _ = staging.bootstrap(client)
    seed_expirable(client, runtime, body)
    before = durable_image(runtime)
    marker = DraftError("CHAT_CANCELLED")
    real_create = runtime.ledger.create_grant
    denied = []
    checks = []

    def authorizer(action, arg1, arg2, database, source):
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "ROLLBACK":
            denied.append(True)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def create_with_fault(value, **kwargs):
        original_guard = kwargs["publication_guard"]

        def guard():
            original_guard()
            checks.append(True)
            if len(checks) == 2:
                runtime.storage.db.set_authorizer(authorizer)
                raise marker

        return real_create(value, **(kwargs | {"publication_guard": guard}))

    monkeypatch.setattr(runtime.ledger, "create_grant", create_with_fault)

    async def exercise():
        try:
            with pytest.raises(DraftError) as exc:
                await runtime.create_grant(GrantInputV4.model_validate(body))
            assert exc.value is marker and denied == [True] and len(checks) == 2
            assert durable_image(runtime) == before
            # Failed rollback is NOT a closed or absent writer transaction.
            assert runtime.storage.fenced and runtime.storage.db.in_transaction
            assert runtime.storage.db.execute("SELECT count(*) FROM tool_grants").fetchone() == (2,)
            assert runtime.grant_deadlines == {} and not runtime.preparing
            assert runtime.active is None and runtime.task is None and not runtime.worker.busy
            with pytest.raises(DraftError, match="CHAT_COMMIT_UNCERTAIN"):
                await runtime.create_grant(GrantInputV4.model_validate(body))
        finally:
            runtime.storage.db.set_authorizer(None)
            runtime.storage.db.rollback()
        assert not runtime.storage.db.in_transaction and runtime.storage.fenced
        assert durable_image(runtime) == before

    client.portal.call(exercise)


def test_real_sql_abort_precedes_postwrite_stop_guard(client):
    """A TEMP TRIGGER sets Stop then ABORTs; SQL uncertainty stays authoritative."""
    runtime, body, _ = staging.bootstrap(client)
    old = seed_expirable(client, runtime, body)
    before = durable_image(runtime)
    fired = []

    def install():
        def stop():
            fired.append(True)
            runtime.stop_signal.set()
            return 1

        runtime.storage.db.create_function("stop_grant", 0, stop)
        runtime.storage.db.execute(
            "CREATE TEMP TRIGGER stop_abort BEFORE INSERT ON tool_grants "
            "WHEN json_extract(NEW.data, '$.schema_version')=4 "
            "BEGIN SELECT stop_grant(); SELECT RAISE(ABORT, 'owned SQL fault'); END"
        )

    client.portal.call(install)
    with pytest.raises(DraftError, match="CHAT_COMMIT_UNCERTAIN"):
        staging.issue(client, runtime, body)
    assert fired == [True] and runtime.storage.fenced
    assert durable_image(runtime) == before

    def inspect():
        assert not runtime.storage.db.in_transaction
        retained = runtime.storage.db.execute("SELECT data FROM tool_grants").fetchall()
        assert [json.loads(row[0]) for row in retained] == [old]
        assert runtime.storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)

    client.portal.call(inspect)
    assert runtime.grant_deadlines == {} and not runtime.preparing
    assert not runtime.worker.busy and runtime.active is None and runtime.task is None


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_replay_ignores_guard_and_direct_no_deadline_still_works(client, version):
    runtime, body, _ = staging.bootstrap(client)
    if version == 4:
        grant, status = staging.issue(client, runtime, body)
        assert status == 201
        value = body
    else:
        value = GrantRequest.model_validate(legacy_body(body, version))
        grant, replay = client.portal.call(runtime.ledger.create_grant, value)
        assert not replay

    def forbidden():
        raise AssertionError("historical replay called new-publication guard")

    def exercise():
        before = durable_image(runtime)
        assert runtime.ledger.create_grant(value, publication_guard=forbidden) == (grant, True)
        assert durable_image(runtime) == before
        revoked = runtime.ledger.revoke(grant["id"])
        assert runtime.ledger.create_grant(value, publication_guard=forbidden) == (revoked, True)
        if version == 4:
            resolved = {key: grant[key] for key in ("resolved_inputs", "inputs_digest")}
            new, replay = runtime.ledger.create_grant(
                body | {"request_id": str(uuid4())},
                resolved=resolved,
            )
            assert not replay and new["status"] == "pending"
        runtime.storage.validate()
        assert not runtime.storage.db.in_transaction

    client.portal.call(exercise)
