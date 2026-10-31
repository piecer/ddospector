"""Actual native scenario saves through separate private operator approval."""

import asyncio
import json
import os
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from test_chat_scenario_proposal_runtime import setup_path, waiting

from aiddos.api.chat_models import encoded
from aiddos.api.chat_scenario_models import protected_projection, validate_call_binding
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import DecisionInput
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput, record_digest


def final_bytes(reason="stop", streaming=False):
    if streaming:
        return (
            b"data: "
            + encoded(
                dict(
                    choices=[
                        dict(index=0, delta=dict(content="Saved definition."), finish_reason=reason)
                    ]
                )
            )
            + b"\n\ndata: [DONE]\n\n"
        )
    return encoded(
        dict(
            choices=[
                dict(
                    index=0,
                    message=dict(role="assistant", content="Saved definition."),
                    finish_reason=reason,
                )
            ]
        )
    )


def capture_transport(transport):
    root = os.environ.get("STAGE3_CORPUS")
    if not root:
        return
    out = Path(root) / ("wire-" + uuid4().hex)
    out.mkdir(parents=True)
    send = transport.handle_async_request
    frames = []

    async def capture(request):
        response = await send(request)
        index = len(frames)
        frames.append(True)
        (out / f"request-{index}.bin").write_bytes(request.content)
        (out / f"response-{index}.bin").write_bytes(response.stream.data)
        return response

    transport.handle_async_request = capture


def approval(call):
    return DecisionInput(
        request_id=str(uuid4()), proposal_digest=call["proposal"]["digest"], decision="approve"
    )


def audit_saved(runtime, turn, grant, raw):
    transcript = runtime.ledger.transcript(turn["id"])
    call = transcript["calls"][-1]
    assert call["status"] == "succeeded", call
    receipt = call["result"]
    record = receipt["scenario"]
    assert record["definition"] == call["proposal"]["after"]
    assert protected_projection(record["definition"]) == grant["resolved_inputs"]
    assert record["digest"] == record_digest(record)
    assert all(record[k] == v for k, v in call["proposal"]["snapshots"].items())
    assert record in runtime.scenarios.history(record["id"])["versions"]
    registry = json.loads(runtime.scenarios.path.read_bytes())
    assert record in next(s["versions"] for s in registry["scenarios"] if s["id"] == record["id"])
    assert receipt["before_scenario_revision"] == call["proposal"]["expected_scenario_revision"]
    assert receipt["after_scenario_revision"] == receipt["before_scenario_revision"] + 1
    assert receipt["source_draft_revision"] == call["proposal"]["expected_draft_revision"]
    assert (
        validate_call_binding(
            call, grant, deadline_at=runtime.ledger.binding(turn["id"])["deadline_at"]
        )
        == call
    )
    exchanges = runtime.ledger.exchanges(turn["id"])
    assert exchanges[2]["tool_calls"][0]["function"]["arguments"] == raw
    assert json.loads(exchanges[3]["content"]) == dict(ok=True, result=receipt, error_code=None)
    with sqlite3.connect(f"file:{runtime.storage.path}?mode=ro", uri=True) as observer:
        observed = json.loads(
            observer.execute("SELECT data FROM tool_calls WHERE key=?", (call["id"],)).fetchone()[0]
        )
        assert observed == dict(turn_id=turn["id"], call=call)
        decision = json.loads(
            observer.execute(
                "SELECT data FROM tool_decisions WHERE key=?", (call["decision"]["request_id"],)
            ).fetchone()[0]
        )
        assert decision["receipt"] == call["decision"]
    runtime.storage.validate()
    root = os.environ.get("STAGE3_CORPUS")
    if root:
        out = Path(root) / call["tool"] / call["id"]
        out.mkdir(parents=True, exist_ok=True)
        for name, obj in dict(
            grant=grant,
            call=call,
            receipt=receipt,
            transcript=transcript,
            exchanges=exchanges,
            registry=registry,
        ).items():
            (out / (name + ".json")).write_bytes(encoded(obj) + b"\n")
    return call


@pytest.mark.parametrize("streaming", [False, True])
def test_private_create_saves_exact_history_and_cold_receipt(client, monkeypatch, streaming):
    runtime, grant, value, transport, raw = setup_path(
        client, monkeypatch, "scenario_create", streaming
    )
    transport.frames.append(final_bytes(streaming=streaming))
    capture_transport(transport)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            decision = approval(call)
            receipt, status = await runtime._decide_scenario_tool(call["id"], decision)
            assert status == 201 and receipt["proposal_digest"] == call["proposal"]["digest"]
            await runtime.task
            assert runtime.storage.turn(turn["id"])["status"] == "succeeded"
            saved = audit_saved(runtime, turn, grant, raw)
            assert len(transport.requests) == 3 and "tools" not in transport.requests[-1]
            assert not runtime.worker.busy and runtime.active is None
            assert runtime.ledger.reservation(turn["id"])["retired"]
            runtime.storage.close()
            cold = ChatStorage(runtime.draft.path)
            assert cold.open()
            try:
                assert ToolLedger(cold).transcript(turn["id"])["calls"][-1] == saved
                cold.validate()
            finally:
                cold.close()
            from aiddos.api.chat_runtime import ChatRuntime

            await runtime.worker.shutdown()
            reopened = ChatRuntime(runtime.draft, runtime.scenarios)
            try:
                assert reopened.storage.open()
                assert reopened.storage.turn(turn["id"])["status"] == "succeeded"
                assert reopened.ledger.transcript(turn["id"])["calls"][-1] == saved
                assert await reopened._decide_scenario_tool(call["id"], decision) == (receipt, 200)
                assert reopened.task is None and not reopened.worker.busy
                assert not reopened.decision_ready.is_set()
                runtime.draft.path.rename(runtime.draft.path.with_name("source-removed.json"))
                assert (
                    saved["result"]["scenario"]
                    in runtime.scenarios.history(saved["result"]["scenario"]["id"])["versions"]
                )
                reopened.storage.validate()
            finally:
                await reopened.close()
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


def test_private_append_replays_before_authority_and_survives_supersession(client, monkeypatch):
    runtime, grant, value, transport, raw = setup_path(
        client, monkeypatch, "scenario_append", False
    )
    transport.frames.append(final_bytes())
    capture_transport(transport)
    real = runtime.scenarios.save_receipt
    writes = []

    def supersede(*args, **kwargs):
        saved = real(*args, **kwargs)
        writes.append(saved)
        record = saved["scenario"]
        runtime.scenarios.save(
            ScenarioInput(
                revision=saved["after_scenario_revision"],
                definition=record["definition"] | {"name": "Later manual version"},
            ),
            record["id"],
        )
        return saved

    monkeypatch.setattr(runtime.scenarios, "save_receipt", supersede)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            decision = approval(call)
            receipt, status = await runtime._decide_scenario_tool(call["id"], decision)
            assert status == 201
            assert await runtime._decide_scenario_tool(call["id"], decision) == (receipt, 200)
            with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                await runtime._decide_scenario_tool(call["id"], approval(call))
            await runtime.task
            saved = audit_saved(runtime, turn, grant, raw)
            record = saved["result"]["scenario"]
            history = runtime.scenarios.history(record["id"])["versions"]
            assert history == [call["proposal"]["before"], record, history[2]]
            assert history[2]["definition"]["name"] == "Later manual version"
            assert saved["proposal"]["input_source"]["reference"]["id"] != record["id"]
            runtime.tool_deadline = runtime.tool_grant_deadline = 0
            runtime.stop_signal.set()
            runtime.ledger.revoke(grant["id"])
            before = list(runtime.storage.db.iterdump())
            runtime.decision_ready.clear()
            assert await runtime._decide_scenario_tool(call["id"], decision) == (receipt, 200)
            assert not runtime.decision_ready.is_set()
            assert list(runtime.storage.db.iterdump()) == before
            assert len(writes) == 1
            runtime.storage.close()
            assert runtime.storage.open()
            assert runtime.ledger.transcript(turn["id"])["calls"][-1] == saved
            assert await runtime._decide_scenario_tool(call["id"], decision) == (receipt, 200)
            assert not runtime.worker.busy
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


@pytest.mark.parametrize("phase", ["before", "projection", "decision_put"])
@pytest.mark.parametrize("loss", ["stop", "clock"])
def test_private_approval_original_authority_cannot_be_renewed(client, monkeypatch, phase, loss):
    from aiddos.api import chat_tool_runtime

    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_create", False)
    before = runtime.scenarios.path.read_bytes()
    fired = []

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            stop = runtime.stop_signal

            def expire():
                if fired:
                    return
                fired.append(True)
                if loss == "stop":
                    stop.set()
                    runtime.stop_signal = threading.Event()
                else:
                    clock = chat_tool_runtime.monotonic
                    monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: clock() + 121)
                    runtime.tool_deadline += 10000
                    runtime.tool_grant_deadline += 10000
                    runtime.grant_deadlines[grant["id"]] += 10000

            if phase == "before":
                expire()
            elif phase == "projection":
                real = runtime.ledger._projection

                def project(*args):
                    result = real(*args)
                    expire()
                    return result

                monkeypatch.setattr(runtime.ledger, "_projection", project)
            else:
                real = runtime.ledger._put

                def put(table, *args):
                    result = real(table, *args)
                    if table == "tool_decisions":
                        expire()
                    return result

                monkeypatch.setattr(runtime.ledger, "_put", put)
            image = list(runtime.storage.db.iterdump())
            with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                await runtime._decide_scenario_tool(call["id"], approval(call))
            assert list(runtime.storage.db.iterdump()) == image
        finally:
            await runtime.cancel(turn["id"])
            await runtime.task
        assert not runtime.worker.busy

    client.portal.call(exercise)
    assert fired == [True] and runtime.scenarios.path.read_bytes() == before


@pytest.mark.parametrize("change", ["append", "settings", "draft"])
def test_actual_revision_race_refuses_save(client, monkeypatch, change):
    from aiddos.api.models import AgentProfileInput, AISettingsInput

    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_append", False)
    transport.frames.append(final_bytes())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        if change == "append":
            runtime.scenarios.save(
                ScenarioInput(revision=2, definition=call["proposal"]["after"]),
                grant["intent"]["base"]["id"],
            )
        elif change == "settings":
            data = runtime.draft.ai_snapshot()
            runtime.draft.save_ai_settings(
                AISettingsInput(**{k: data[k] for k in AISettingsInput.model_fields})
            )
        else:
            data = runtime.draft.snapshot()["agent_profile"]
            runtime.draft.save_agent_profile(
                AgentProfileInput(
                    **{k: data[k] for k in AgentProfileInput.model_fields}
                    | {"name": data["name"] + " changed"}
                )
            )
        before = runtime.scenarios.path.read_bytes()
        await runtime._decide_scenario_tool(call["id"], approval(call))
        await runtime.task
        actual = runtime.ledger.call(call["id"])
        assert actual["status"] == "conflict" and actual["error_code"] == "CHAT_TOOL_CONFLICT"
        assert actual["result"] is None
        assert runtime.scenarios.path.read_bytes() == before
        assert not runtime.ledger.fence()["fenced"]
        runtime.storage.validate()

    client.portal.call(exercise)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_success_next_request_fits_original_projection_with_escaping(
    client, monkeypatch, operation
):
    from test_chat_scenario_proposal_runtime import native_bytes

    runtime, grant, value, transport, raw = setup_path(client, monkeypatch, operation, False)
    args = json.loads(raw)
    args["definition"]["name"] = 'Quote " slash \\ 한😀'
    raw = json.dumps(args, ensure_ascii=False)
    transport.frames[1] = native_bytes(operation, raw, "write-2", False)
    transport.frames.append(final_bytes())
    capture_transport(transport)
    check = ToolLedger.check_payload
    sizes = []

    def sized(payload):
        wire = check(payload)
        last = payload["messages"][-1]
        if last["role"] == "tool":
            envelope = json.loads(last["content"])
            if envelope["result"] and envelope["result"]["kind"] in {
                "scenario_created",
                "scenario_appended",
            }:
                sizes.append((last["tool_call_id"], len(wire)))
        return wire

    monkeypatch.setattr(ToolLedger, "check_payload", staticmethod(sized))

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        await runtime._decide_scenario_tool(call["id"], approval(call))
        await runtime.task
        audit_saved(runtime, turn, grant, raw)
        actual = [size for identifier, size in sizes if identifier == "write-2"]
        projected = [size for identifier, size in sizes if identifier == "\x00" * 128]
        assert actual and projected and max(actual) <= min(projected) <= 131072
        assert len(encoded(transport.requests[-1])) == actual[-1]
        assert "tools" not in transport.requests[-1]

    client.portal.call(exercise)


def test_concurrent_exact_decisions_have_one_winner_and_one_save(client, monkeypatch):
    runtime, grant, value, transport, raw = setup_path(
        client, monkeypatch, "scenario_create", False
    )
    transport.frames.append(final_bytes())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        requests = [approval(call), approval(call)]
        results = await asyncio.gather(
            *(runtime._decide_scenario_tool(call["id"], body) for body in requests),
            return_exceptions=True,
        )
        assert (
            sum(
                isinstance(r, DraftError) and r.code == "CHAT_TOOL_APPROVAL_CONFLICT"
                for r in results
            )
            == 1
        )
        assert sum(isinstance(r, tuple) and r[1] == 201 for r in results) == 1
        await runtime.task
        audit_saved(runtime, turn, grant, raw)
        assert runtime.scenarios.page()["revision"] == 3
        assert len(runtime.ledger._rows("tool_decisions")) == 1

    client.portal.call(exercise)


@pytest.mark.parametrize("damage", ["digest", "call", "revoke", "expired"])
def test_exact_approval_refuses_foreign_or_lost_authority(client, monkeypatch, damage):
    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_create", False)
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            body = approval(call)
            call_id = call["id"]
            if damage == "digest":
                body = body.model_copy(update={"proposal_digest": "0" * 64})
            elif damage == "call":
                call_id = runtime.ledger.transcript(turn["id"])["calls"][0]["id"]
            elif damage == "revoke":
                await runtime.revoke_grant(grant["id"])
            else:
                from datetime import timedelta

                from aiddos.api import chat_tool_storage
                from aiddos.api.chat_tool_models import instant

                monkeypatch.setattr(
                    chat_tool_storage,
                    "now",
                    lambda: (instant(grant["expires_at"]) + timedelta(seconds=1)).isoformat(),
                )
            with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                await runtime._decide_scenario_tool(call_id, body)
            assert not runtime.ledger._rows("tool_decisions")
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task
        assert runtime.scenarios.path.read_bytes() == before

    client.portal.call(exercise)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_reachable_last_slot_save_then_quota_refusal(client, monkeypatch, operation):
    from chat_scenario_support import reference
    from test_chat_scenario_proposal_runtime import native_bytes

    from aiddos.api.chat_scenario_models import GrantInputV4
    from aiddos.api.chat_tool_models import ToolTurnInput

    runtime, old_grant, old_value, transport, raw = setup_path(
        client, monkeypatch, operation, False
    )
    definition = runtime.scenarios.page()["items"][0]["definition"]
    base = runtime.scenarios.page()["items"][1]
    count = 97 if operation == "scenario_create" else 8
    for _ in range(count):
        receipt = runtime.scenarios.save(
            ScenarioInput(revision=runtime.scenarios.page()["revision"], definition=definition),
            None if operation == "scenario_create" else base["id"],
        )
        base = receipt["scenario"]
    intent = old_grant["intent"] | {
        "expected_scenario_revision": runtime.scenarios.page()["revision"]
    }
    if operation == "scenario_append":
        intent["base"] = reference(base)
    request = {
        k: old_grant[k] for k in ("schema_version", "scope", "session_id", "expected_sequence")
    }
    request.update(
        request_id=str(uuid4()), turn_request_id=str(uuid4()), text=old_value.text, intent=intent
    )
    runtime_grant = []

    async def exercise():
        await runtime.revoke_grant(old_grant["id"])
        grant, _ = await runtime._create_scenario_grant(GrantInputV4(**request))
        runtime_grant.append(grant)
        args = json.loads(raw) | {
            "expected_scenario_revision": intent["expected_scenario_revision"]
        }
        if operation == "scenario_append":
            args["base"] = intent["base"]
        actual_raw = json.dumps(args, ensure_ascii=False)
        transport.frames[1] = native_bytes(operation, actual_raw, "write-2", False)
        transport.frames.append(final_bytes())
        capture_transport(transport)
        turn, _ = await runtime._accept_scenario_tool(
            grant["session_id"],
            ToolTurnInput(
                request_id=grant["turn_request_id"],
                expected_sequence=0,
                text=old_value.text,
                grant_id=grant["id"],
            ),
        )
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        await runtime._decide_scenario_tool(call["id"], approval(call))
        await runtime.task
        saved = audit_saved(runtime, turn, grant, actual_raw)
        if operation == "scenario_append":
            assert saved["result"]["scenario"]["version"] == 10
        else:
            assert runtime.scenarios.page()["total"] == 100
        next_intent = intent | {"expected_scenario_revision": runtime.scenarios.page()["revision"]}
        if operation == "scenario_append":
            next_intent["base"] = reference(saved["result"]["scenario"])
        next_request = request | dict(
            request_id=str(uuid4()),
            turn_request_id=str(uuid4()),
            expected_sequence=1,
            intent=next_intent,
        )
        before = runtime.scenarios.path.read_bytes()
        if operation == "scenario_append":
            # The closed intent itself excludes a full ten-version base.
            with pytest.raises(ValueError):
                GrantInputV4(**next_request)
            with pytest.raises(DraftError, match="CHAT_TOOL_LIMIT"):
                await runtime.worker.resolve_scenario_intent(
                    next_intent, grant["settings_revision"]
                )
        else:
            with pytest.raises(DraftError, match="CHAT_TOOL_LIMIT"):
                await runtime._create_scenario_grant(GrantInputV4(**next_request))
        assert runtime.scenarios.path.read_bytes() == before
        runtime.storage.validate()

    client.portal.call(exercise)
