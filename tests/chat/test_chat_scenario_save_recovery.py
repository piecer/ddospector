"""Private scenario intent crash recovery and revision-bound acknowledgement."""

import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_scenario_proposal_runtime import setup_path, waiting
from test_chat_scenario_save_runtime import approval

from aiddos.api.app import create_app
from aiddos.api.chat_scenario_models import ReconcileInputV4
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import ReconcileInput
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(state_path=tmp_path / "drafts.json"),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as connection:
        yield connection


def test_executing_restart_is_uncertain_without_replay(client, monkeypatch, tmp_path):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create", False)
    before = runtime.scenarios.path.read_bytes()
    cold = ChatStorage(tmp_path / "crash.json")

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            await runtime._decide_scenario_tool(call["id"], approval(call))
            # Snapshot the real durable intent before returning control to its producer.
            with sqlite3.connect(cold.path) as backup:
                runtime.storage.db.backup(backup)
            cold.path.chmod(0o600)
            assert cold.open()
            ledger = ToolLedger(cold)
            recovered = ledger.call(call["id"])
            assert recovered["status"] == "uncertain"
            assert recovered["error_code"] == "CHAT_TOOL_UNCERTAIN"
            assert ledger.fence()["call_ids"] == [call["id"]]
            assert json.loads(ledger.exchanges(turn["id"])[-1]["content"]) == dict(
                ok=False, result=None, error_code="CHAT_TOOL_UNCERTAIN"
            )
            assert ledger.reservation(turn["id"])["retired"]
            assert ledger.reservation(turn["id"])["remaining"] > 0
            assert cold.turn(turn["id"])["status"] == "interrupted"
            cold.validate()
            cold.close()
            assert cold.open()
            assert ToolLedger(cold).call(call["id"]) == recovered
            cold.validate()
            assert len(transport.requests) == 2
        finally:
            cold.close()
            await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
    assert runtime.scenarios.path.read_bytes() == before


def test_private_reconcile_checks_both_revisions_and_replays_historically(client, monkeypatch):
    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append", False)
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        await runtime._decide_scenario_tool(call["id"], approval(call))
        # Cancellation at the durable intent boundary must not invent nonpublication.
        await runtime.cancel(turn["id"])
        await runtime.task
        assert runtime.ledger.call(call["id"])["status"] == "uncertain"
        fence = runtime.ledger.fence()
        draft_revision = runtime.draft._read().audit_total
        scenario_revision = runtime.scenarios.page()["revision"]
        legacy = ReconcileInput(
            request_id=str(uuid4()),
            expected_generation=fence["generation"],
            expected_draft_revision=draft_revision,
            acknowledge_uncertain=True,
        )
        with pytest.raises(DraftError, match="CHAT_TOOL_CONFLICT"):
            await runtime.reconcile_tools(legacy)
        body = ReconcileInputV4(
            schema_version=4,
            request_id=str(uuid4()),
            expected_generation=fence["generation"],
            expected_draft_revision=draft_revision,
            expected_scenario_revision=scenario_revision,
            acknowledge_uncertain=True,
        )
        image = list(runtime.storage.db.iterdump())
        for field in (
            "expected_generation",
            "expected_draft_revision",
            "expected_scenario_revision",
        ):
            with pytest.raises(DraftError, match="CHAT_TOOL_CONFLICT"):
                await runtime._reconcile_scenario_tools(
                    body.model_copy(update={field: getattr(body, field) + 1})
                )
            assert list(runtime.storage.db.iterdump()) == image
        receipt, status = await runtime._reconcile_scenario_tools(body)
        assert status == 201
        assert receipt == dict(
            schema_version=4,
            request_id=body.request_id,
            acknowledged_call_ids=[call["id"]],
            generation=fence["generation"] + 1,
            write_fenced=False,
            prior_outcomes="remain_uncertain",
            observed_scenario_revision=scenario_revision,
            scenario_recovery="not_performed",
        )
        assert not runtime.ledger.fence()["fenced"]
        assert runtime.ledger.call(call["id"])["status"] == "uncertain"
        runtime.storage.validate()
        runtime.storage.close()
        assert runtime.storage.open()
        image = list(runtime.storage.db.iterdump())

        async def no_inspection(*args):
            pytest.fail("historical replay inspected current domain")

        monkeypatch.setattr(runtime.worker, "locked_scenario_revisions", no_inspection)
        runtime.preparing = True
        try:
            assert await runtime._reconcile_scenario_tools(body) == (receipt, 200)
        finally:
            runtime.preparing = False
        assert list(runtime.storage.db.iterdump()) == image
        runtime.storage.validate()

    client.portal.call(exercise)
    assert runtime.scenarios.path.read_bytes() == before


def test_reconcile_never_recovers_registry_and_holds_both_locks(client, monkeypatch):
    from test_scenario_retention import IOFault

    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append", False)
    observed = []

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        with monkeypatch.context() as scope:
            fault = IOFault(scope, runtime.scenarios.path, "parent-published", "fsync")
            await runtime._decide_scenario_tool(call["id"], approval(call))
            await runtime.task
        assert fault.fired == [("parent-published", "fsync")]
        body = ReconcileInputV4(
            schema_version=4,
            request_id=str(uuid4()),
            expected_generation=runtime.ledger.fence()["generation"],
            expected_draft_revision=runtime.draft._read().audit_total,
            expected_scenario_revision=runtime.scenarios.page()["revision"],
            acknowledge_uncertain=True,
        )
        retained = {
            p: p.read_bytes()
            for p in [
                runtime.scenarios.path,
                runtime.scenarios.receipt_path,
                *runtime.scenarios.pending_path.iterdir(),
            ]
        }
        real_put = runtime.ledger._put

        def put(table, *args):
            if table == "tool_reconciliations":
                observed.append(True)
                assert runtime.preparing and runtime.worker.busy and runtime.active is None
                for lock in (runtime.scenarios.lock, runtime.draft.lock):
                    acquired = lock.acquire(False)
                    if acquired:
                        lock.release()
                    assert not acquired, "reconciliation lost native domain lock"
            return real_put(table, *args)

        monkeypatch.setattr(runtime.ledger, "_put", put)
        receipt, status = await runtime._reconcile_scenario_tools(body)
        assert status == 201 and receipt["scenario_recovery"] == "not_performed"
        assert runtime.scenarios.coordinator.blocked
        assert not runtime.ledger.fence()["fenced"]
        assert runtime.ledger.call(call["id"])["status"] == "uncertain"
        assert all(p.read_bytes() == raw for p, raw in retained.items())
        for operation in ("prepare", "save"):
            with pytest.raises(DraftError, match="CHAT_SCENARIO_WRITE_FENCED"):
                if operation == "prepare":
                    await runtime.worker.prepare_scenario(
                        grant, call["arguments"], grant["settings_revision"]
                    )
                else:
                    await runtime.worker.save_scenario(
                        grant,
                        call["arguments"],
                        call["proposal"],
                        lambda: None,
                        grant["settings_revision"],
                    )
        assert all(p.read_bytes() == raw for p, raw in retained.items())
        runtime.storage.validate()

    client.portal.call(exercise)
    assert observed == [True]


@pytest.mark.parametrize(
    "damage", ["missing_decision", "foreign_decision", "proposal", "receipt", "encoding"]
)
def test_private_approved_graph_still_rejects_unlinked_tamper(client, monkeypatch, damage):
    from test_chat_scenario_save_runtime import final_bytes

    from aiddos.api.chat_models import encoded

    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create", False)
    transport.frames.append(final_bytes())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        decision = approval(call)
        await runtime._decide_scenario_tool(call["id"], decision)
        await runtime.task
        runtime.storage.validate()
        runtime.storage.close()
        with sqlite3.connect(runtime.storage.path) as db:
            if damage == "missing_decision":
                db.execute("DELETE FROM tool_decisions WHERE key=?", (decision.request_id,))
            else:
                table, key = (
                    ("tool_grants", grant["id"])
                    if damage == "encoding"
                    else ("tool_decisions", decision.request_id)
                    if damage == "foreign_decision"
                    else ("tool_calls", call["id"])
                )
                row = json.loads(
                    db.execute(f"SELECT data FROM {table} WHERE key=?", (key,)).fetchone()[0]
                )
                if damage == "encoding":
                    row = row["grant"]
                elif damage == "foreign_decision":
                    row["receipt"]["call_id"] = str(uuid4())
                elif damage == "proposal":
                    row["call"]["proposal"]["after"]["name"] = "Foreign proposal"
                else:
                    row["call"]["result"]["scenario"]["definition"]["name"] = "Foreign saved fact"
                db.execute(f"UPDATE {table} SET data=? WHERE key=?", (encoded(row).decode(), key))
        cold = ChatStorage(runtime.draft.path)
        try:
            with pytest.raises(DraftError, match="CHAT_STORAGE_ERROR"):
                cold.open()
        finally:
            cold.close()

    client.portal.call(exercise)
