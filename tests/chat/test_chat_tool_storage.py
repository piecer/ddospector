"""Component ledger tests use real SQLite, never HTTP/model/domain mocks."""

from uuid import uuid4

import pytest

from aiddos.api.chat_models import now
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.errors import DraftError

STAMP = "2026-01-01T00:00:00+00:00"


def uid():
    return str(uuid4())


def setup_store(tmp_path):
    storage = ChatStorage(tmp_path / "draft.json")
    storage.open(create=True)
    profile = dict(
        id="p",
        name="Local",
        format="openai",
        model="fixture",
        base_url="http://localhost:12345/v1",
        credential_env="",
        rate_per_second=0,
        rate_per_minute=0,
        context_window_k=0,
        streaming=True,
        max_tokens=0,
        max_tokens_field="",
        thinking_type="",
        reasoning_effort="",
        retry={key: dict(attempts=-1, interval_ms=0) for key in ("connect", "empty", "stream")},
    )
    consent = dict(
        request_id=uid(),
        settings_revision=0,
        profile_id="p",
        approved_endpoint="http://localhost:12345/v1/chat/completions",
        locale="en",
    )
    session = dict(
        schema_version=1,
        id=uid(),
        request_id=consent["request_id"],
        settings_revision=0,
        profile_id="p",
        model="fixture",
        endpoint=consent["approved_endpoint"],
        streaming=True,
        locale="en",
        created_at=STAMP,
        sequence=0,
        active_turn_id=None,
    )
    storage.add_session(session, profile, consent)
    return storage, session


def admission(session, request_id=None):
    request_id = request_id or uid()
    body = dict(
        session_id=session["id"],
        request_id=request_id,
        expected_sequence=session["sequence"],
        text="hello 한😀",
    )
    turn = dict(
        schema_version=1,
        id=uid(),
        session_id=session["id"],
        request_id=request_id,
        sequence=session["sequence"] + 1,
        revision=1,
        status="accepted",
        user_text=body["text"],
        assistant_text="",
        error_code=None,
        transport="not_started",
        provider_stop="not_dispatched",
        created_at=STAMP,
        finished_at=None,
    )
    return session | dict(sequence=turn["sequence"], active_turn_id=turn["id"]), turn, body


def grant_body(session, commitment):
    return dict(
        request_id=uid(),
        session_id=session["id"],
        turn_request_id=commitment["request_id"],
        expected_sequence=commitment["expected_sequence"],
        text=commitment["text"],
    )


def test_grant_turn_binding_replays_and_cross_route_conflicts(tmp_path):
    from aiddos.api.chat_tool_storage import ToolLedger

    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant_input = grant_body(session, body)
    try:
        grant, replay = ledger.create_grant(grant_input, timestamp=STAMP)
        assert not replay and grant["status"] == "pending"
        assert ledger.create_grant(grant_input, timestamp=now()) == (grant, True)
        assert ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP) == (turn, False)
        assert ledger.grant(grant["id"])["status"] == "consumed"
        assert ledger.admit(grant["id"], updated, turn, body, timestamp=now()) == (turn, True)
        assert ledger.transcript(turn["id"])["calls"] == []
        assert ledger.reservation(turn["id"])["remaining"] < 1048576
        with pytest.raises(DraftError) as error:
            storage.replay("turns", body["request_id"], body)
        assert error.value.code == "CHAT_IDEMPOTENCY_CONFLICT"
        with pytest.raises(DraftError) as error:
            ledger.create_grant(grant_input | {"text": "changed"}, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_GRANT_CONFLICT"
        storage.validate()
    finally:
        storage.close()


def test_grant_binding_is_atomic_when_insert_fails(tmp_path):
    from aiddos.api.chat_tool_storage import ToolLedger

    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
    fired = []
    storage.db.create_function("fault", 0, lambda: fired.append(True) or 1)
    storage.db.execute(
        "CREATE TEMP TRIGGER fail_binding BEFORE INSERT ON tool_bindings "
        "BEGIN SELECT fault(); SELECT RAISE(ABORT, 'fault'); END"
    )
    try:
        with pytest.raises(DraftError) as error:
            ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
        assert error.value.code == "CHAT_COMMIT_UNCERTAIN" and fired == [True]
        assert not storage.db.in_transaction
        assert storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)
        import json

        raw = json.loads(storage.db.execute("SELECT data FROM tool_grants").fetchone()[0])
        assert raw["status"] == "pending"
        assert storage.db.execute("SELECT count(*) FROM tool_reservations").fetchone() == (0,)
    finally:
        storage.close()
