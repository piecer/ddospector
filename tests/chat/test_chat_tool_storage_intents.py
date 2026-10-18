"""Approval, intent and replay are durable facts, never domain execution."""

import sqlite3

import pytest
from test_chat_tool_storage import STAMP, admission, grant_body, setup_store, uid

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import proposal_digest
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError


def prepared(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
    ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
    arguments = dict(expected_draft_revision=7, name="New 한😀", skill_ids=["skill-a"])
    native = dict(
        role="assistant",
        content="",
        tool_calls=[
            dict(
                id="native-1",
                type="function",
                function=dict(name="agent_profile_update", arguments=encoded(arguments).decode()),
            )
        ],
    )
    call = ledger.request_call(turn["id"], native, timestamp=STAMP)
    proposal = dict(
        expected_draft_revision=7,
        before=dict(resource_id="agent-profile", name="Before", skill_ids=[]),
        after=dict(
            resource_id="agent-profile", name=arguments["name"], skill_ids=arguments["skill_ids"]
        ),
        expires_at="2026-01-01T00:02:00+00:00",
    )
    proposal["digest"] = proposal_digest(call["id"], grant["id"], proposal)
    ledger.propose(call["id"], proposal, timestamp=STAMP)
    return storage, ledger, turn, call, proposal


def test_approval_is_atomic_intent_and_exact_replay_precedes_expiry(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    body = dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve")
    try:
        receipt, replay = ledger.decide(
            call["id"], body, active_turn_id=turn["id"], timestamp=STAMP
        )
        assert not replay
        current = ledger.call(call["id"])
        assert current["status"] == "executing" and current["decision"] == receipt
        assert ledger.binding(turn["id"])["write_slot"] is True
        assert ledger.decide(
            call["id"],
            body,
            active_turn_id=None,
            timestamp="2027-01-01T00:00:00+00:00",
            stopped=True,
        ) == (receipt, True)
        for changed in (body | {"request_id": uid()}, body | {"decision": "deny"}):
            with pytest.raises(DraftError) as error:
                ledger.decide(call["id"], changed, active_turn_id=turn["id"], timestamp=STAMP)
            assert error.value.code == "CHAT_TOOL_APPROVAL_CONFLICT"
        storage.validate()
    finally:
        storage.close()


def test_late_decision_failure_rolls_back_decision_intent_and_slot(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    fired = []
    storage.db.create_function("fault", 0, lambda: fired.append(True) or 1)
    storage.db.execute(
        "CREATE TEMP TRIGGER fail_intent BEFORE UPDATE ON tool_calls "
        "BEGIN SELECT fault(); SELECT RAISE(ABORT, 'fault'); END"
    )
    try:
        with pytest.raises(DraftError):
            ledger.decide(
                call["id"],
                dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve"),
                active_turn_id=turn["id"],
                timestamp=STAMP,
            )
        assert fired == [True] and storage.fenced and not storage.db.in_transaction
        with sqlite3.connect(storage.path) as observer:
            assert observer.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
            import json

            saved = json.loads(observer.execute("SELECT data FROM tool_calls").fetchone()[0])
            assert saved["call"]["status"] == "awaiting_approval"
            binding = json.loads(observer.execute("SELECT data FROM tool_bindings").fetchone()[0])
            assert not binding["write_slot"]
    finally:
        storage.close()


def test_restart_armed_intent_fences_once_and_reconciliation_is_historical(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    body = dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve")
    ledger.decide(call["id"], body, active_turn_id=turn["id"], timestamp=STAMP)
    storage.close()
    for _ in range(2):
        storage = ChatStorage(tmp_path / "draft.json")
        storage.open()
        ledger = ToolLedger(storage)
        assert ledger.call(call["id"])["status"] == "uncertain"
        assert ledger.fence()["generation"] == 1 and ledger.fence()["fenced"]
        assert ledger.reservation(turn["id"])["remaining"] == 8192
        assert storage.turn(turn["id"])["status"] == "interrupted"
        storage.close()
    storage = ChatStorage(tmp_path / "draft.json")
    storage.open()
    ledger = ToolLedger(storage)
    reconcile = dict(
        request_id=uid(),
        expected_generation=1,
        expected_draft_revision=8,
        acknowledge_uncertain=True,
    )
    receipt, replay = ledger.reconcile(reconcile, current_draft_revision=8, owner_idle=True)
    assert not replay and receipt["generation"] == 2
    assert ledger.fence()["fenced"] is False
    assert ledger.reservation(turn["id"])["remaining"] == 0
    assert ledger.reconcile(reconcile, current_draft_revision=None, owner_idle=False) == (
        receipt,
        True,
    )
    assert ledger.call(call["id"])["status"] == "uncertain"
    storage.validate()
    storage.close()
