import stat
from uuid import uuid4

from fastapi.testclient import TestClient
from test_chat_runtime import configure

from aiddos.api.app import create_app


def start(client, **changes):
    runtime = client.get("/api/v1/chat/runtime").json()
    body = {
        "request_id": str(uuid4()),
        "settings_revision": runtime["settings_revision"],
        "profile_id": runtime["profile"]["id"],
        "approved_endpoint": runtime["profile"]["endpoint"],
        "locale": "ko",
    }
    body.update(changes)
    return client.post("/api/v1/chat/sessions", json=body), body


def test_session_consent_is_durable_idempotent_and_pinned(tmp_path):
    path = tmp_path / "draft.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        assert client.get("/api/v1/chat/sessions").json() == {"schema_version": 1, "sessions": []}
        assert list(tmp_path.iterdir()) == []
        configure(client)
        response, body = start(client)
        assert response.status_code == 201, response.text
        session = response.json()
        assert session["profile_id"] == "profile-local"
        assert session["sequence"] == 0 and session["active_turn_id"] is None
        repeated = client.post("/api/v1/chat/sessions", json=body)
        assert repeated.status_code == 200 and repeated.json() == session
        changed = client.post("/api/v1/chat/sessions", json={**body, "locale": "en"})
        assert changed.status_code == 409
        assert changed.json()["code"] == "CHAT_IDEMPOTENCY_CONFLICT"
        wrong, _ = start(client, settings_revision=0)
        assert wrong.status_code == 409 and wrong.json()["code"] == "CHAT_BINDING_CHANGED"
    db = tmp_path / "draft.chat.sqlite3"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        assert client.get("/api/v1/chat/sessions").json()["sessions"] == [session]
        assert client.get(f"/api/v1/chat/sessions/{session['id']}").json() == {
            "schema_version": 1,
            "session": session,
            "turns": [],
            "next_before_sequence": None,
        }
