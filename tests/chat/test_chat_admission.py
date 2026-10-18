import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app


def test_chat_body_limit_is_preframework_and_legacy_denials_stay_unconditional(tmp_path):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        result = client.post(
            "/api/v1/chat/sessions",
            content=b"x" * 32769,
            headers={"Content-Type": "application/json"},
        )
        assert result.status_code == 413
        assert result.json()["code"] == "CHAT_BODY_TOO_LARGE"
        for path, code in [
            ("runs", "LIVE_NOT_AVAILABLE"),
            ("agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
            ("ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"),
            ("ai-settings/models", "AI_CONNECTION_NOT_AVAILABLE"),
        ]:
            result = client.post(
                "/api/v1/" + path, content=b"not json", headers={"Content-Type": "application/json"}
            )
            assert result.status_code == 409 and result.json()["code"] == code
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ["", " \n\t", "x\x00", "\ud800", "😀" * 2049])
def test_invalid_user_text_never_dispatches(tmp_path, text):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        configure(client)
        session = start(client)[0].json()
        raw = json.dumps({"request_id": str(uuid4()), "expected_sequence": 0, "text": text})
        result = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert result.status_code == 422
        assert client.get(f"/api/v1/chat/sessions/{session['id']}").json()["turns"] == []


@pytest.mark.parametrize(
    "query",
    [
        "foo=1",
        "before_sequence=0",
        "before_sequence=1&before_sequence=2",
        "before_sequence=9007199254740992",
        "before_sequence=true",
    ],
)
def test_history_query_is_closed(tmp_path, query):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        configure(client)
        session = start(client)[0].json()
        result = client.get(f"/api/v1/chat/sessions/{session['id']}?{query}")
        assert result.status_code == 422


def test_session_replay_survives_settings_change_and_new_turn_requires_pinned_snapshot(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        yield "ok"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        result, body = start(client)
        session = result.json()
        turn = settled(client, app, submit(client, session)[0].json())
        configure(client, thinking_type="disabled")
        replay = client.post("/api/v1/chat/sessions", json=body)
        assert replay.status_code == 200 and replay.json()["id"] == session["id"]
        denied, _ = submit(client, session, expected_sequence=1)
        assert denied.status_code == 409 and denied.json()["code"] == "CHAT_BINDING_CHANGED"
        assert client.get(f"/api/v1/chat/turns/{turn['id']}").json() == turn
