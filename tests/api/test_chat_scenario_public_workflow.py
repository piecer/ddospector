"""Public HTTP authority, native proposal and durable scenario saving."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx2
import pytest
import test_chat_scenario_proposal_runtime as producer
from chat_scenario_capture import ScenarioCapture
from test_chat_scenario_grant_staging import bootstrap
from test_chat_scenario_save_runtime import approval, audit_saved, capture_transport, final_bytes


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_public_scenario_separate_approval_saves_exact_history(client, monkeypatch, operation):
    issued = []
    capture = ScenarioCapture(operation)

    def public_issue(client, runtime, value):
        response = client.post("/api/v1/chat/tool-grants", json=value)
        capture.record("grant", response)
        assert response.status_code == 201, response.text
        issued.append((value, response.json()))
        replay = client.post("/api/v1/chat/tool-grants", json=value)
        capture.record("grant-replay", replay)
        assert replay.status_code == 200 and replay.json() == response.json()
        lookup = client.get(f"/api/v1/chat/tool-grants/by-request/{value['request_id']}")
        capture.record("grant-lookup", lookup)
        assert lookup.status_code == 200 and lookup.json() == response.json()
        return response.json(), response.status_code

    monkeypatch.setattr(producer, "issue", public_issue)
    runtime, grant, value, transport, raw = producer.setup_path(
        client, monkeypatch, operation, streaming=False
    )
    transport.frames.append(final_bytes())
    capture_transport(transport)
    before = runtime.scenarios.path.read_bytes()
    state_before = capture.record("state-before", client.get("/api/v1/chat/tools/scenarios/state"))
    assert state_before.status_code == 200
    for name, path in (
        ("chat-runtime", "/api/v1/chat/runtime"),
        ("sessions", "/api/v1/chat/sessions"),
        ("fence", "/api/v1/chat/tools/fence"),
    ):
        assert capture.record(name, client.get(path)).status_code == 200
    metadata = client.get("/api/v1/chat/tools/runtime")
    capture.record("runtime", metadata)
    assert metadata.status_code == 200
    assert metadata.json()["schema_version"] == 4
    assert metadata.json()["tools"] == [
        "configuration_read", "agent_profile_update", "target_create", "skill_create",
        "scenario_create", "scenario_append",
    ]
    accepted = client.post(
        f"/api/v1/chat/sessions/{grant['session_id']}/tool-turns", json=value.model_dump()
    )
    capture.record("turn", accepted)
    assert accepted.status_code == 202, accepted.text
    turn = accepted.json()
    client.portal.call(producer.waiting, runtime, turn["id"])
    waiting = client.get(f"/api/v1/chat/turns/{turn['id']}/tools")
    capture.record("proposal", waiting)
    assert waiting.status_code == 200
    call = waiting.json()["calls"][-1]
    assert call["status"] == "awaiting_approval"
    assert runtime.scenarios.path.read_bytes() == before
    decision = approval(call).model_dump()
    receipt = client.post(f"/api/v1/chat/tool-calls/{call['id']}/decision", json=decision)
    capture.record("decision", receipt)
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["proposal_digest"] == call["proposal"]["digest"]

    async def finished():
        async with asyncio.timeout(4):
            task = runtime.task
            if task is not None:
                await task
        return audit_saved(runtime, turn, grant, raw)

    saved_call = client.portal.call(finished)
    saved = client.get(f"/api/v1/chat/turns/{turn['id']}/tools")
    capture.record("saved", saved)
    assert saved.status_code == 200 and saved.json()["calls"][-1] == saved_call
    record = saved_call["result"]["scenario"]
    history = client.get(f"/api/v1/scenarios/{record['id']}")
    capture.record("history", history)
    assert history.status_code == 200, history.text
    assert record in history.json()["versions"]
    chat_history = client.get(f"/api/v1/chat/sessions/{grant['session_id']}")
    capture.record("chat-history", chat_history)
    assert chat_history.status_code == 200
    assert chat_history.json()["turns"][-1]["status"] == "succeeded"
    replay = client.post(f"/api/v1/chat/tool-calls/{call['id']}/decision", json=decision)
    capture.record("decision-replay", replay)
    assert replay.status_code == 200 and replay.json() == receipt.json()
    assert len(issued) == 1 and len(transport.requests) == 3
    assert not runtime.worker.busy and runtime.active is None
    state_after = capture.record("state-after", client.get("/api/v1/chat/tools/scenarios/state"))
    assert state_after.status_code == 200
    capture.finish()


@pytest.mark.parametrize("mutation", ["duplicate", "version_float", "version_exponent", "unknown"])
def test_public_grant_rejects_raw_invalid_input_without_admission(client, mutation):
    runtime, body, _ = bootstrap(client)
    raw = json.dumps(body, separators=(",", ":"))
    if mutation == "duplicate":
        raw = raw.replace('"schema_version":4', '"schema_version":3,"schema_version":4')
    elif mutation == "version_float":
        raw = raw.replace('"schema_version":4', '"schema_version":4.0')
    elif mutation == "version_exponent":
        raw = raw.replace('"schema_version":4', '"schema_version":4e0')
    else:
        raw = raw[:-1] + ',"execute":true}'
    before = client.portal.call(lambda: list(runtime.storage.db.iterdump()))
    response = client.post("/api/v1/chat/tool-grants", content=raw,
                           headers={"content-type": "application/json"})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == (
        "VALIDATION_ERROR" if mutation == "duplicate" else "CHAT_INVALID_REQUEST"
    )
    assert client.portal.call(lambda: list(runtime.storage.db.iterdump())) == before
    assert not runtime.preparing and runtime.active is None


def test_public_scenario_turn_rejects_duplicate_keys_before_admission(client, monkeypatch):
    runtime, grant, value, transport, _ = producer.setup_path(
        client, monkeypatch, "scenario_create", streaming=False
    )
    raw = json.dumps(value.model_dump(), separators=(",", ":")).replace(
        '"expected_sequence":0', '"expected_sequence":1,"expected_sequence":0'
    )
    before = client.portal.call(lambda: list(runtime.storage.db.iterdump()))
    response = client.post(f"/api/v1/chat/sessions/{grant['session_id']}/tool-turns",
                           content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert client.portal.call(lambda: list(runtime.storage.db.iterdump())) == before
    assert not transport.requests and runtime.active is None


def test_public_v4_reconcile_reaches_revision_fence_without_mutation(client):
    runtime, body, _ = bootstrap(client)
    before = client.portal.call(lambda: list(runtime.storage.db.iterdump()))
    response = client.post("/api/v1/chat/tools/reconcile", json={
        "schema_version": 4, "request_id": str(uuid4()), "expected_generation": 0,
        "expected_draft_revision": body["intent"]["expected_draft_revision"],
        "expected_scenario_revision": 0, "acknowledge_uncertain": True,
    })
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CHAT_TOOL_CONFLICT"
    assert client.portal.call(lambda: list(runtime.storage.db.iterdump())) == before


def test_public_reconcile_preserves_uncertain_outcome_and_checks_all_revisions(client, monkeypatch):
    runtime, grant, value, transport, _ = producer.setup_path(
        client, monkeypatch, "scenario_append", streaming=False
    )
    capture = ScenarioCapture("reconcile")
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=client.app), base_url="http://localhost"
        ) as http:
            accepted = capture.record("turn", await http.post(
                f"/api/v1/chat/sessions/{grant['session_id']}/tool-turns", json=value.model_dump()
            ))
            assert accepted.status_code == 202, accepted.text
            turn = accepted.json()
            call = (await producer.waiting(runtime, turn["id"]))["calls"][-1]
            receipt = capture.record("decision", await http.post(
                f"/api/v1/chat/tool-calls/{call['id']}/decision", json=approval(call).model_dump()
            ))
            assert receipt.status_code == 201, receipt.text
            # Same event-loop turn: cancel at durable intent before producer resumes.
            await runtime.cancel(turn["id"])
            await runtime.task
            uncertain = capture.record("uncertain", await http.get(
                f"/api/v1/chat/turns/{turn['id']}/tools"
            ))
            assert uncertain.json()["calls"][-1]["status"] == "uncertain"
            fence = capture.record("fence", await http.get("/api/v1/chat/tools/fence"))
            state = capture.record("state", await http.get("/api/v1/chat/tools/scenarios/state"))
            assert fence.status_code == state.status_code == 200
            body = {
                "schema_version": 4, "request_id": str(uuid4()),
                "expected_generation": fence.json()["generation"],
                "expected_draft_revision": fence.json()["current_draft_revision"],
                "expected_scenario_revision": state.json()["scenario_revision"],
                "acknowledge_uncertain": True,
            }
            image = list(runtime.storage.db.iterdump())
            for field in (
                "expected_generation", "expected_draft_revision", "expected_scenario_revision"
            ):
                denied = await http.post(
                    "/api/v1/chat/tools/reconcile", json=body | {field: body[field] + 1}
                )
                assert denied.status_code == 409 and denied.json()["code"] == "CHAT_TOOL_CONFLICT"
                assert list(runtime.storage.db.iterdump()) == image
            reconciled = capture.record("reconcile", await http.post(
                "/api/v1/chat/tools/reconcile", json=body
            ))
            assert reconciled.status_code == 201, reconciled.text
            assert reconciled.json()["scenario_recovery"] == "not_performed"
            assert reconciled.json()["prior_outcomes"] == "remain_uncertain"
            assert reconciled.json()["acknowledged_call_ids"] == [call["id"]]
            replay = capture.record("reconcile-replay", await http.post(
                "/api/v1/chat/tools/reconcile", json=body
            ))
            assert replay.status_code == 200 and replay.json() == reconciled.json()
            assert runtime.ledger.call(call["id"])["status"] == "uncertain"
            assert not runtime.ledger.fence()["fenced"]
            runtime.storage.validate()
            assert runtime.scenarios.path.read_bytes() == before
            assert len(transport.requests) == 2
            capture.finish()

    client.portal.call(exercise)


def test_current_public_runtime_reaches_existing_acceptance_selectors(client, monkeypatch, tmp_path):
    bootstrap(client)
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "tools"))
    import chat_tools_acceptance as acceptance

    assert Path(acceptance.__file__).resolve() == source / "tools/chat_tools_acceptance.py"

    def actual_http(_base, path):
        response = client.get(path)
        return response.status_code, response.json()

    monkeypatch.setattr(acceptance, "http", actual_http)
    for case in ("agent", "target", "skill"):
        acceptance.require_runtime("in-process", tmp_path, fixture_case=case)
