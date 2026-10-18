"""Persistent B1 regressions: storage uncertainty is not producer ownership."""

import asyncio
import json
import sqlite3
from contextlib import suppress
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from provider_fixture import ProviderFixture, Scenario, sse
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app
from aiddos.api.chat_models import TurnInput
from aiddos.api.chat_transport import receive_text
from aiddos.api.errors import DraftError


class ConnectionProxy:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.mark.parametrize("phase", ["terminal", "final-flush", "live-flush", "ticker"])
def test_final_read_fault_fences_without_inventing_terminal(tmp_path, phase):
    streaming = phase != "terminal"
    live = phase in {"live-flush", "ticker"}
    text = "pending text" * (32 if phase == "live-flush" else 1)
    raw = (
        sse(text) + sse(finish="stop") + b"data: [DONE]\n\n"
        if streaming
        else json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()
    )
    scenario = Scenario(
        (raw,), content_type="text/event-stream" if streaming else "application/json"
    )
    if live:
        scenario = Scenario((sse(text), sse(finish="stop")), (0, 10))
    path = tmp_path / "draft.json"
    with ProviderFixture([scenario]) as provider:
        app = create_app(state_path=path)
        runtime = app.state.chat
        assert runtime.transport is receive_text
        faults = []
        with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
            configure(client, base_url=provider.base_url, streaming=streaming)
            session = start(client)[0].json()

            class ReadFault(ConnectionProxy):
                def execute(self, sql, *args):
                    ready = bool(provider.requests) if live else runtime.finalizing
                    if ready and not faults and sql == "SELECT data FROM turns WHERE id=?":
                        faults.append(sql)
                        raise sqlite3.OperationalError("private read failure")
                    return self.connection.execute(sql, *args)

            async def admit_and_observe():
                runtime.storage.db = ReadFault(runtime.storage.db)
                turn, status = await runtime.accept(
                    session["id"],
                    TurnInput(request_id=str(uuid4()), expected_sequence=0, text="hello"),
                )
                assert status == 202
                observer = await runtime.subscribe(turn["id"], 0)
                return turn, observer

            turn, observer = client.portal.call(admit_and_observe)

            async def wait():
                # Preserve a real RED at the public admission assertion, like the reviewer.
                with suppress(sqlite3.Error):
                    await asyncio.wait_for(asyncio.shield(runtime.task), 3)

            client.portal.call(wait)
            provider.wait_closed()
            second = submit(client, session, expected_sequence=1)[0]
            if second.status_code == 202:
                settled(client, app, second.json())
            assert faults == ["SELECT data FROM turns WHERE id=?"]
            assert second.status_code == 503, second.text
            assert second.json()["code"] == "CHAT_COMMIT_UNCERTAIN"
            assert runtime.active is None and runtime.storage.fenced
            assert observer.closed
            assert len(provider.requests) == 1 and provider.opened == provider.closed
            response = client.get(f"/api/v1/chat/turns/{turn['id']}")
            assert response.status_code == 503
            with sqlite3.connect(tmp_path / "draft.chat.sqlite3") as db:
                durable = json.loads(db.execute("SELECT data FROM turns").fetchone()[0])
                saved = json.loads(db.execute("SELECT data FROM sessions").fetchone()[0])
            assert durable["status"] == "running" and durable["finished_at"] is None
            assert durable["assistant_text"] == ""
            assert saved["active_turn_id"] == turn["id"]
        with TestClient(create_app(state_path=path), base_url="http://localhost") as restarted:
            recovered = restarted.get(f"/api/v1/chat/turns/{turn['id']}").json()
            assert recovered["status"] == "interrupted"
            assert recovered["error_code"] == "CHAT_INTERRUPTED"
            assert recovered["revision"] == durable["revision"] + 1
            assert recovered["assistant_text"] == durable["assistant_text"]
            assert recovered["transport"] == recovered["provider_stop"] == "unknown"
            assert (
                restarted.get(f"/api/v1/chat/sessions/{session['id']}").json()["session"][
                    "active_turn_id"
                ]
                is None
            )
        assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "operation", ["sessions", "session", "turn", "request", "turns", "replay", "text_bytes"]
)
@pytest.mark.parametrize("phase", ["execute", "fetch"])
def test_sibling_reads_map_io_failure_and_fence(tmp_path, operation, phase):
    app = create_app(state_path=tmp_path / "draft.json")
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session, commitment = start(client)
        session = session.json()
        storage = app.state.chat.storage
        faults = []

        def fail():
            faults.append(phase)
            raise sqlite3.OperationalError("private disk error")

        class CursorFault:
            def fetchone(self):
                fail()

            def __iter__(self):
                fail()

        class ReadFault(ConnectionProxy):
            def execute(self, sql, *args):
                if sql.startswith("SELECT"):
                    if phase == "execute":
                        fail()
                    return CursorFault()
                return self.connection.execute(sql, *args)

        def check():
            storage.db = ReadFault(storage.db)
            calls = {
                "sessions": lambda: storage.sessions(),
                "session": lambda: storage.session(session["id"]),
                "turn": lambda: storage.turn(str(uuid4())),
                "request": lambda: storage.turn(str(uuid4()), by_request=True),
                "turns": lambda: storage.turns(session["id"]),
                "replay": lambda: storage.replay("sessions", session["request_id"], commitment),
                "text_bytes": lambda: storage.text_bytes(),
            }
            with pytest.raises(DraftError) as error:
                calls[operation]()
            assert error.value.code == "CHAT_COMMIT_UNCERTAIN"
            assert faults == [phase] and storage.fenced
            for call in calls.values():
                with pytest.raises(DraftError) as refused:
                    call()
                assert refused.value.code == "CHAT_COMMIT_UNCERTAIN"
            assert faults == [phase], "fenced readers must not touch SQLite again"

        client.portal.call(check)
        refused = submit(client, session)[0]
        assert refused.status_code == 503


@pytest.mark.parametrize("primary", ["draft", "sqlite", "programming"])
def test_rollback_failure_never_masks_primary_and_fences(tmp_path, primary):
    app = create_app(state_path=tmp_path / "draft.json")
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        start(client)
        storage = app.state.chat.storage
        faults = []

        class RollbackFault(ConnectionProxy):
            def rollback(self):
                faults.append(1)
                raise sqlite3.OperationalError("private rollback error")

        def check():
            storage.db = RollbackFault(storage.db)
            original = {
                "draft": DraftError("CHAT_RETENTION_FULL"),
                "sqlite": sqlite3.OperationalError("private write error"),
                "programming": ValueError("programming defect"),
            }[primary]
            with (
                pytest.raises(DraftError if primary != "programming" else ValueError) as error,
                storage.transaction(),
            ):
                raise original
            if primary == "sqlite":
                assert error.value.code == "CHAT_COMMIT_UNCERTAIN"
            else:
                assert error.value is original
            assert faults == [1] and storage.fenced

        client.portal.call(check)
