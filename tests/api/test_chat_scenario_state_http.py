"""Read-only scenario metadata through the real, socket-free ASGI app."""

import asyncio
import threading

import httpx2 as httpx
import pytest
from scenario_producer import definition, register_targets

from aiddos.api import chat_tool_runtime, scenario_persistence
from aiddos.api.chat_tool_runtime import schemas
from aiddos.api.scenarios import ScenarioInput

STATE = "/api/v1/chat/tools/scenarios/state"


def test_fresh_state_from_actual_app(client):
    response = client.get(STATE)
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 4,
        "scenario_revision": 0,
        "registry_write_status": "available",
    }


def files_at(path):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir() if p.is_file()}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message"}


def test_state_is_fresh_after_same_store_manual_save(client, state_path):
    store = client.app.state.chat.scenarios
    assert store is client.app.state.chat.worker.scenarios
    value = definition(register_targets(client))
    for revision in (0, 1, 2):
        before = files_at(state_path.parent)
        assert client.get(STATE).json() == {
            "schema_version": 4,
            "scenario_revision": revision,
            "registry_write_status": "available",
        }
        assert files_at(state_path.parent) == before
        if revision < 2:
            store.save(ScenarioInput(revision=revision, definition=value))


@pytest.mark.parametrize("fault", ["blocked", "receipt_corrupt"])
def test_quarantine_is_observed_without_recovery(client, state_path, monkeypatch, fault):
    store = client.app.state.chat.scenarios
    store.save(ScenarioInput(revision=0, definition=definition(register_targets(client))))
    if fault == "blocked":
        monkeypatch.setattr(store.coordinator, "blocked", True)
    else:
        # A readable registry with a bad admission receipt is quarantine, not
        # an unreadable registry (ScenarioStore._admission(observe=True)).
        store.receipt_path.write_bytes(b"not json")
    blocked_before = store.coordinator.blocked
    before = files_at(state_path.parent)
    response = client.get(STATE)
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 4,
        "scenario_revision": 1,
        "registry_write_status": "quarantined",
    }
    assert store.coordinator.blocked == blocked_before
    assert files_at(state_path.parent) == before


@pytest.mark.parametrize("fault", ["registry_corrupt", "unavailable"])
def test_unreadable_state_is_not_available(client, state_path, monkeypatch, fault):
    runtime = client.app.state.chat
    store = runtime.scenarios
    fired = []
    if fault == "registry_corrupt":
        store.path.write_bytes(b"not json")
    else:
        read_bytes = scenario_persistence.read_bytes

        def fail(path, *args, **kwargs):
            if path == store.receipt_path:
                fired.append(path)
                raise OSError("owned receipt unavailable")
            return read_bytes(path, *args, **kwargs)

        monkeypatch.setattr(scenario_persistence, "read_bytes", fail)
    before = files_at(state_path.parent)
    assert_error(client.get(STATE), 503, "CHAT_STORAGE_ERROR")
    if fault == "unavailable":
        assert fired == [store.receipt_path]
    assert not runtime.preparing and not runtime.worker.busy
    assert files_at(state_path.parent) == before


@pytest.mark.parametrize("invalid", [
    {"schema_version": True}, {"schema_version": 4.0}, {"schema_version": 3},
    {"scenario_revision": True}, {"scenario_revision": 1.0}, {"scenario_revision": "1"},
    {"scenario_revision": -1}, {"scenario_revision": 1001},
    {"registry_write_status": "ready"}, {"extra": "must not escape"},
])
def test_invalid_worker_output_cannot_be_success(client, monkeypatch, invalid):
    runtime = client.app.state.chat
    real = runtime.worker.scenario_state
    calls = []

    async def malformed(**kwargs):
        calls.append(kwargs)
        return {"schema_version": 4, "scenario_revision": 0,
                "registry_write_status": "available", **invalid}

    monkeypatch.setattr(runtime.worker, "scenario_state", malformed)
    assert_error(client.get(STATE), 503, "CHAT_STORAGE_ERROR")
    assert len(calls) == 1 and not runtime.preparing
    monkeypatch.setattr(runtime.worker, "scenario_state", real)
    assert client.get(STATE).status_code == 200


@pytest.mark.parametrize("method,suffix,status,code", [
    ("GET", "?revision=0", 422, "CHAT_INVALID_REQUEST"),
    ("GET", "?revision=0&revision=0", 422, "CHAT_INVALID_REQUEST"),
    ("GET", "?unknown", 422, "CHAT_INVALID_REQUEST"),
    ("GET", "?=", 422, "CHAT_INVALID_REQUEST"),
    ("POST", "", 405, "METHOD_NOT_ALLOWED"),
    ("POST", "", 415, "JSON_REQUIRED"),
])
def test_invalid_requests_never_admit_worker(client, monkeypatch, method, suffix, status, code):
    runtime = client.app.state.chat
    calls = []

    async def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("invalid request admitted worker")

    monkeypatch.setattr(runtime.worker, "scenario_state", forbidden)
    # Valid JSON framing reaches routing; absent framing is rejected earlier
    # by the unchanged DevelopmentBoundary, still without worker admission.
    kwargs = {"json": {}} if status == 405 else {}
    assert_error(client.request(method, STATE + suffix, **kwargs), status, code)
    assert calls == [] and runtime.worker._executor is None
    assert not runtime.preparing


@pytest.mark.parametrize("field,value,status,code", [
    ("active", "existing-turn", 429, "CHAT_BUSY"),
    ("preparing", True, 429, "CHAT_BUSY"),
    ("stopping", True, 503, "CHAT_SHUTTING_DOWN"),
    ("fenced", True, 503, "CHAT_COMMIT_UNCERTAIN"),
])
def test_owner_admission_guards(client, monkeypatch, field, value, status, code):
    runtime = client.app.state.chat
    owner = runtime.storage if field == "fenced" else runtime
    before = getattr(owner, field)
    monkeypatch.setattr(owner, field, value)
    try:
        assert_error(client.get(STATE), status, code)
        assert getattr(owner, field) == value
        assert runtime.worker._executor is None
    finally:
        monkeypatch.setattr(owner, field, before)
    assert client.get(STATE).status_code == 200


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("completion", ["normal", "timeout", "cancel"])
def test_pending_read_lease_and_native_retirement(client, monkeypatch, completion):
    runtime = client.app.state.chat
    entered, release = threading.Event(), threading.Event()
    inspect_state = runtime.scenarios.inspect_state
    calls = []

    def blocked():
        calls.append(True)
        entered.set()
        assert release.wait(5), "test did not release owned native read"
        return inspect_state()

    monkeypatch.setattr(runtime.scenarios, "inspect_state", blocked)
    monkeypatch.setattr(runtime, "turn_seconds", 0.2 if completion == "timeout" else 2)

    async def exercise():
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as http:
            pending = asyncio.create_task(http.get(STATE))
            try:
                await wait_until(entered.is_set)
                assert runtime.preparing and runtime.worker.busy
                for endpoint in (STATE, "/api/v1/chat/tools/runtime", "/api/v1/chat/runtime",
                                 "/api/v1/chat/tools/skills", "/api/v1/chat/tools/targets"):
                    assert_error(await http.get(endpoint), 429, "CHAT_BUSY")
                assert calls == [True]
                if completion == "cancel":
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                elif completion == "timeout":
                    assert_error(await asyncio.wait_for(pending, 2), 504, "CHAT_TIMEOUT")
                else:
                    release.set()
                    assert (await asyncio.wait_for(pending, 2)).status_code == 200
                assert not runtime.preparing
                if completion != "normal":
                    assert runtime.worker.busy
                    assert_error(await http.get(STATE), 429, "CHAT_BUSY")
                    assert_error(await http.get("/api/v1/chat/tools/runtime"), 429, "CHAT_BUSY")
                    assert calls == [True]
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await runtime.worker.settle()
                await wait_until(lambda: not runtime.worker.busy)
            monkeypatch.setattr(runtime.scenarios, "inspect_state", inspect_state)
            assert (await http.get(STATE)).status_code == 200
            assert (await http.get("/api/v1/chat/tools/runtime")).status_code == 200
            assert not runtime.preparing and not runtime.worker.busy

    client.portal.call(exercise)


def test_original_deadline_expires_while_waiting_owner_lock(client, monkeypatch):
    runtime = client.app.state.chat
    started = asyncio.Event()
    monotonic = chat_tool_runtime.monotonic

    def clock():
        started.set()
        return monotonic()

    monkeypatch.setattr(chat_tool_runtime, "monotonic", clock)
    monkeypatch.setattr(runtime, "turn_seconds", 0.01)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                    base_url="http://localhost") as http:
            async with runtime.lock:
                pending = asyncio.create_task(http.get(STATE))
                await asyncio.wait_for(started.wait(), 2)
                await asyncio.sleep(0.03)
                assert runtime.worker._executor is None
            assert_error(await asyncio.wait_for(pending, 2), 504, "CHAT_TIMEOUT")
            assert runtime.worker._executor is None
            assert not runtime.preparing and not runtime.worker.busy
            monkeypatch.setattr(runtime, "turn_seconds", 2)
            assert (await http.get(STATE)).status_code == 200

    client.portal.call(exercise)


def test_late_validation_cannot_publish_success(client, monkeypatch):
    runtime = client.app.state.chat
    model = chat_tool_runtime.ScenarioStateInspection
    validate = model.model_validate
    monotonic = chat_tool_runtime.monotonic
    validated = []

    def late(value):
        result = validate(value)
        validated.append(True)
        monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: monotonic() + 121)
        return result

    monkeypatch.setattr(model, "model_validate", late)
    assert_error(client.get(STATE), 504, "CHAT_TIMEOUT")
    assert validated == [True] and not runtime.preparing
    monkeypatch.setattr(model, "model_validate", validate)
    monkeypatch.setattr(chat_tool_runtime, "monotonic", monotonic)
    assert client.get(STATE).status_code == 200


def test_native_metadata_and_legacy_authority_remain_v1_to_v3(client):
    before = client.get("/api/v1/chat/tools/runtime")
    assert before.status_code == 200
    metadata = before.json()
    assert metadata["schema_version"] == 3
    assert metadata["tools"] == [
        "configuration_read", "agent_profile_update", "target_create", "skill_create",
    ]
    assert client.get(STATE).status_code == 200
    assert client.get("/api/v1/chat/tools/runtime").json() == metadata
    for version, scope, tool in [(1, None, "agent_profile_update"),
                                 (2, "target_create", "target_create"),
                                 (3, "skill_create", "skill_create")]:
        grant = {"schema_version": version, "scope": scope}
        assert [s["function"]["name"] for s in schemas(grant)] == ["configuration_read", tool]
    with pytest.raises(ValueError, match="Unknown authority"):
        schemas({"schema_version": 4, "scope": "scenario_write"})
    assert_error(client.post("/api/v1/chat/tool-grants", json={
        "schema_version": 4, "scope": "scenario_write",
    }), 422, "CHAT_INVALID_REQUEST")
