"""Execution denial precedes JSON grammar, after bounded transport admission."""

import socket

import pytest
from fastapi.testclient import TestClient

from aiddos.api.app import create_app
from aiddos.api.store import DraftStore


@pytest.mark.parametrize(
    "route,code",
    [
        ("/api/v1/ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"),
        ("/api/v1/ai-settings/models", "AI_CONNECTION_NOT_AVAILABLE"),
        ("/api/v1/runs", "LIVE_NOT_AVAILABLE"),
        ("/api/v1/agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
    ],
)
@pytest.mark.parametrize("body", [b"", b"not-json", b"\xff", b'{"x":1,"x":2}'])
def test_unconditional_denial_precedes_json_validation(tmp_path, monkeypatch, route, code, body):
    path = tmp_path / "corrupt.json"
    raw = b"broken storage"
    path.write_bytes(raw)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("A denial must not touch storage/network/DNS")

    monkeypatch.setattr(DraftStore, "_read", forbidden)
    monkeypatch.setattr(DraftStore, "_write", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with TestClient(
        create_app(state_path=path),
        base_url="http://localhost",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(route, content=body, headers={"Content-Type": "application/json"})
    assert calls == []
    assert path.read_bytes() == raw
    assert response.status_code == 409
    assert response.json()["code"] == code
