"""Internal scenario native path, real owned stores and in-memory HTTP bytes."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
from chat_scenario_support import intent_for, reference
from scenario_producer import definition, register_targets
from test_chat_runtime import configure
from test_chat_scenario_grant_staging import issue
from test_chat_sessions import start

from aiddos.api import chat_tool_transport
from aiddos.api.chat_models import encoded
from aiddos.api.chat_scenario_models import TranscriptV4, bound_grant, model_projection, parse_value
from aiddos.api.chat_tool_models import DecisionInput, ToolTurnInput
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput


def native_bytes(name, raw, identifier, streaming):
    call = dict(id=identifier, type="function", function=dict(name=name, arguments=raw))
    if not streaming:
        return encoded(
            dict(
                choices=[
                    dict(
                        index=0,
                        message=dict(role="assistant", content="한😀", tool_calls=[call]),
                        finish_reason="tool_calls",
                    )
                ]
            )
        )
    delta = dict(role="assistant", content="한😀", tool_calls=[dict(index=0, **call)])
    return (
        b"data: "
        + encoded(dict(choices=[dict(index=0, delta=delta, finish_reason="tool_calls")]))
        + b"\n\ndata: [DONE]\n\n"
    )


class BytesStream(httpx2.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        for index in range(0, len(self.data), 37):
            yield self.data[index : index + 37]


class NativeBytesTransport(httpx2.AsyncBaseTransport):
    def __init__(self, frames, streaming):
        self.frames = list(frames)
        self.original_frames = tuple(frames)
        self.streaming = streaming
        self.requests = []
        self.closed = False

    async def handle_async_request(self, request):
        self.requests.append(json.loads(request.content))
        assert self.frames, "unexpected native round"
        return httpx2.Response(
            200,
            headers={
                "content-type": ("text/event-stream" if self.streaming else "application/json")
            },
            stream=BytesStream(self.frames.pop(0)),
        )

    async def aclose(self):
        self.closed = True


def setup_path(client, monkeypatch, operation, streaming=True):
    configure(client, streaming=streaming)
    definition_value = definition(register_targets(client))
    response, _ = start(client)
    assert response.status_code == 201
    runtime = client.app.state.chat
    body = dict(
        schema_version=4,
        scope="scenario_write",
        request_id=str(uuid4()),
        session_id=response.json()["id"],
        turn_request_id=str(uuid4()),
        expected_sequence=0,
        text="Prepare scenario 한😀",
        intent=intent_for(runtime.draft, runtime.scenarios, definition_value),
    )
    # Independent immutable source and append base, deliberately different inputs.
    source = runtime.scenarios.save(ScenarioInput(revision=0, definition=definition_value))[
        "scenario"
    ]
    base = runtime.scenarios.save(
        ScenarioInput(
            revision=1, definition=definition_value | {"policy_version": "base-not-source"}
        )
    )["scenario"]
    body["intent"] = intent_for(
        runtime.draft,
        runtime.scenarios,
        definition_value,
        base=reference(base) if operation == "scenario_append" else None,
        source=dict(source="scenario_version", reference=reference(source)),
    )
    grant, _ = issue(client, runtime, body)
    arguments = dict(
        expected_scenario_revision=2,
        expected_draft_revision=body["intent"]["expected_draft_revision"],
        definition=model_projection(definition_value) | {"name": "Native 한😀"},
    )
    if operation == "scenario_append":
        arguments["base"] = reference(base)
    raw = json.dumps(arguments, ensure_ascii=False, indent=1)
    frames = [
        native_bytes("configuration_read", '{ "kind" : "scenario_context" }', "read-1", streaming),
        native_bytes(operation, raw, "write-2", streaming),
    ]
    transport = NativeBytesTransport(frames, streaming)
    monkeypatch.setattr(chat_tool_transport.httpx2, "AsyncHTTPTransport", lambda **kw: transport)
    value = ToolTurnInput(
        request_id=body["turn_request_id"],
        expected_sequence=0,
        text=body["text"],
        grant_id=grant["id"],
    )
    return runtime, grant, value, transport, raw


async def waiting(runtime, turn_id):
    async with asyncio.timeout(4):
        while True:
            transcript = runtime.ledger.transcript(turn_id)
            if any(c["status"] == "awaiting_approval" for c in transcript["calls"]):
                return transcript
            assert runtime.active == turn_id, runtime.storage.turn(turn_id)
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
@pytest.mark.parametrize("streaming", [False, True])
def test_real_native_read_to_durable_approval_wait(client, monkeypatch, operation, streaming):
    runtime, grant, value, transport, raw = setup_path(client, monkeypatch, operation, streaming)
    before = runtime.scenarios.path.read_bytes()
    request = {
        key: grant[key]
        for key in (
            "schema_version",
            "scope",
            "request_id",
            "session_id",
            "turn_request_id",
            "expected_sequence",
            "intent",
        )
    } | {"text": value.text}
    assert (
        bound_grant(
            grant,
            request,
            settings_revision=grant["settings_revision"],
            profile_id=grant["profile_id"],
            resolved_inputs=grant["resolved_inputs"],
        )
        == grant
    )

    async def exercise():
        # A private entry on the existing runtime, not a parallel owner or ledger.
        turn, status = await runtime._accept_scenario_tool(grant["session_id"], value)
        assert status == 202
        try:
            transcript = await waiting(runtime, turn["id"])
            assert TranscriptV4.model_validate(transcript).model_dump() == transcript
            read, call = transcript["calls"]
            assert read["status"] == "succeeded"
            assert read["result"]["resolved_inputs"] == grant["resolved_inputs"]
            assert call["proposal"]["after"]["policy_version"] != "base-not-source"
            assert call["proposal"]["input_source"] == grant["intent"]["input_source"]
            assert (
                call["proposal"]["before"] is None
                if operation == "scenario_create"
                else reference(call["proposal"]["before"]) == grant["intent"]["base"]
            )
            stored = json.loads(
                runtime.storage.db.execute(
                    "SELECT data FROM tool_calls WHERE key=?", (call["id"],)
                ).fetchone()[0]
            )
            assert stored == dict(turn_id=turn["id"], call=call)
            exchanges = runtime.ledger.exchanges(turn["id"])
            assert exchanges[-1]["tool_calls"][0]["function"]["arguments"] == raw
            assert [x["function"]["name"] for x in transport.requests[0]["tools"]] == [
                "configuration_read",
                operation,
            ]
            assert len(transport.requests) == 2
            runtime.storage.validate()
            body = DecisionInput(
                request_id=str(uuid4()),
                proposal_digest=call["proposal"]["digest"],
                decision="approve",
            )
            image = list(runtime.storage.db.iterdump())
            with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                await runtime.decide_tool(call["id"], body)
            with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                runtime.ledger.decide(call["id"], body.model_dump(), active_turn_id=turn["id"])
            assert list(runtime.storage.db.iterdump()) == image
            root = os.environ.get("STAGE2_CORPUS")
            if root:
                out = Path(root) / f"{operation}-{streaming}"
                out.mkdir(parents=True, exist_ok=True)
                for name, data in {
                    "grant": grant,
                    "call": call,
                    "proposal": call["proposal"],
                    "transcript": transcript,
                    "read-result": read["result"],
                    "exchanges": exchanges,
                }.items():
                    (out / (name + ".json")).write_bytes(encoded(data) + b"\n")
                for index, frame in enumerate(transport.original_frames):
                    (out / f"native-{index}.bin").write_bytes(frame)
                (out / "requests.json").write_bytes(encoded(transport.requests) + b"\n")
                (out / "envelope.json").write_bytes(exchanges[1]["content"].encode() + b"\n")
                producer = encoded(transcript)
                counterexamples = {
                    "unknown": encoded(transcript | {"unknown": True}),
                    "float": producer.replace(b'"schema_version":4', b'"schema_version":4.0', 1),
                    "duplicate": producer.replace(
                        b'"schema_version":4', b'"schema_version":4,"schema_version":4', 1
                    ),
                }
                for name, invalid in counterexamples.items():
                    with pytest.raises(ValueError):
                        parse_value("TranscriptV4", invalid)
                    (out / f"invalid-{name}.json").write_bytes(invalid + b"\n")
        finally:
            await runtime.cancel(turn["id"])
            await runtime.task
        assert runtime.ledger.transcript(turn["id"])["calls"][-1]["status"] == "cancelled"
        assert runtime.ledger.reservation(turn["id"])["retired"]
        runtime.storage.validate()
        assert not runtime.worker.busy and transport.closed

    client.portal.call(exercise)
    assert runtime.scenarios.path.read_bytes() == before


@pytest.mark.parametrize("phase", ["admit", "proposal", "read_result", "decision"])
@pytest.mark.parametrize("loss", ["stop", "deadline"])
def test_original_authority_survives_final_sql_accounting(client, monkeypatch, phase, loss):
    from aiddos.api import chat_tool_runtime

    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create")
    put = runtime.ledger._put
    fired = []

    def delayed(table, key, record, *args):
        result = put(table, key, record, *args)
        hit = (
            phase == "admit"
            and table == "tool_exchanges"
            and record == []
            or phase == "proposal"
            and table == "tool_calls"
            and record["call"]["status"] == "awaiting_approval"
            or phase == "read_result"
            and table == "tool_calls"
            and record["call"]["status"] == "succeeded"
            or phase == "decision"
            and table == "tool_decisions"
        )
        if hit and not fired:
            fired.append(True)
            if loss == "stop":
                runtime.stop_signal.set()
            else:
                clock = chat_tool_runtime.monotonic
                monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: clock() + 121)
        return result

    monkeypatch.setattr(runtime.ledger, "_put", delayed)

    async def exercise():
        image = list(runtime.storage.db.iterdump())
        if phase == "admit":
            with pytest.raises(DraftError, match="CHAT_CANCELLED|CHAT_TIMEOUT"):
                await runtime._accept_scenario_tool(grant["session_id"], value)
            assert list(runtime.storage.db.iterdump()) == image
            assert runtime.active is None and not transport.requests
            return
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            if phase == "decision":
                transcript = await waiting(runtime, turn["id"])
                call = transcript["calls"][-1]
                image = list(runtime.storage.db.iterdump())
                with pytest.raises(DraftError, match="CHAT_TOOL_APPROVAL_CONFLICT"):
                    await runtime.decide_tool(
                        call["id"],
                        DecisionInput(
                            request_id=str(uuid4()),
                            proposal_digest=call["proposal"]["digest"],
                            decision="deny",
                        ),
                    )
                assert list(runtime.storage.db.iterdump()) == image
                await runtime.cancel(turn["id"])
            await runtime.task
            calls = runtime.ledger.transcript(turn["id"])["calls"]
            assert all(c["status"] != "awaiting_approval" for c in calls)
            assert calls[-1]["proposal"] is None if phase == "proposal" else True
            if phase == "read_result":
                assert calls[0]["result"] is None and len(calls) == 1
            assert not runtime.storage.db.in_transaction
            runtime.storage.validate()
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
    assert fired == [True]


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_complete_prospective_context_refused_before_wait(client, monkeypatch, operation):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, operation)
    real = runtime.context
    observed = []

    def full_context(*args):
        payload = real(*args)
        if runtime.active and len(runtime.ledger.transcript(runtime.active)["calls"]) == 2:
            # Keep an otherwise valid complete history just below the request cap.
            # The exact pending call plus escaped future receipt must not fit.
            payload["messages"].insert(1, dict(role="user", content="x" * 130000))
            observed.append(True)
        return payload

    monkeypatch.setattr(runtime, "context", full_context)
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        await runtime.task
        assert runtime.storage.turn(turn["id"])["error_code"] == "CHAT_TOOL_LIMIT"
        assert all(c["proposal"] is None for c in runtime.ledger.transcript(turn["id"])["calls"])
        assert not runtime.ledger._rows("tool_decisions")
        assert len(transport.requests) == 2
        runtime.storage.validate()

    client.portal.call(exercise)
    assert observed and runtime.scenarios.path.read_bytes() == before


@pytest.mark.parametrize("phase", ["read", "prepare"])
@pytest.mark.parametrize("ending", ["cancel", "timeout"])
def test_native_read_prepare_retirement_blocks_replacement(client, monkeypatch, phase, ending):
    import threading

    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_append")
    entered, release = threading.Event(), threading.Event()
    name = "read_configuration" if phase == "read" else "prepare_scenario"
    real = getattr(runtime.scenarios, name)
    runtime.turn_seconds = 0.4 if ending == "timeout" else 3

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return real(*args, **kwargs)

    monkeypatch.setattr(runtime.scenarios, name, blocked)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            assert runtime.worker.busy and not runtime.storage.db.in_transaction
            if ending == "cancel":
                await runtime.cancel(turn["id"])
            else:
                await asyncio.sleep(0.5)
            assert runtime.worker.busy and runtime.active == turn["id"]
            assert not runtime.task.done()
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                runtime.check_idle()
        finally:
            release.set()
            await runtime.task
            await runtime.worker.settle()
        calls = runtime.ledger.transcript(turn["id"])["calls"]
        assert all(c["proposal"] is None for c in calls)
        assert calls[-1]["error_code"] == (
            "CHAT_TIMEOUT" if ending == "timeout" else "CHAT_CANCELLED"
        )
        assert runtime.ledger.reservation(turn["id"])["retired"]
        assert not runtime.worker.busy
        runtime.storage.validate()

    client.portal.call(exercise)


def test_public_transcript_exposes_wait_but_approval_and_send_stay_closed(client, monkeypatch):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create")
    turn, _ = client.portal.call(runtime._accept_scenario_tool, grant["session_id"], value)
    try:
        expected = client.portal.call(waiting, runtime, turn["id"])
        response = client.get(f"/api/v1/chat/turns/{turn['id']}/tools")
        assert response.status_code == 200 and response.json() == expected
        call = expected["calls"][-1]
        before = client.portal.call(lambda: list(runtime.storage.db.iterdump()))
        response = client.post(
            f"/api/v1/chat/tool-calls/{call['id']}/decision",
            json=dict(
                request_id=str(uuid4()),
                proposal_digest=call["proposal"]["digest"],
                decision="approve",
            ),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "CHAT_TOOL_APPROVAL_CONFLICT"
        response = client.post(
            f"/api/v1/chat/sessions/{grant['session_id']}/tool-turns", json=value.model_dump()
        )
        assert response.status_code == 409
        assert response.json()["code"] == "CHAT_TOOL_GRANT_INVALID"
        assert client.portal.call(lambda: list(runtime.storage.db.iterdump())) == before
        assert len(transport.requests) == 2
    finally:
        client.portal.call(runtime.cancel, turn["id"])
        client.portal.call(lambda: runtime.task)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_three_call_budget_with_pinned_detail_and_terminal_fourth_round(
    client, monkeypatch, operation
):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, operation)
    detail = dict(kind="scenario", **grant["intent"]["input_source"]["reference"])
    transport.frames.insert(
        1, native_bytes("configuration_read", encoded(detail).decode(), "detail", True)
    )
    transport.frames.append(
        b"data: "
        + encoded(
            dict(choices=[dict(index=0, delta=dict(content="Not saved."), finish_reason="stop")])
        )
        + b"\n\ndata: [DONE]\n\n"
    )

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            transcript = await waiting(runtime, turn["id"])
            assert len(transcript["calls"]) == 3
            detail_call = transcript["calls"][1]
            assert detail_call["result"]["kind"] == "scenario"
            assert (
                reference(detail_call["result"]["scenario"])
                == grant["intent"]["input_source"]["reference"]
            )
            call = transcript["calls"][-1]
            await runtime.decide_tool(
                call["id"],
                DecisionInput(
                    request_id=str(uuid4()),
                    proposal_digest=call["proposal"]["digest"],
                    decision="deny",
                ),
            )
            await runtime.task
            assert len(transport.requests) == 4
            assert "tools" not in transport.requests[-1]
            assert runtime.storage.turn(turn["id"])["status"] == "succeeded"
            runtime.storage.validate()
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


def test_internal_admission_timeout_keeps_native_lease_until_retirement(client, monkeypatch):
    import threading

    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create")
    runtime.turn_seconds = 0.05
    entered, release = threading.Event(), threading.Event()
    real = runtime.draft.ai_snapshot

    def slow():
        entered.set()
        assert release.wait(3)
        return real()

    monkeypatch.setattr(runtime.draft, "ai_snapshot", slow)

    async def exercise():
        task = asyncio.create_task(runtime._accept_scenario_tool(grant["session_id"], value))
        try:
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            await asyncio.sleep(0.12)
            assert task.done(), "original admission clock did not interrupt native observation"
            with pytest.raises(DraftError, match="CHAT_TIMEOUT"):
                await task
            assert runtime.worker.busy and not runtime.preparing
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                runtime.check_idle()
            assert not transport.requests and runtime.active is None
            assert runtime.ledger.grant(grant["id"])["status"] == "pending"
            assert not runtime.storage.db.in_transaction
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await runtime.worker.settle()

    client.portal.call(exercise)
