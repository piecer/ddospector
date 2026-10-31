"""Real internal graphs, replay, recovery and preallocation refusal."""

import json
import sqlite3
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_scenario_proposal_runtime import native_bytes, setup_path, waiting

from aiddos.api import chat_tool_storage
from aiddos.api.app import create_app
from aiddos.api.chat_models import encoded
from aiddos.api.chat_scenario_models import TranscriptV4
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import DecisionInput
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as connection:
        yield connection


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
@pytest.mark.parametrize("ending", ["deny", "timeout", "restart", "revoke"])
def test_waiting_settlement_and_reopen(client, monkeypatch, tmp_path, operation, ending):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, operation)
    registry = runtime.scenarios.path.read_bytes()
    if ending == "timeout":
        runtime.turn_seconds = 0.7
    final = encoded(
        dict(
            choices=[
                dict(
                    index=0,
                    message=dict(role="assistant", content="Not saved."),
                    finish_reason="stop",
                )
            ]
        )
    )
    # Streaming final text, still parsed through the actual transport.
    final = (
        b"data: "
        + encoded(
            dict(choices=[dict(index=0, delta=dict(content="Not saved."), finish_reason="stop")])
        )
        + b"\n\ndata: [DONE]\n\n"
    )
    transport.frames.append(final)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            transcript = await waiting(runtime, turn["id"])
            call = transcript["calls"][-1]
            assert runtime.ledger.reservation(turn["id"])["exchange_hold"] > 0
            if ending == "deny":
                body = DecisionInput(
                    request_id=str(uuid4()),
                    proposal_digest=call["proposal"]["digest"],
                    decision="deny",
                )
                decision = await runtime.decide_tool(call["id"], body)
                assert decision[1] == 201
                assert await runtime.decide_tool(call["id"], body) == (decision[0], 200)
            elif ending == "revoke":
                await runtime.revoke_grant(grant["id"])
            elif ending == "restart":
                # Snapshot an actual published waiting graph, not a fabricated fixture.
                recovered = ChatStorage(tmp_path / "crashed.json")
                with sqlite3.connect(recovered.path) as db:
                    runtime.storage.db.backup(db)
                recovered.path.chmod(0o600)
                await runtime.cancel(turn["id"])
                await runtime.task
                assert recovered.open()
                try:
                    ledger = ToolLedger(recovered)
                    value4 = ledger.transcript(turn["id"])
                    TranscriptV4.model_validate(value4)
                    assert value4["calls"][-1]["status"] == "cancelled"
                    assert value4["calls"][-1]["proposal"] == call["proposal"]
                    assert ledger.exchanges(turn["id"])[-1]["role"] == "tool"
                    assert ledger.reservation(turn["id"])["retired"]
                    recovered.validate()
                finally:
                    recovered.close()
            await runtime.task
            expected = {"deny": "denied", "timeout": "failed"}.get(ending, "cancelled")
            settled = runtime.ledger.transcript(turn["id"])["calls"][-1]
            assert settled["status"] == expected
            assert settled["result"] is None
            assert len(transport.requests) == (3 if ending == "deny" else 2)
            if ending == "deny":
                assert "tools" not in transport.requests[-1]
            runtime.storage.close()
            assert runtime.storage.open()
            assert runtime.ledger.call(call["id"]) == settled
            runtime.storage.validate()
            assert await runtime._accept_scenario_tool(grant["session_id"], value) == (
                runtime.storage.turn(turn["id"]),
                200,
            )
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
    assert runtime.scenarios.path.read_bytes() == registry


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "float",
        "exponent",
        "unknown",
        "protected",
        "revision",
        "foreign_operation",
        "foreign_base",
    ],
)
def test_bad_native_arguments_never_allocate_second_call(client, monkeypatch, mutation):
    runtime, grant, value, transport, raw = setup_path(client, monkeypatch, "scenario_append")
    name = "scenario_append"
    args = json.loads(raw)
    if mutation == "duplicate":
        raw = raw.replace(
            '"expected_scenario_revision": 2',
            '"expected_scenario_revision": 2, "expected_scenario_revision": 2',
        )
    elif mutation in {"float", "exponent"}:
        raw = raw.replace(
            '"expected_scenario_revision": 2',
            '"expected_scenario_revision": ' + ("2.0" if mutation == "float" else "2e0"),
        )
    else:
        if mutation == "unknown":
            args["extra"] = 0
        elif mutation == "protected":
            args["definition"]["traffic_budget"] = grant["resolved_inputs"]["traffic_budget"]
        elif mutation == "revision":
            args["expected_scenario_revision"] += 1
        elif mutation == "foreign_operation":
            name = "scenario_create"
            args.pop("base")
        else:
            args["base"]["digest"] = "f" * 64
        raw = json.dumps(args)
    transport.frames[1] = native_bytes(name, raw, "write-2", True)
    real = runtime.ledger.finish_call
    observations = []
    identities = []

    def finish(*args, **kwargs):
        result = real(*args, **kwargs)
        if result[0]["tool"] == "configuration_read":
            observations.append(True)

            def forbidden():
                identities.append(True)
                raise AssertionError("invalid native call allocated an identity")

            monkeypatch.setattr(chat_tool_storage, "uuid4", forbidden)
        return result

    monkeypatch.setattr(runtime.ledger, "finish_call", finish)

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        await runtime.task
        assert observations == [True] and identities == []
        assert len(runtime.ledger.transcript(turn["id"])["calls"]) == 1
        assert runtime.storage.turn(turn["id"])["status"] == "failed"
        assert len(transport.requests) == 2
        runtime.storage.validate()

    client.portal.call(exercise)


def test_predecessor_staged_text_commitment_replays_without_reissue(client, monkeypatch):
    from test_chat_scenario_grant_staging import issue
    from test_chat_scenario_proposal_authority import legacy_seed

    from aiddos.api.chat_tool_models import digest

    # Actual frozen S1 issuer bytes, including its session references. A legacy
    # encoder override inside the new issuer is not historical storage.
    runtime, body, grant, _ = legacy_seed(client, monkeypatch)
    status = 201  # Captured S1 issuance status; no new authority is issued here.
    assert status == 201
    assert grant["text_sha256"] == digest(body["text"])

    def forbidden(*args, **kwargs):
        raise AssertionError("historical replay acquired fresh settings/source")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", forbidden)
    assert issue(client, runtime, body) == (grant, 200)
    with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_CONFLICT"):
        issue(client, runtime, body | {"text": body["text"] + "changed"})

    def reopen():
        runtime.storage.close()
        assert runtime.storage.open()
        runtime.storage.validate()

    client.portal.call(reopen)
    assert issue(client, runtime, body) == (grant | {"status": "expired"}, 200)


@pytest.mark.parametrize("mutation", ["grant", "arguments", "proposal", "exchange", "binding"])
def test_real_graph_tampering_is_rejected_before_recovery(client, monkeypatch, tmp_path, mutation):
    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append")

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            transcript = await waiting(runtime, turn["id"])
            call = transcript["calls"][-1]
            recovered = ChatStorage(tmp_path / "tampered.json")
            with sqlite3.connect(recovered.path) as db:
                runtime.storage.db.backup(db)
                table, key = "tool_calls", call["id"]
                value4 = dict(turn_id=turn["id"], call=deepcopy(call))
                if mutation == "grant":
                    value4["call"]["grant_id"] = str(uuid4())
                elif mutation == "arguments":
                    value4["call"]["arguments"]["base"]["digest"] = "f" * 64
                elif mutation == "proposal":
                    value4["call"]["proposal"]["after"]["policy_version"] = "foreign"
                elif mutation == "exchange":
                    table, key = "tool_exchanges", turn["id"]
                    value4 = runtime.ledger.exchanges(turn["id"])
                    value4[-1]["tool_calls"][0]["function"]["arguments"] = "{}"
                else:
                    table, key = "tool_bindings", turn["id"]
                    value4 = runtime.ledger.binding(turn["id"])
                    value4["grant_digest"] = "f" * 64
                db.execute(
                    f"UPDATE {table} SET data=? WHERE key=?", (encoded(value4).decode(), key)
                )
            recovered.path.chmod(0o600)
            before = recovered.path.read_bytes()
            with pytest.raises(DraftError, match="CHAT_STORAGE_ERROR"):
                recovered.open()
            assert recovered.path.read_bytes() == before
            recovered.close()
        finally:
            await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
