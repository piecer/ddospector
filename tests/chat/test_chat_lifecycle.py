import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app


def test_cancel_waits_for_cleanup_and_never_reuses_active_slot(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def transport(*args):
        calls.append(args)
        entered.set()
        try:
            yield "partial"
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await asyncio.wait_for(release.wait(), timeout=2)

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        result, body = submit(client, session)
        assert result.status_code == 202
        turn = result.json()
        client.portal.call(entered.wait)
        cancel = client.post(f"/api/v1/chat/turns/{turn['id']}/cancel", json={})
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancel_requested"
        client.portal.call(cleanup.wait)
        repeated = client.post(f"/api/v1/chat/turns/{turn['id']}/cancel", json={})
        assert repeated.json()["revision"] == cancel.json()["revision"]
        duplicate = client.post(f"/api/v1/chat/sessions/{session['id']}/turns", json=body)
        assert duplicate.status_code == 200
        busy, _ = submit(client, session, expected_sequence=1)
        assert busy.status_code == 429
        client.portal.call(release.set)
        final = settled(client, app, turn)
        assert final["status"] == "cancelled"
        assert final["assistant_text"] == "partial"
        assert final["provider_stop"] == "unknown" and final["transport"] == "closed"
        late = client.post(f"/api/v1/chat/turns/{turn['id']}/cancel", json={})
        assert late.json() == final
        assert len(calls) == 1


def test_total_deadline_includes_local_dispatch_preparation(tmp_path, monkeypatch):
    import time

    app = create_app(state_path=tmp_path / "draft.json")
    calls = []

    async def transport(*args):
        calls.append(1)
        yield "should not dispatch"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        runtime = app.state.chat
        original = runtime.context

        def slow_context(*args):
            # An explicit deterministic expiry fault, not a scheduling race workaround.
            time.sleep(0.03)
            return original(*args)

        runtime.turn_seconds = 0.01
        monkeypatch.setattr(runtime, "context", slow_context)
        result, _ = submit(client, session)
        final = settled(client, app, result.json())
        assert final["status"] == "failed" and final["error_code"] == "CHAT_TIMEOUT"
        assert final["provider_stop"] == "not_dispatched" and final["transport"] == "not_started"
        assert calls == []


def test_pre_dispatch_cancel_sends_nothing(tmp_path):
    from aiddos.api.chat_models import TurnInput

    app = create_app(state_path=tmp_path / "draft.json")
    calls = []

    async def transport(*args):
        calls.append(1)
        yield "unexpected"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()

        async def cancel_before_scheduling():
            runtime = app.state.chat
            turn, _ = await runtime.accept(
                session["id"], TurnInput(request_id=str(uuid4()), expected_sequence=0, text="hello")
            )
            cancellation = await runtime.cancel(turn["id"])
            assert cancellation["status"] == "cancel_requested"
            await asyncio.wait_for(asyncio.shield(runtime.task), 5)
            return turn

        turn = client.portal.call(cancel_before_scheduling)
        final = client.get(f"/api/v1/chat/turns/{turn['id']}").json()
        assert final["status"] == "cancelled"
        assert final["transport"] == "not_started" and final["provider_stop"] == "not_dispatched"
        assert calls == []


def test_expired_provider_cleanup_never_claims_success(tmp_path):
    import time

    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        yield "partial"
        time.sleep(1.1)

    app.state.chat.transport = transport
    app.state.chat.turn_seconds = 1
    with TestClient(app, base_url="http://localhost") as client:
        configure(client, streaming=False)
        turn = settled(client, app, submit(client, start(client)[0].json())[0].json())
        assert turn["status"] == "failed" and turn["error_code"] == "CHAT_TIMEOUT"
        assert turn["assistant_text"] == "partial"


def test_cancel_during_final_publication_settles_durably(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    runtime = app.state.chat
    finished, finalizing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class PublicationBarrier(asyncio.Lock):
        async def acquire(self):
            if asyncio.current_task() is runtime.task and finished.is_set():
                finalizing.set()
                await asyncio.wait_for(release.wait(), 2)
            return await super().acquire()

    runtime.lock = PublicationBarrier()

    async def transport(*args):
        yield "partial"
        finished.set()

    runtime.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        turn = submit(client, start(client)[0].json())[0].json()
        client.portal.call(finalizing.wait)
        cancellation = client.post(f"/api/v1/chat/turns/{turn['id']}/cancel", json={})
        assert cancellation.status_code == 200
        client.portal.call(release.set)
        final = settled(client, app, turn)
        assert final["status"] == "cancelled" and final["assistant_text"] == "partial"
        assert runtime.active is None


def test_partial_publication_failure_stops_owned_transport(tmp_path, monkeypatch):
    from aiddos.api.errors import DraftError

    app = create_app(state_path=tmp_path / "draft.json")
    runtime = app.state.chat
    closed = asyncio.Event()
    faults = []

    async def transport(*args):
        try:
            yield "short pending text"
            await asyncio.Event().wait()
        finally:
            closed.set()

    runtime.transport = transport
    original = runtime.storage.update_turn

    def fail_partial(turn):
        if turn["assistant_text"]:
            faults.append(1)
            runtime.storage.fenced = True
            raise DraftError("CHAT_COMMIT_UNCERTAIN")
        return original(turn)

    monkeypatch.setattr(runtime.storage, "update_turn", fail_partial)
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        turn = submit(client, start(client)[0].json())[0].json()

        async def wait_closed():
            await asyncio.wait_for(closed.wait(), 1.5)
            await asyncio.wait_for(asyncio.shield(runtime.task), 1)

        client.portal.call(wait_closed)
        assert faults == [1]
        assert client.get(f"/api/v1/chat/turns/{turn['id']}").status_code == 503
        assert runtime.active is None


def test_global_request_identity_includes_session(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        yield "ok"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        first, second = start(client)[0].json(), start(client)[0].json()
        request_id = str(uuid4())
        one, _ = submit(client, first, request_id=request_id)
        settled(client, app, one.json())
        two, _ = submit(client, second, request_id=request_id)
        assert two.status_code == 409
        assert two.json()["code"] == "CHAT_IDEMPOTENCY_CONFLICT"
