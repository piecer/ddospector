"""Admission identity, closed projection and schema graph negative controls."""

import sqlite3

import pytest
from test_chat_tool_storage import STAMP, admission, grant_body, setup_store, uid
from test_chat_tool_storage_intents import prepared
from test_chat_tool_storage_limits import decision

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import proposal_digest
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError


@pytest.mark.parametrize(
    "field,value", [("text", "changed"), ("expected_sequence", 1), ("request_id", "fresh")]
)
def test_grant_mismatched_admission_has_zero_writes(tmp_path, field, value):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
    body[field] = uid() if value == "fresh" else value
    try:
        before = ledger.usage()
        with pytest.raises(DraftError) as error:
            ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_GRANT_INVALID"
        assert ledger.usage() == before and ledger.grant(grant["id"])["status"] == "pending"
        assert storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)
    finally:
        storage.close()


def test_text_route_request_cannot_replay_as_tool_turn(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    storage.add_turn(updated, turn, body)
    try:
        with pytest.raises(DraftError) as error:
            ledger.admit(uid(), updated, turn, body, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_GRANT_CONFLICT"
        assert storage.replay("turns", body["request_id"], body) == turn
    finally:
        storage.close()


def test_deny_is_atomic_terminal_replays_after_expiry_and_consumes_proposal(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    body = decision(proposal) | {"decision": "deny"}
    try:
        receipt, replay = ledger.decide(
            call["id"], body, active_turn_id=turn["id"], timestamp=STAMP
        )
        assert not replay and ledger.call(call["id"])["status"] == "denied"
        assert not ledger.binding(turn["id"])["write_slot"]
        assert ledger.decide(call["id"], body, active_turn_id=None, stopped=True) == (receipt, True)
        native = dict(
            role="assistant",
            content="",
            tool_calls=[
                dict(
                    id="second",
                    type="function",
                    function=dict(
                        name="agent_profile_update", arguments=encoded(call["arguments"]).decode()
                    ),
                )
            ],
        )
        second = ledger.request_call(turn["id"], native, timestamp=STAMP)
        next_proposal = proposal | {
            "digest": proposal_digest(second["id"], second["grant_id"], proposal)
        }
        with pytest.raises(DraftError) as error:
            ledger.propose(second["id"], next_proposal, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_LIMIT"
        storage.validate()
    finally:
        storage.close()


@pytest.mark.parametrize("state", ["stopped", "expired", "revoked", "other_turn", "digest"])
def test_decision_refuses_invalid_authority_without_receipt(tmp_path, state):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    body = decision(proposal)
    options = dict(active_turn_id=turn["id"], timestamp=STAMP)
    if state == "stopped":
        options["stopped"] = True
    elif state == "expired":
        options["timestamp"] = proposal["expires_at"]
    elif state == "revoked":
        ledger.revoke(call["grant_id"])
    elif state == "other_turn":
        options["active_turn_id"] = uid()
    else:
        body["proposal_digest"] = "0" * 64
    try:
        with pytest.raises(DraftError) as error:
            ledger.decide(call["id"], body, **options)
        assert error.value.code == "CHAT_TOOL_APPROVAL_CONFLICT"
        assert ledger.call(call["id"])["status"] == "awaiting_approval"
        assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
    finally:
        storage.close()


def test_no_native_round_after_consumed_write_slot(tmp_path):
    from test_chat_tool_storage_limits import result

    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
        ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
        native = dict(
            role="assistant",
            content="",
            tool_calls=[
                dict(
                    id="again",
                    type="function",
                    function=dict(name="configuration_read", arguments='{"kind":"agent_profile"}'),
                )
            ],
        )
        with pytest.raises(DraftError) as error:
            ledger.request_call(turn["id"], native, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_LIMIT"
        assert len(ledger.transcript(turn["id"])["calls"]) == 1
    finally:
        storage.close()


def test_read_intent_cannot_arm_after_grant_revocation(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
    ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
    native = dict(
        role="assistant",
        content="",
        tool_calls=[
            dict(
                id="p",
                type="function",
                function=dict(name="configuration_read", arguments='{"kind":"agent_profile"}'),
            )
        ],
    )
    call = ledger.request_call(turn["id"], native, timestamp=STAMP)
    ledger.revoke(grant["id"])
    try:
        with pytest.raises(DraftError) as error:
            ledger.start_read(call["id"], timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_GRANT_INVALID"
        assert ledger.call(call["id"])["status"] == "requested"
    finally:
        storage.close()


def test_proposal_cannot_extend_original_turn_deadline(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    # Fresh requested call image, prior legitimate proposal removed only in fixture.
    with storage.transaction():
        row = dict(turn_id=turn["id"], call=call)
        storage.db.execute("UPDATE tool_calls SET data=?", (encoded(row).decode(),))
    late = proposal | {"expires_at": "2026-01-01T00:04:00+00:00"}
    late["digest"] = proposal_digest(call["id"], call["grant_id"], late)
    try:
        with pytest.raises(DraftError) as error:
            ledger.propose(call["id"], late, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_GRANT_INVALID"
    finally:
        storage.close()


def test_noncanonical_persisted_json_cannot_hide_uncharged_utf8(tmp_path):
    storage, ledger, _, _, _ = prepared(tmp_path)
    path = storage.path
    storage.close()
    with sqlite3.connect(path) as db:
        raw = db.execute("SELECT data FROM tool_grants").fetchone()[0]
        db.execute("UPDATE tool_grants SET data=?", (" " * 9000 + raw,))
    before = path.read_bytes()
    store = ChatStorage(tmp_path / "draft.json")
    try:
        with pytest.raises(DraftError) as error:
            store.open()
        assert error.value.code == "CHAT_STORAGE_ERROR"
        assert path.read_bytes() == before
    finally:
        store.close()


def test_reservation_metadata_growth_is_charged_to_own_reserve(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        # Inspect the positive hold-metadata delta through a second valid proposal
        # publication from a requested fixture image, not a fake usage counter.
        with storage.transaction():
            storage.db.execute(
                "UPDATE tool_calls SET data=?",
                (encoded(dict(turn_id=turn["id"], call=call)).decode(),),
            )
            reservation = ledger.reservation(turn["id"])
            reservation["exchange_hold"] = 0
            storage.db.execute(
                "UPDATE tool_reservations SET data=?", (encoded(reservation).decode(),)
            )
        before = ledger.usage()
        ledger.propose(call["id"], proposal, timestamp=STAMP)
        after = ledger.usage()
        assert after["actual"] + after["reserved"] <= before["actual"] + before["reserved"]
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["revoked", "expired"])
def test_native_call_admission_checks_consumed_authority(tmp_path, change):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
    ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
    if change == "revoked":
        ledger.revoke(grant["id"])
    timestamp = STAMP if change == "revoked" else "2026-01-01T00:02:00+00:00"
    native = dict(
        role="assistant",
        content="",
        tool_calls=[
            dict(
                id="p",
                type="function",
                function=dict(name="configuration_read", arguments='{"kind":"agent_profile"}'),
            )
        ],
    )
    try:
        with pytest.raises(DraftError) as error:
            ledger.request_call(turn["id"], native, timestamp=timestamp)
        assert error.value.code in {"CHAT_TOOL_GRANT_INVALID", "CHAT_TIMEOUT"}
        assert ledger.transcript(turn["id"])["calls"] == []
    finally:
        storage.close()
