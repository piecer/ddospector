"""Private controls validate actual copied-model data before any effects."""

import asyncio
from uuid import uuid4

import pytest
from test_chat_scenario_proposal_runtime import setup_path, waiting
from test_chat_scenario_save_recovery import client as client
from test_chat_scenario_save_runtime import approval, final_bytes

from aiddos.api.chat_scenario_models import ReconcileInputV4


@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize("extra", [{"schema_version": 3}, {"unrecognized_control": "must reject"}])
def test_private_decision_rejects_actual_model_copy_fields(client, monkeypatch, decision, extra):
    runtime, grant, value, transport, _ = setup_path(
        client, monkeypatch, "scenario_create", False
    )
    transport.frames.append(final_bytes())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            invalid = approval(call).model_copy(update={"decision": decision, **extra})
            before = list(runtime.storage.db.iterdump())
            registry = runtime.scenarios.path.read_bytes()
            requests = len(transport.requests)
            with pytest.raises(ValueError):
                await runtime._decide_scenario_tool(call["id"], invalid)
            assert list(runtime.storage.db.iterdump()) == before
            assert runtime.scenarios.path.read_bytes() == registry
            assert len(transport.requests) == requests
            assert runtime.ledger.call(call["id"])["status"] == "awaiting_approval"
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


async def uncertain(runtime, grant, value):
    turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
    call = (await waiting(runtime, turn["id"]))["calls"][-1]
    await runtime._decide_scenario_tool(call["id"], approval(call))
    await runtime.cancel(turn["id"])
    await runtime.task
    assert runtime.ledger.call(call["id"])["status"] == "uncertain"
    return ReconcileInputV4(
        schema_version=4,
        request_id=str(uuid4()),
        expected_generation=runtime.ledger.fence()["generation"],
        expected_draft_revision=runtime.draft._read().audit_total,
        expected_scenario_revision=runtime.scenarios.page()["revision"],
        acknowledge_uncertain=True,
    )


@pytest.mark.parametrize("extra", [{"unrecognized_control": "must reject"}, {"schema_version": 3}])
def test_private_reconciliation_rejects_actual_model_copy_fields(client, monkeypatch, extra):
    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append", False)

    async def exercise():
        body = await uncertain(runtime, grant, value)
        invalid = body.model_copy(update=extra)
        before = list(runtime.storage.db.iterdump())
        registry = runtime.scenarios.path.read_bytes()

        async def forbidden(*args):
            pytest.fail("invalid reconciliation acquired native revisions")

        with monkeypatch.context() as scoped:
            scoped.setattr(runtime.worker, "locked_scenario_revisions", forbidden)
            with pytest.raises(ValueError):
                await runtime._reconcile_scenario_tools(invalid)
        assert list(runtime.storage.db.iterdump()) == before
        assert runtime.scenarios.path.read_bytes() == registry
        assert runtime.ledger.fence()["fenced"]
        receipt, status = await runtime._reconcile_scenario_tools(body)
        assert status == 201 and receipt["scenario_recovery"] == "not_performed"
        assert await runtime._reconcile_scenario_tools(body) == (receipt, 200)

    client.portal.call(exercise)


def test_private_decision_detaches_caller_before_lock_wait(client, monkeypatch):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create", False)
    transport.frames.append(final_bytes())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        body = approval(call)
        original = body.model_dump()
        async with runtime.lock:
            task = asyncio.create_task(runtime._decide_scenario_tool(call["id"], body))
            await asyncio.sleep(0)
            body.__dict__["request_id"] = str(uuid4())
            body.__dict__["decision"] = "deny"
        receipt, status = await task
        await runtime.task
        assert status == 201
        assert receipt["request_id"] == original["request_id"]
        assert receipt["decision"] == original["decision"] == "approve"
        assert runtime.ledger.call(call["id"])["status"] == "succeeded"
        assert await runtime._decide_scenario_tool(call["id"], approval(call).model_copy(
            update=original
        )) == (receipt, 200)

    client.portal.call(exercise)
