from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app
from aiddos.api.errors import DraftError


def test_session_and_turn_quotas_preserve_all_history(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        yield "ok"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        sessions = []
        for _ in range(32):
            response, _ = start(client)
            assert response.status_code == 201
            sessions.append(response.json())
        refused, _ = start(client)
        assert refused.status_code == 409 and refused.json()["code"] == "CHAT_RETENTION_FULL"
        assert len(client.get("/api/v1/chat/sessions").json()["sessions"]) == 32
        for sequence in range(64):
            response, _ = submit(client, sessions[0], expected_sequence=sequence)
            assert response.status_code == 202
            assert settled(client, app, response.json())["status"] == "succeeded"
        refused, _ = submit(client, sessions[0], expected_sequence=64)
        assert refused.status_code == 409 and refused.json()["code"] == "CHAT_RETENTION_FULL"
        before, found = None, []
        while True:
            suffix = "" if before is None else f"?before_sequence={before}"
            page = client.get(f"/api/v1/chat/sessions/{sessions[0]['id']}{suffix}").json()
            assert len(page["turns"]) <= 2
            found.extend(t["sequence"] for t in page["turns"])
            before = page["next_before_sequence"]
            if before is None:
                break
        assert sorted(found) == list(range(1, 65))


def test_context_overflow_refuses_without_dispatch_or_silent_truncation(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    calls = []

    async def transport(*args):
        calls.append(1)
        yield "x" * 65536

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client, streaming=False)
        session = start(client)[0].json()
        for sequence in range(2):
            turn = settled(
                client, app, submit(client, session, expected_sequence=sequence)[0].json()
            )
            assert turn["status"] == "succeeded"
        denied, _ = submit(client, session, expected_sequence=2)
        assert denied.status_code == 409 and denied.json()["code"] == "CHAT_CONTEXT_LIMIT"
        assert calls == [1, 1]
        assert (
            client.get(f"/api/v1/chat/sessions/{session['id']}").json()["session"]["sequence"] == 2
        )


def test_real_retained_text_cap_refuses_without_eviction(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        yield "x" * 65536
        raise DraftError("CHAT_PROVIDER_PROTOCOL")

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client, streaming=False)
        sessions = [start(client)[0].json() for _ in range(2)]
        count = 0
        for session in sessions:
            for sequence in range(64):
                response, _ = submit(client, session, text="x", expected_sequence=sequence)
                if response.status_code == 409:
                    assert response.json()["code"] == "CHAT_RETENTION_FULL"
                    break
                assert response.status_code == 202
                turn = settled(client, app, response.json())
                assert turn["status"] == "failed"
                assert len(turn["assistant_text"]) == 65536
                count += 1
        assert count == 127
        assert client.portal.call(app.state.chat.storage.text_bytes) == 127 * 65537
        first = client.get(f"/api/v1/chat/sessions/{sessions[0]['id']}?before_sequence=2").json()
        assert first["turns"][0]["assistant_text"] == "x" * 65536
    assert (tmp_path / "draft.chat.sqlite3").stat().st_size <= 16 * 1024 * 1024
