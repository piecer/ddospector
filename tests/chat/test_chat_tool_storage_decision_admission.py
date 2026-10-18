"""New decisions recheck authority after preparation, before durable intent."""

from datetime import timedelta

import pytest
from test_chat_tool_storage import STAMP, uid
from test_chat_tool_storage_intents import prepared

from aiddos.api import chat_tool_storage
from aiddos.api.errors import DraftError


def assert_unadmitted(storage, ledger, turn, call):
    assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
    current = ledger.call(call["id"])
    assert current["status"] == "awaiting_approval" and current["decision"] is None
    assert ledger.binding(turn["id"])["write_slot"] is False
    assert not storage.db.in_transaction and not storage.fenced


@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize("expiry", ["proposal", "grant"])
@pytest.mark.parametrize("exceeded", [False, True])
def test_projection_crosses_utc_expiry_before_decision(
    tmp_path, monkeypatch, decision, expiry, exceeded
):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    clock = [STAMP]
    monkeypatch.setattr(chat_tool_storage, "now", lambda: clock[0])
    seam = "_projection" if decision == "approve" else "binding"
    original = getattr(ledger, seam)
    expires_at = (proposal if expiry == "proposal" else ledger.grant(call["grant_id"]))[
        "expires_at"
    ]
    entered = []

    def delayed(*args):
        result = original(*args)
        if not entered:
            entered.append(True)
            clock[0] = (
                chat_tool_storage.instant(expires_at) + timedelta(seconds=int(exceeded))
            ).isoformat()
        return result

    monkeypatch.setattr(ledger, seam, delayed)
    try:
        with pytest.raises(DraftError) as error:
            ledger.decide(
                call["id"],
                dict(request_id=uid(), proposal_digest=proposal["digest"], decision=decision),
                active_turn_id=turn["id"],
            )
        assert error.value.code == "CHAT_TOOL_APPROVAL_CONFLICT"
        assert entered == [True]
        assert_unadmitted(storage, ledger, turn, call)
    finally:
        storage.close()


@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize("injected_timestamp", [False, True])
def test_accepted_timestamp_matches_final_check_and_exact_replay(
    tmp_path, monkeypatch, decision, injected_timestamp
):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    body = dict(request_id=uid(), proposal_digest=proposal["digest"], decision=decision)
    clock = [STAMP]
    monkeypatch.setattr(chat_tool_storage, "now", lambda: clock[0])
    seam = "_projection" if decision == "approve" else "binding"
    original = getattr(ledger, seam)
    entered = []
    final_stamp = "2026-01-01T00:00:01+00:00"

    def prepare(*args):
        result = original(*args)
        if not entered:
            entered.append(True)
            clock[0] = "2027-01-01T00:00:00+00:00" if injected_timestamp else final_stamp
        return result

    monkeypatch.setattr(ledger, seam, prepare)
    guarded = []

    def guard(turn_id):
        assert storage.db.in_transaction and turn_id == turn["id"]
        assert entered == [True]
        assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
        guarded.append(True)

    try:
        receipt, replay = ledger.decide(
            call["id"],
            body,
            active_turn_id=turn["id"],
            timestamp=STAMP if injected_timestamp else None,
            admission_guard=guard,
        )
        assert not replay and guarded == [True]
        assert receipt["accepted_at"] == (STAMP if injected_timestamp else final_stamp)
        current = ledger.call(call["id"])
        assert current["decision"] == receipt
        assert current["status"] == ("executing" if decision == "approve" else "denied")
        assert ledger.binding(turn["id"])["write_slot"] == (decision == "approve")
        if decision == "deny":
            assert current["finished_at"] == receipt["accepted_at"]
            assert current["error_code"] == "CHAT_TOOL_DENIED"
        else:
            ledger.finish_call(
                call["id"],
                "cancelled",
                error_code="CHAT_CANCELLED",
                timestamp=receipt["accepted_at"],
            )
        before = list(storage.db.iterdump())

        def forbidden(_):
            pytest.fail("historical replay must not consult live authority")

        clock[0] = "2027-01-01T00:00:00+00:00"
        assert ledger.decide(
            call["id"],
            body,
            active_turn_id=None,
            stopped=True,
            admission_guard=forbidden,
        ) == (receipt, True)
        for conflict in (
            body | {"request_id": uid()},
            body | {"decision": "deny" if decision == "approve" else "approve"},
        ):
            with pytest.raises(DraftError) as error:
                ledger.decide(
                    call["id"],
                    conflict,
                    active_turn_id=None,
                    stopped=True,
                    admission_guard=forbidden,
                )
            assert error.value.code == "CHAT_TOOL_APPROVAL_CONFLICT"
        assert list(storage.db.iterdump()) == before
        storage.validate()
    finally:
        storage.close()


@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize("failure", ["authority", "unexpected"])
def test_live_guard_throw_precedes_every_durable_write(tmp_path, monkeypatch, decision, failure):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    entered = []
    writes = []
    original = ledger._put

    def put(*args):
        writes.append(args[0])
        return original(*args)

    monkeypatch.setattr(ledger, "_put", put)
    error = (
        DraftError("CHAT_TOOL_APPROVAL_CONFLICT")
        if failure == "authority"
        else RuntimeError("live guard failed")
    )

    def guard(turn_id):
        assert storage.db.in_transaction and turn_id == turn["id"]
        entered.append(True)
        raise error

    try:
        before = list(storage.db.iterdump())
        with pytest.raises(type(error)) as caught:
            ledger.decide(
                call["id"],
                dict(request_id=uid(), proposal_digest=proposal["digest"], decision=decision),
                active_turn_id=turn["id"],
                timestamp=STAMP,
                admission_guard=guard,
            )
        assert caught.value is error and entered == [True] and writes == []
        assert_unadmitted(storage, ledger, turn, call)
        assert list(storage.db.iterdump()) == before
    finally:
        storage.close()
