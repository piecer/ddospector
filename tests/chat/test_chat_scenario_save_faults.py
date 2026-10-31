"""Real publication failures; known facts differ from uncertain intent."""

import asyncio
import json
import sqlite3
import threading

import pytest
from test_chat_scenario_proposal_runtime import setup_path, waiting
from test_chat_scenario_save_recovery import client as client
from test_chat_scenario_save_runtime import approval, audit_saved, final_bytes
from test_scenario_retention import SAVE_FAULTS, IOFault

from aiddos.api.errors import DraftError


@pytest.mark.parametrize(
    "fault", ["exchange_limit", "exchange_sql", "final_length", "stop_after_ack"]
)
def test_saved_fact_survives_downstream_failure(client, monkeypatch, fault):
    runtime, grant, value, transport, raw = setup_path(
        client, monkeypatch, "scenario_create", False
    )
    transport.frames.append(final_bytes("length" if fault == "final_length" else "stop"))
    saved, fired = [], []
    real_save = runtime.scenarios.save_receipt
    real_settle = runtime.ledger._settle_message

    def save(*args, **kwargs):
        result = real_save(*args, **kwargs)
        saved.append(result)
        if fault == "stop_after_ack":
            runtime.stop_signal.set()
            fired.append(True)
        return result

    def settle(turn_id, call):
        if call["tool"] == "scenario_create" and call["status"] == "succeeded":
            if fault == "exchange_limit":
                fired.append(True)
                raise DraftError("CHAT_TOOL_LIMIT")
            if fault == "exchange_sql":
                runtime.storage.db.execute(
                    "CREATE TEMP TRIGGER exchange_fault BEFORE UPDATE ON tool_exchanges "
                    "BEGIN SELECT RAISE(ABORT, 'exchange refused'); END"
                )
                fired.append(True)
        return real_settle(turn_id, call)

    monkeypatch.setattr(runtime.scenarios, "save_receipt", save)
    monkeypatch.setattr(runtime.ledger, "_settle_message", settle)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        await runtime._decide_scenario_tool(call["id"], approval(call))
        await runtime.task
        assert len(saved) == 1
        with sqlite3.connect(f"file:{runtime.storage.path}?mode=ro", uri=True) as observer:
            retained = json.loads(
                observer.execute(
                    "SELECT data FROM tool_calls WHERE key=?", (call["id"],)
                ).fetchone()[0]
            )["call"]
        assert retained["status"] == "succeeded"
        assert retained["result"] == saved[0]
        assert (
            saved[0]["scenario"]
            in runtime.scenarios.history(saved[0]["scenario"]["id"])["versions"]
        )
        assert not runtime.worker.busy and runtime.active is None
        if fault == "exchange_sql":
            assert runtime.storage.fenced
        else:
            assert runtime.storage.turn(turn["id"])["status"] != "succeeded"
        runtime.storage.close()
        monkeypatch.setattr(runtime.ledger, "_settle_message", real_settle)
        # A new owner, not clearing a live storage fence.
        from aiddos.api.chat_storage import ChatStorage
        from aiddos.api.chat_tool_storage import ToolLedger

        cold = ChatStorage(runtime.draft.path)
        try:
            assert cold.open()
            ledger = ToolLedger(cold)
            assert ledger.call(call["id"]) == retained
            cold.validate()
        finally:
            cold.close()
        assert len(saved) == 1

    client.portal.call(exercise)
    assert fired == ([] if fault == "final_length" else [True])


@pytest.mark.parametrize("phase", ["last_guard", "after_ack"])
@pytest.mark.parametrize("loss", ["stop", "cancel", "deadline"])
def test_native_save_drains_and_retains_actual_outcome(client, monkeypatch, phase, loss):
    from aiddos.api import chat_tool_runtime, scenario_persistence

    runtime, grant, value, transport, raw = setup_path(
        client, monkeypatch, "scenario_create", False
    )
    transport.frames.append(final_bytes())
    entered, release = threading.Event(), threading.Event()
    fired = []
    before = runtime.scenarios.path.read_bytes()
    real_save = runtime.scenarios.save_receipt
    real_candidate = scenario_persistence.write_candidate

    def pause():
        fired.append(True)
        entered.set()
        assert release.wait(4)

    def candidate(*args):
        result = real_candidate(*args)
        if phase == "last_guard":
            pause()
        return result

    def save(*args):
        result = real_save(*args)
        if phase == "after_ack":
            pause()
        return result

    monkeypatch.setattr(scenario_persistence, "write_candidate", candidate)
    monkeypatch.setattr(runtime.scenarios, "save_receipt", save)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            await runtime._decide_scenario_tool(call["id"], approval(call))
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            assert runtime.worker.busy and runtime.active == turn["id"]
            if loss == "cancel":
                await runtime.cancel(turn["id"])
            elif loss == "stop":
                runtime.stop_signal.set()
            else:
                clock = chat_tool_runtime.monotonic
                monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: clock() + 121)
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                runtime.check_idle()
            assert not runtime.task.done()
            release.set()
            await runtime.task
            if phase == "after_ack":
                audit_saved(runtime, turn, grant, raw)
                assert runtime.scenarios.page()["revision"] == 3
            else:
                result = runtime.ledger.call(call["id"])
                assert result["status"] in {"cancelled", "failed"}
                assert result["result"] is None
                assert runtime.scenarios.path.read_bytes() == before
                assert runtime.scenarios.coordinator.blocked
            assert not runtime.worker.busy and runtime.active is None
            assert runtime.ledger.reservation(turn["id"])["retired"]
            runtime.storage.validate()
        finally:
            release.set()
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
    assert fired == [True]


@pytest.mark.parametrize(
    "failure", ["receipt_abort", "commit_refused", "commit_then_raise", "readback"]
)
def test_cross_store_uncertainty_uses_independent_sql_before_cleanup(client, monkeypatch, failure):
    from aiddos.api import scenario_persistence as persistence
    from aiddos.api.chat_storage import ChatStorage
    from aiddos.api.chat_tool_storage import ToolLedger

    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_create", False)
    observed, fired, published = [], [], []
    real_frame, real_read = persistence.write_frame, persistence.read_registry
    real_db = runtime.storage.db
    target = []

    def inspect():
        with sqlite3.connect(f"file:{runtime.storage.path}?mode=ro", uri=True) as db:
            observed.append(
                json.loads(
                    db.execute("SELECT data FROM tool_calls WHERE key=?", (target[0],)).fetchone()[
                        0
                    ]
                )["call"]
            )

    class Connection:
        def __getattr__(self, name):
            return getattr(real_db, name)

        def commit(self):
            row = real_db.execute(
                "SELECT data FROM tool_calls WHERE key=?", (target[0],)
            ).fetchone()
            hit = row and json.loads(row[0])["call"]["status"] == "succeeded" and not fired
            if hit and failure in {"commit_refused", "commit_then_raise"}:
                fired.append(True)
                if failure == "commit_then_raise":
                    real_db.commit()
                raise sqlite3.OperationalError("receipt commit acknowledgement lost")
            return real_db.commit()

        def rollback(self):
            inspect()  # Observe independently before rollback erases transaction evidence.
            return real_db.rollback()

    def frame(path, data, **kwargs):
        result = real_frame(path, data, **kwargs)
        if persistence.decode_frame(data)["phase"] == "PUBLISHED":
            published.append(True)
        return result

    def read(path):
        if published and failure == "readback" and not fired:
            fired.append(True)
            raise OSError("immutable readback unavailable")
        return real_read(path)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        target.append(call["id"])
        await runtime._decide_scenario_tool(call["id"], approval(call))
        if failure == "receipt_abort":
            real_db.create_function("receipt_fault_fired", 0, lambda: fired.append(True) or 0)
            real_db.execute(
                "CREATE TEMP TRIGGER receipt_fault BEFORE UPDATE ON tool_calls "
                "WHEN json_extract(new.data, '$.call.status')='succeeded' "
                "BEGIN SELECT receipt_fault_fired(); "
                "SELECT RAISE(ABORT, 'receipt refused'); END"
            )
        runtime.storage.db = Connection()
        monkeypatch.setattr(persistence, "write_frame", frame)
        monkeypatch.setattr(persistence, "read_registry", read)
        await runtime.task
        inspect()
        assert fired == [True]
        expected = (
            "succeeded"
            if failure == "commit_then_raise"
            else "uncertain"
            if failure == "readback"
            else "executing"
        )
        assert all(c["status"] == expected for c in observed)
        assert runtime.scenarios.page()["revision"] == 3
        assert not runtime.worker.busy
        runtime.storage.close()
        cold = ChatStorage(runtime.draft.path)
        try:
            assert cold.open()
            ledger = ToolLedger(cold)
            result = ledger.call(call["id"])
            assert result["status"] == (
                "succeeded" if failure == "commit_then_raise" else "uncertain"
            )
            assert ledger.fence()["fenced"] is (failure != "commit_then_raise")
            if result["status"] == "succeeded":
                assert (
                    result["result"]["scenario"]
                    in runtime.scenarios.history(result["result"]["scenario"]["id"])["versions"]
                )
            cold.validate()
        finally:
            cold.close()

    client.portal.call(exercise)


@pytest.mark.parametrize("role,operation", SAVE_FAULTS)
def test_native_registry_fault_truth_and_restart(client, monkeypatch, role, operation):
    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append", False)
    before = runtime.scenarios.path.read_bytes()
    uncertain = (
        role in {"PUBLISHED", "CLEAN", "slot-published", "parent-published", "slot-retired"}
        or operation == "retire"
    )

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        with monkeypatch.context() as scope:
            fault = IOFault(scope, runtime.scenarios.path, role, operation)
            await runtime._decide_scenario_tool(call["id"], approval(call))
            await runtime.task
        assert fault.fired == [(role, operation)]
        result = runtime.ledger.call(call["id"])
        assert result["status"] == ("uncertain" if uncertain else "failed")
        assert result["error_code"] == (
            "CHAT_TOOL_UNCERTAIN" if uncertain else "CHAT_STORAGE_ERROR"
        )
        assert runtime.ledger.fence()["fenced"] is uncertain
        assert runtime.scenarios.coordinator.blocked
        assert (runtime.scenarios.path.read_bytes() != before) is uncertain
        retained = {
            p: p.read_bytes()
            for p in [
                runtime.scenarios.path,
                runtime.scenarios.receipt_path,
                *runtime.scenarios.pending_path.iterdir(),
            ]
        }
        assert (await runtime.worker.scenario_state())["registry_write_status"] == "quarantined"
        assert runtime.ledger.fence()["fenced"] is uncertain
        assert all(p.read_bytes() == data for p, data in retained.items())
        runtime.storage.validate()
        runtime.storage.close()
        assert runtime.storage.open()
        assert runtime.ledger.call(call["id"]) == result
        assert runtime.ledger.fence()["fenced"] is uncertain
        runtime.storage.validate()

    client.portal.call(exercise)
