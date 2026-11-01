"""Public variant discovery must not replace legacy validation/replay errors."""

from uuid import uuid4

import pytest

from aiddos.api.errors import DraftError


def decision():
    return {"request_id": str(uuid4()), "proposal_digest": "a" * 64, "decision": "approve"}


@pytest.mark.parametrize(
    "change",
    [{"decision": "unknown"}, {"proposal_digest": "short"}, {"request_id": 4}],
)
def test_missing_call_does_not_hide_invalid_decision_body(client, change):
    response = client.post(
        f"/api/v1/chat/tool-calls/{uuid4()}/decision", json=decision() | change
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CHAT_INVALID_REQUEST"


def test_missing_call_without_prior_decision_remains_not_found(client, state_path):
    assert not state_path.with_suffix(".chat.sqlite3").exists()
    response = client.post(f"/api/v1/chat/tool-calls/{uuid4()}/decision", json=decision())
    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"
    assert not state_path.with_suffix(".chat.sqlite3").exists()


def test_decision_discovery_does_not_hide_storage_errors(client, monkeypatch):
    def unavailable(call_id):
        raise DraftError("CHAT_STORAGE_ERROR")

    monkeypatch.setattr(client.app.state.chat.ledger, "call", unavailable)
    response = client.post(f"/api/v1/chat/tool-calls/{uuid4()}/decision", json=decision())
    assert response.status_code == 503
    assert response.json()["code"] == "CHAT_STORAGE_ERROR"


def test_missing_grant_does_not_hide_missing_session(client):
    response = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/tool-turns",
        json={
            "request_id": str(uuid4()), "expected_sequence": 0,
            "text": "No authority", "grant_id": str(uuid4()),
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "CHAT_NOT_FOUND"
