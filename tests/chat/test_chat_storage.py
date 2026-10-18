import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app


@pytest.mark.parametrize("dispatched", [False, True])
@pytest.mark.parametrize("read_route", ["sessions", "history", "turn", "request", "events"])
def test_read_recovery_interrupts_once_and_preserves_dispatch_truth(
    tmp_path, dispatched, read_route
):
    path = tmp_path / "draft.json"
    app = create_app(state_path=path)

    async def transport(*args):
        yield "committed partial"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        turn = settled(client, app, submit(client, session)[0].json())
    db = tmp_path / "draft.chat.sqlite3"
    # A crash image: only committed bytes, never an invented durable terminal.
    turn.update(
        status="running" if dispatched else "accepted",
        error_code=None,
        finished_at=None,
        transport="open" if dispatched else "not_started",
        provider_stop="unknown" if dispatched else "not_dispatched",
    )
    session.update(sequence=1, active_turn_id=turn["id"])
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE turns SET data=?", (json.dumps(turn),))
        connection.execute("UPDATE sessions SET data=?", (json.dumps(session),))
    raw = db.read_bytes()
    app2 = create_app(state_path=path)
    with TestClient(app2, base_url="http://localhost") as client:
        assert client.get("/api/v1/chat/runtime").status_code == 200
        assert db.read_bytes() == raw
        routes = {
            "sessions": "/api/v1/chat/sessions",
            "history": f"/api/v1/chat/sessions/{session['id']}",
            "turn": f"/api/v1/chat/turns/{turn['id']}",
            "request": f"/api/v1/chat/turns/by-request/{turn['request_id']}",
            "events": f"/api/v1/chat/turns/{turn['id']}/events",
        }
        if read_route == "events":

            async def read_events():
                async with (
                    asyncio.timeout(2),
                    httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app=app2), base_url="http://localhost"
                    ) as observer,
                ):
                    return await observer.get(routes[read_route])

            response = client.portal.call(read_events)
        else:
            response = client.get(routes[read_route])
        recovered = client.get(f"/api/v1/chat/turns/{turn['id']}").json()
        assert recovered["status"] == "interrupted"
        assert recovered["error_code"] == "CHAT_INTERRUPTED"
        assert recovered["assistant_text"] == turn["assistant_text"]
        assert recovered["revision"] == turn["revision"] + 1
        assert recovered["transport"] == ("unknown" if dispatched else "not_started")
        assert recovered["provider_stop"] == turn["provider_stop"]
        assert response.status_code == 200
        assert client.get(f"/api/v1/chat/turns/{turn['id']}").json() == recovered
        assert (
            client.get(f"/api/v1/chat/sessions/{session['id']}").json()["session"]["active_turn_id"]
            is None
        )


def test_missing_reads_and_competing_owner_never_recover_foreign_state(tmp_path):
    path = tmp_path / "draft.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as first:
        for route in (
            "sessions",
            f"sessions/{uuid4()}",
            f"turns/{uuid4()}",
            f"turns/by-request/{uuid4()}",
            f"turns/{uuid4()}/events",
        ):
            assert first.get("/api/v1/chat/" + route).status_code in (200, 404)
        assert list(tmp_path.iterdir()) == []
        configure(first)
        start(first)
        with TestClient(create_app(state_path=path), base_url="http://localhost") as second:
            result = second.get("/api/v1/chat/sessions")
            assert result.status_code == 503
            assert result.json()["code"] == "CHAT_STORAGE_ERROR"
            assert second.get("/api/v1/chat/runtime").status_code == 200


def test_terminal_commit_failure_fences_reads_admission_and_reopens_truthfully(tmp_path):
    import asyncio

    path = tmp_path / "draft.json"
    app = create_app(state_path=path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    faults = []

    async def transport(*args):
        calls.append(1)
        yield "durable" * 100
        entered.set()
        await release.wait()

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        accepted = submit(client, session)[0].json()
        client.portal.call(entered.wait)

        class BrokenCommit:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, key):
                return getattr(self.connection, key)

            def commit(self):
                faults.append(1)
                raise sqlite3.OperationalError("PRIVATE STORAGE FAILURE")

        def inject():
            storage = app.state.chat.storage
            storage.db = BrokenCommit(storage.db)
            release.set()

        client.portal.call(inject)

        async def wait():
            await asyncio.wait_for(asyncio.shield(app.state.chat.task), 5)

        client.portal.call(wait)
        result = client.get(f"/api/v1/chat/turns/{accepted['id']}")
        assert result.status_code == 503, result.text
        assert result.json()["code"] == "CHAT_COMMIT_UNCERTAIN"
        assert "PRIVATE" not in result.text
        refused, _ = submit(client, session, expected_sequence=1)
        assert refused.status_code == 503
        assert faults == [1] and calls == [1]
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        recovered = client.get(f"/api/v1/chat/turns/{accepted['id']}").json()
        assert recovered["status"] == "interrupted"
        assert recovered["assistant_text"] == "durable" * 100
        assert recovered["transport"] == "unknown" and recovered["provider_stop"] == "unknown"


@pytest.mark.parametrize("mutation", ["revision", "extra", "unicode", "duplicate", "status"])
def test_supported_schema_with_invalid_record_fails_closed(tmp_path, mutation):
    path = tmp_path / "draft.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
    db = tmp_path / "draft.chat.sqlite3"
    if mutation == "revision":
        session["settings_revision"] = 9007199254740992
    elif mutation == "extra":
        session["secret"] = "PRIVATE"
    elif mutation == "unicode":
        session["model"] = "\ud800"
    elif mutation == "status":
        session["sequence"] = -1
    raw = json.dumps(session)
    if mutation == "duplicate":
        raw = raw[:-1] + ', "locale":"en"}'
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE sessions SET data=?", (raw,))
    before = db.read_bytes()
    with TestClient(
        create_app(state_path=path), base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        result = client.get("/api/v1/chat/sessions")
        assert result.status_code == 503, result.text
        assert result.json()["code"] == "CHAT_STORAGE_ERROR"
        assert "PRIVATE" not in result.text
    assert db.read_bytes() == before


@pytest.mark.parametrize("kind", ["bytes", "schema", "symlink", "directory"])
def test_invalid_storage_preserves_existing_bytes(tmp_path, kind):
    path = tmp_path / "draft.chat.sqlite3"
    if kind == "schema":
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE unrelated (data TEXT)")
    elif kind == "symlink":
        target = tmp_path / "caller"
        target.write_bytes(b"caller")
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"not sqlite")
    before = path.read_bytes() if not path.is_dir() else None
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        result = client.get("/api/v1/chat/sessions")
        assert result.status_code == 503
        assert result.json()["code"] == "CHAT_STORAGE_ERROR"
    if before is not None:
        assert path.read_bytes() == before
