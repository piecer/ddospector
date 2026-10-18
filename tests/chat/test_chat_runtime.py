import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app


def configure(client, **changes):
    profile = {
        "id": "profile-local",
        "name": "Local",
        "format": "openai",
        "model": "fixture-model",
        "base_url": "http://localhost:12345/v1",
        "credential_env": "",
        "rate_per_second": 0,
        "rate_per_minute": 0,
        "context_window_k": 0,
        "streaming": True,
        "max_tokens": 0,
        "max_tokens_field": "",
        "thinking_type": "",
        "reasoning_effort": "",
        "retry": {
            key: {"attempts": -1, "interval_ms": 0} for key in ("connect", "empty", "stream")
        },
    }
    profile.update(changes)
    old = client.get("/api/v1/ai-settings").json()
    response = client.put(
        "/api/v1/ai-settings",
        json={
            "revision": old["revision"],
            "profiles": [profile],
            "default_profile_id": profile["id"],
            "agent_profile_id": None,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({}, None),
        ({"base_url": "https://localhost:12345/v1"}, "CHAT_UNSUPPORTED_PROFILE"),
        ({"base_url": "http://example.com/v1"}, "CHAT_UNSUPPORTED_PROFILE"),
        ({"credential_env": "DO_NOT_LOOK_UP"}, "CHAT_UNSUPPORTED_PROFILE"),
        ({"format": "anthropic"}, "CHAT_UNSUPPORTED_PROFILE"),
        ({"thinking_type": "disabled"}, "CHAT_UNSUPPORTED_OPTIONS"),
        ({"max_tokens": 4097}, "CHAT_UNSUPPORTED_OPTIONS"),
        ({"rate_per_second": 1}, "CHAT_UNSUPPORTED_OPTIONS"),
    ],
)
def test_profile_metadata_preserves_ai_identifier(tmp_path, changes, reason):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as client:
        settings = configure(client, **changes)
        response = client.get("/api/v1/chat/runtime")
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] == reason
        assert data["supported"] is (reason is None)
        assert data["settings_revision"] == settings["revision"]
        if reason is None:
            assert data["profile"] == {
                "id": "profile-local",
                "name": "Local",
                "model": "fixture-model",
                "format": "openai",
                "endpoint": "http://localhost:12345/v1/chat/completions",
                "streaming": True,
            }
        else:
            assert data["profile"] is None
    assert not list(tmp_path.glob("*.sqlite3*"))


def test_runtime_is_public_and_lazy(tmp_path):
    path = tmp_path / "draft.json"
    with TestClient(create_app(state_path=path), base_url="http://localhost") as client:
        result = client.get("/api/v1/chat/runtime")
        assert result.status_code == 200
        assert result.json() == {
            "schema_version": 1,
            "mode": "chat_only",
            "supported": False,
            "reason": "CHAT_NOT_CONFIGURED",
            "settings_revision": 0,
            "profile": None,
            "limits": {
                "input_bytes": 8192,
                "output_bytes": 65536,
                "sessions": 32,
                "session_turns": 64,
                "history_bytes": 8388608,
                "turn_seconds": 120,
            },
            "history": "persistent",
            "configuration_tools": False,
            "live_execution": False,
            "mcp_execution": False,
        }
    assert list(tmp_path.iterdir()) == []
