"""Internal v4 issuance through real owned stores; public sending stays closed."""

import asyncio
import threading
from copy import deepcopy
from uuid import uuid4

import pytest
from chat_scenario_support import intent_for, reference
from scenario_producer import definition, register_targets
from test_chat_runtime import configure
from test_chat_sessions import start

from aiddos.api import chat_tool_runtime
from aiddos.api.chat_models import encoded
from aiddos.api.chat_scenario_models import GrantInputV4, GrantV4
from aiddos.api.errors import DraftError, error_response
from aiddos.api.models import AISettingsInput
from aiddos.api.scenarios import ScenarioInput


def bootstrap(client):
    configure(client)
    value = definition(register_targets(client))
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
        intent=intent_for(runtime.draft, runtime.scenarios, value),
    )
    return runtime, body, value


def issue(client, runtime, body):
    return client.portal.call(runtime.create_grant, GrantInputV4.model_validate(body))


def test_real_operator_issue_replay_lookup(client):
    runtime, body, _ = bootstrap(client)
    grant, status = issue(client, runtime, body)
    assert status == 201
    assert GrantV4.model_validate(grant).model_dump() == grant
    assert grant["intent"] == body["intent"]
    assert grant["resolved_inputs"] == body["intent"]["input_source"]["inputs"]
    assert grant["status"] == "pending"
    assert issue(client, runtime, body) == (grant, 200)
    assert client.portal.call(runtime.ledger.grant, grant["id"]) == grant
    client.portal.call(runtime.storage.validate)


def test_public_v4_issuance_remains_closed(client, monkeypatch):
    runtime, body, _ = bootstrap(client)

    async def forbidden(*args, **kwargs):
        raise AssertionError("public v4 body reached runtime")

    monkeypatch.setattr(runtime, "create_grant", forbidden)
    response = client.post("/api/v1/chat/tool-grants", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "CHAT_INVALID_REQUEST"
    view = client.get("/api/v1/chat/tools/runtime").json()
    assert view["schema_version"] == 3
    assert view["tools"] == [
        "configuration_read", "agent_profile_update", "target_create", "skill_create"
    ]


def test_known_v4_send_denied_before_any_preparation(client, monkeypatch):
    runtime, body, _ = bootstrap(client)
    grant, _ = issue(client, runtime, body)

    def image():
        return list(runtime.storage.db.iterdump())

    before = client.portal.call(image)
    clocks = dict(runtime.grant_deadlines)

    def forbidden(*args, **kwargs):
        raise AssertionError("v4 send reached allocation or producer preparation")

    for owner, name in (
        (runtime.worker, "ai_snapshot"), (runtime, "context"),
        (chat_tool_runtime, "schemas"), (chat_tool_runtime, "uuid4"),
        (runtime, "produce_tools"), (runtime.ledger, "admit"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    response = client.post(
        f"/api/v1/chat/sessions/{body['session_id']}/tool-turns",
        json=dict(request_id=body["turn_request_id"], expected_sequence=0,
                  text=body["text"], grant_id=grant["id"]),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CHAT_TOOL_GRANT_INVALID"
    assert client.portal.call(image) == before
    assert runtime.grant_deadlines == clocks
    assert not runtime.preparing and runtime.active is None and runtime.task is None
    assert client.portal.call(runtime.ledger.grant, grant["id"]) == grant
    with pytest.raises(ValueError, match="Unknown authority"):
        chat_tool_runtime.authority_version(grant)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
@pytest.mark.parametrize("source", ["operator", "scenario_version"])
def test_full_intent_provenance_and_historical_replay(client, monkeypatch, operation, source):
    runtime, body, value = bootstrap(client)
    store = runtime.scenarios
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    second = store.save(
        ScenarioInput(revision=1, definition=value | {"policy_version": "other"})
    )["scenario"]
    base = reference(second) if operation == "scenario_append" else None
    origin = (
        {"source": source, "reference": reference(first)}
        if source == "scenario_version" else None
    )
    body["intent"] = intent_for(runtime.draft, store, value, base=base, source=origin)
    observed = []
    resolve = store.resolve_intent

    def tracked(*args):
        observed.append(deepcopy(args))
        return resolve(*args)

    monkeypatch.setattr(store, "resolve_intent", tracked)
    grant, status = issue(client, runtime, body)
    assert status == 201 and len(observed) == 1
    assert grant["intent"] == body["intent"]
    assert grant["resolved_inputs"]["policy_version"] == value["policy_version"]
    assert grant["proposal_tools"] == [operation]
    deadlines = dict(runtime.grant_deadlines)
    # Change the real source revision/settings, then make both unavailable.
    store.save(ScenarioInput(revision=2, definition=value))
    configure(client, model="changed")

    def forbidden(*args, **kwargs):
        raise AssertionError("historical replay consulted mutable state or allocated identity")

    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", forbidden)
    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    monkeypatch.setattr(chat_tool_runtime, "uuid4", forbidden)
    assert issue(client, runtime, body) == (grant, 200)
    assert runtime.grant_deadlines == deadlines
    lookup = client.get(f"/api/v1/chat/tool-grants/by-request/{body['request_id']}")
    assert lookup.status_code == 200 and lookup.json() == grant
    revoked = client.post(f"/api/v1/chat/tool-grants/{grant['id']}/revoke", json={})
    assert revoked.status_code == 200 and revoked.json() == grant | {"status": "revoked"}
    assert issue(client, runtime, body) == (revoked.json(), 200)
    assert len(observed) == 1


@pytest.mark.parametrize("field", [
    "request_text", "session", "sequence", "turn", "draft_revision", "scenario_revision",
    "operation", "operator_inputs", "source", "base", "source_digest",
])
def test_changed_commitment_conflicts_before_resolution(client, monkeypatch, field):
    runtime, body, value = bootstrap(client)
    a = runtime.scenarios.save(ScenarioInput(revision=0, definition=value))["scenario"]
    b = runtime.scenarios.save(ScenarioInput(revision=1, definition=value))["scenario"]
    body["intent"] = intent_for(runtime.draft, runtime.scenarios, value,
                                base=reference(b),
                                source={"source": "scenario_version", "reference": reference(a)})
    grant, _ = issue(client, runtime, body)
    changed = deepcopy(body)
    if field == "request_text":
        changed["text"] += " changed"
    elif field in {"session", "turn"}:
        changed[{"session": "session_id", "turn": "turn_request_id"}[field]] = str(uuid4())
    elif field == "sequence":
        changed["expected_sequence"] += 1
    elif field in {"draft_revision", "scenario_revision"}:
        changed["intent"]["expected_" + field] += 1
    elif field == "operation":
        changed["intent"].update(operation="scenario_create", base=None)
    elif field in {"operator_inputs", "source"}:
        changed["intent"]["input_source"] = dict(
            source="operator", inputs=deepcopy(grant["resolved_inputs"])
        )
        if field == "operator_inputs":
            changed["intent"]["input_source"]["inputs"]["policy_version"] = "replacement"
    elif field == "base":
        changed["intent"]["base"] = reference(a)
    else:
        changed["intent"]["input_source"]["reference"]["digest"] = "f" * 64

    def forbidden(*args, **kwargs):
        raise AssertionError("conflict consulted mutable authority")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", forbidden)
    with pytest.raises(DraftError) as exc:
        issue(client, runtime, changed)
    assert exc.value.code == "CHAT_TOOL_GRANT_CONFLICT"
    assert client.portal.call(runtime.ledger.grant, grant["id"]) == grant


def test_copied_model_extras_and_nested_mutation_do_not_escape(client, monkeypatch):
    runtime, body, _ = bootstrap(client)
    model = GrantInputV4.model_validate(body)
    for invalid in (
        model.model_copy(update={"extra": "must reject"}),
        model.model_copy(update={"intent": model.intent.model_copy(update={"extra": 1})}),
        model.model_copy(update={"schema_version": True}),
    ):
        with pytest.raises(ValueError):
            client.portal.call(runtime.create_grant, invalid)
    original = deepcopy(body)
    snapshot = runtime.worker.ai_snapshot
    seen = []

    async def mutate(**kwargs):
        if not seen:
            seen.append(True)
            model.intent.input_source.inputs.traffic_budget.max_pps += 1
        return await snapshot(**kwargs)

    monkeypatch.setattr(runtime.worker, "ai_snapshot", mutate)
    grant, _ = client.portal.call(runtime.create_grant, model)
    assert grant["intent"] == original["intent"]
    grant["resolved_inputs"]["traffic_budget"]["max_pps"] += 1
    retained = client.portal.call(runtime.ledger.grant, grant["id"])
    assert retained["resolved_inputs"] == original["intent"]["input_source"]["inputs"]


@pytest.mark.parametrize("fault,code", [
    ("scenario_revision", "CHAT_TOOL_CONFLICT"), ("draft_revision", "CHAT_TOOL_CONFLICT"),
    ("missing", "CHAT_NOT_FOUND"), ("digest", "CHAT_TOOL_CONFLICT"),
    ("stale_base", "CHAT_TOOL_CONFLICT"), ("roles", "CHAT_INVALID_REQUEST"),
    ("settings", "CHAT_BINDING_CHANGED"), ("quarantine", "CHAT_SCENARIO_WRITE_FENCED"),
])
def test_real_source_refusals_publish_nothing(client, fault, code):
    runtime, body, value = bootstrap(client)
    store = runtime.scenarios
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    body["intent"] = intent_for(runtime.draft, store, value, base=reference(first))
    if fault.endswith("revision"):
        body["intent"]["expected_" + fault] += 1
    elif fault in {"missing", "digest"}:
        body["intent"]["input_source"] = dict(source="scenario_version", reference=reference(first))
        body["intent"]["input_source"]["reference"]["id" if fault == "missing" else "digest"] = (
            "missing" if fault == "missing" else "f" * 64)
    elif fault == "stale_base":
        store.save(ScenarioInput(revision=1, definition=value), first["id"])
        body["intent"]["expected_scenario_revision"] = 2
    elif fault == "roles":
        inputs = body["intent"]["input_source"]["inputs"]
        inputs["target_id"], inputs["sink_id"] = inputs["sink_id"], inputs["target_id"]
    elif fault == "settings":
        configure(client, model="changed")
    else:
        store.coordinator.blocked = True
    with pytest.raises(DraftError) as exc:
        issue(client, runtime, body)
    assert exc.value.code == code
    assert client.portal.call(lambda: runtime.ledger._rows("tool_grants")) == []
    assert not runtime.preparing and runtime.grant_deadlines == {}
    if fault == "quarantine":
        assert store.coordinator.blocked
        response = error_response(exc.value.code)
        assert response.status_code == 409
        assert response.body == (
            b'{"code":"CHAT_SCENARIO_WRITE_FENCED",'
            b'"message":"Scenario writes are quarantined; inspect storage before retrying."}'
        )


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("phase", ["settings", "resolve"])
@pytest.mark.parametrize("completion", ["normal", "cancel", "timeout", "stop"])
def test_preparation_lease_and_native_retirement(client, monkeypatch, phase, completion):
    runtime, body, _ = bootstrap(client)
    entered, release = threading.Event(), threading.Event()
    if phase == "resolve":
        owner, name = runtime.scenarios, "resolve_intent"
    else:
        owner, name = runtime.draft, "ai_snapshot"
    real = getattr(owner, name)
    calls = []

    def blocked(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, blocked)
    monkeypatch.setattr(runtime, "turn_seconds", 0.15 if completion == "timeout" else 3)

    async def exercise():
        task = asyncio.create_task(runtime.create_grant(GrantInputV4.model_validate(body)))
        try:
            await wait_until(entered.is_set)
            assert runtime.preparing and runtime.worker.busy
            assert not runtime.storage.db.in_transaction
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                await runtime.tools_scenario_state()
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                await runtime.create_grant(
                    GrantInputV4.model_validate(body | {"request_id": str(uuid4())})
                )
            if completion == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif completion == "timeout":
                with pytest.raises(DraftError, match="CHAT_TIMEOUT"):
                    await task
            elif completion == "stop":
                runtime.stop_signal.set()
                release.set()
                with pytest.raises(DraftError, match="CHAT_CANCELLED"):
                    await task
            else:
                release.set()
                assert (await task)[1] == 201
            assert not runtime.preparing
            if completion in {"cancel", "timeout"}:
                assert runtime.worker.busy
                with pytest.raises(DraftError, match="CHAT_BUSY"):
                    await runtime.tools_runtime()
            if completion != "normal":
                assert runtime.ledger._rows("tool_grants") == []
                assert runtime.grant_deadlines == {}
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await runtime.worker.settle()
            await wait_until(lambda: not runtime.worker.busy)
        assert not runtime.preparing

    client.portal.call(exercise)


@pytest.mark.parametrize("change,code", [
    ("late", "CHAT_TIMEOUT"), ("settings", "CHAT_BINDING_CHANGED"),
    ("stop", "CHAT_CANCELLED"), ("shutdown", "CHAT_SHUTTING_DOWN"),
    ("fence", "CHAT_COMMIT_UNCERTAIN"), ("session", "CHAT_TOOL_GRANT_INVALID"),
])
def test_final_publication_checks_after_real_resolution(client, monkeypatch, change, code):
    runtime, body, _ = bootstrap(client)
    real = runtime.worker.resolve_scenario_intent
    fired = []
    old_session = client.portal.call(runtime.storage.session, body["session_id"])[0]

    async def resolved_then_changed(*args, **kwargs):
        result = await real(*args, **kwargs)
        fired.append(True)
        if change == "late":
            clock = chat_tool_runtime.monotonic
            monkeypatch.setattr(chat_tool_runtime, "monotonic",
                                lambda: clock() + runtime.turn_seconds + 1)
        elif change == "settings":
            snapshot = runtime.draft.ai_snapshot()
            runtime.draft.save_ai_settings(AISettingsInput.model_validate({
                k: snapshot[k] for k in
                ("revision", "profiles", "default_profile_id", "agent_profile_id")
            }))
        elif change == "stop":
            runtime.stop_signal.set()
        elif change == "shutdown":
            runtime.stopping = True
        elif change == "fence":
            runtime.storage.fenced = True
        else:
            # In-flight sequence/session change; restored after the refusal.
            runtime.storage.db.execute("UPDATE sessions SET data=? WHERE id=?", (
                encoded(old_session | {"sequence": 1}).decode(), body["session_id"]
            ))
            runtime.storage.db.commit()
        return result

    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", resolved_then_changed)
    try:
        with pytest.raises(DraftError, match=code):
            issue(client, runtime, body)
        assert fired == [True]
        count = client.portal.call(lambda: runtime.storage.db.execute(
            "SELECT count(*) FROM tool_grants").fetchone())
        assert count == (0,) and runtime.grant_deadlines == {}
        assert not runtime.preparing
    finally:
        if change == "session":
            def restore():
                runtime.storage.db.execute("UPDATE sessions SET data=? WHERE id=?", (
                    encoded(old_session).decode(), body["session_id"]
                ))
                runtime.storage.db.commit()
            client.portal.call(restore)


@pytest.mark.parametrize("fault", ["registry_corrupt", "receipt_unavailable"])
def test_source_storage_failure_does_not_publish_or_clear(client, monkeypatch, fault):
    from aiddos.api import scenario_persistence

    runtime, body, _ = bootstrap(client)
    store = runtime.scenarios
    fired = []
    if fault == "registry_corrupt":
        store.path.write_bytes(b"corrupt owned registry")
    else:
        read = scenario_persistence.read_bytes

        def unavailable(path, *args, **kwargs):
            if path == store.receipt_path:
                fired.append(True)
                raise OSError("owned unavailable receipt")
            return read(path, *args, **kwargs)

        monkeypatch.setattr(scenario_persistence, "read_bytes", unavailable)
    before = {p: p.read_bytes() for p in store.path.parent.glob("*.json")}
    with pytest.raises(DraftError, match="CHAT_STORAGE_ERROR"):
        issue(client, runtime, body)
    assert {p: p.read_bytes() for p in before} == before
    assert client.portal.call(lambda: runtime.ledger._rows("tool_grants")) == []
    if fault == "receipt_unavailable":
        assert fired == [True]
