"""Byte accounting, escaped envelopes, physical failures and historic fences."""

import json

import pytest
from test_chat_tool_storage import STAMP, admission, grant_body, setup_store, uid
from test_chat_tool_storage_intents import prepared

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import EXCHANGE_BYTES, proposal_digest
from aiddos.api.chat_tool_storage import TABLES, ToolLedger, charge
from aiddos.api.errors import DraftError


def decision(proposal):
    return dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve")


def result(proposal):
    return dict(
        kind="agent_profile_updated",
        before_revision=7,
        after_revision=8,
        agent_profile=proposal["after"],
        audit=dict(
            id="audit-one",
            action="agent_profile.updated",
            entity_id="agent-profile",
            origin="local_operator",
            created_at=STAMP,
        ),
    )


def terminal(storage, turn, *, succeeded=False):
    turn = turn | dict(
        status="succeeded" if succeeded else "failed",
        revision=turn["revision"] + 1,
        assistant_text="saved" if succeeded else "",
        finished_at=STAMP,
        error_code=None if succeeded else "CHAT_TOOL_LIMIT",
    )
    storage.update_turn(turn)
    return turn


def test_success_is_immutable_and_exact_native_exchange_survives_restart(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=result(proposal), timestamp=STAMP
        )
        assert retained and saved["status"] == "succeeded"
        ledger.append_final(turn["id"], "saved")
        terminal(storage, turn, succeeded=True)
        ledger.retire(turn["id"], owner_idle=True)
        original = ledger.exchanges(turn["id"])
        actual = sum(
            charge(k, json.loads(raw))
            for table in TABLES
            for k, raw in storage.db.execute(f"SELECT key, data FROM {table}")
        )
        assert ledger.usage()["actual"] == actual
        assert ledger.reservation(turn["id"])["remaining"] == 0
        with pytest.raises(DraftError):
            ledger.finish_call(
                call["id"], "uncertain", error_code="CHAT_TOOL_UNCERTAIN", timestamp=STAMP
            )
        storage.validate()
    finally:
        storage.close()
    store = ChatStorage(tmp_path / "draft.json")
    try:
        store.open()
        restarted = ToolLedger(store)
        assert restarted.call(call["id"]) == saved
        assert restarted.exchanges(turn["id"]) == original
        assert not restarted.fence()["fenced"]
    finally:
        store.close()


def test_later_final_overflow_does_not_erase_success(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
        ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
        with pytest.raises(DraftError) as error:
            ledger.append_final(turn["id"], "\x01" * 65536)
        assert error.value.code == "CHAT_TOOL_LIMIT"
        assert ledger.call(call["id"])["status"] == "succeeded"
        terminal(storage, turn)
        ledger.retire(turn["id"], owner_idle=True)
        storage.validate()
    finally:
        storage.close()


def test_retirement_does_not_allow_replacement_before_owner_retires(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.finish_call(call["id"], "cancelled", error_code="CHAT_CANCELLED", timestamp=STAMP)
        terminal(storage, turn)
        session = storage.session(turn["session_id"])[0]
        updated, next_turn, body = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
        with pytest.raises(DraftError) as error:
            ledger.admit(grant["id"], updated, next_turn, body, timestamp=STAMP)
        assert error.value.code == "CHAT_BUSY"
        ledger.retire(turn["id"], owner_idle=True)
        ledger.admit(grant["id"], updated, next_turn, body, timestamp=STAMP)
    finally:
        storage.close()


def test_terminal_timestamp_cannot_precede_decision(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(
            call["id"],
            decision(proposal),
            active_turn_id=turn["id"],
            timestamp="2026-01-01T00:00:30+00:00",
        )
        with pytest.raises(ValueError):
            ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
        assert ledger.call(call["id"])["status"] == "executing"
    finally:
        storage.close()


def test_missing_companion_reads_do_not_create_files(tmp_path):
    storage = ChatStorage(tmp_path / "draft.json")
    ledger = ToolLedger(storage)
    assert ledger.fence()["generation"] == 0
    assert ledger.usage() == dict(actual=0, reserved=0, limit=2097152)
    assert ledger.reservation(uid()) is None
    for read in (ledger.call, ledger.grant, ledger.transcript, ledger.exchanges):
        with pytest.raises(DraftError) as error:
            read(uid())
        assert error.value.code == "CHAT_NOT_FOUND"
    assert list(tmp_path.iterdir()) == []


def test_legal_oversized_read_detail_is_bounded_failed_tool_result(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    try:
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
                    function=dict(name="configuration_read", arguments='{"kind":"skill","id":"s"}'),
                )
            ],
        )
        call = ledger.request_call(turn["id"], native, timestamp=STAMP)
        ledger.start_read(call["id"], timestamp=STAMP)
        oversized = dict(
            kind="skill",
            draft_revision=7,
            skill=dict(
                id="s",
                name="Skill",
                category="analysis",
                status="draft",
                version="1.0.0",
                description="😀" * 1000,
                instructions="😀" * 8000,
            ),
        )
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=oversized, timestamp=STAMP
        )
        assert saved["status"] == "failed" and saved["error_code"] == "CHAT_TOOL_LIMIT"
        assert saved["result"] is None and retained
        assert (
            ledger.exchanges(turn["id"])[-1]["content"]
            == encoded(dict(ok=False, result=None, error_code="CHAT_TOOL_LIMIT")).decode()
        )
        storage.validate()
    finally:
        storage.close()


def test_full_reservation_refuses_with_room_for_actual_small_records(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    # Populate valid retained revoked grants in one fixture transaction. Admission
    # still runs through the real API; no fake usage counters or filler table.
    try:
        _, _, body = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
        ledger.revoke(grant["id"])
        grant = ledger.grant(grant["id"])
        count = 1048576 // charge(grant["id"], grant) + 1
        with storage.transaction():
            for _ in range(count):
                record = grant | dict(id=uid(), request_id=uid(), turn_request_id=uid())
                storage.db.execute(
                    "INSERT INTO tool_grants VALUES (?,?)", (record["id"], encoded(record).decode())
                )
        storage.validate()
        usage = ledger.usage()
        assert 1048576 < usage["actual"] < 2097152 and usage["reserved"] == 0
        updated, turn, body = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
        before = ledger.usage()
        with pytest.raises(DraftError) as error:
            ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_LIMIT"
        assert ledger.usage() == before and ledger.grant(grant["id"])["status"] == "pending"
        assert storage.db.execute("SELECT count(*) FROM turns").fetchone() == (0,)
        storage.validate()
    finally:
        storage.close()


def test_maximal_projection_counts_nested_escape_and_holds_growth(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    try:
        updated, turn, body = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
        ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
        arguments = dict(
            expected_draft_revision=7,
            name='😀"' * 60,
            skill_ids=[f"skill-{i:03}-" + "a" * 54 for i in range(103)],
        )
        raw = encoded(arguments).decode()
        native = dict(
            role="assistant",
            content="\x01" * 100,
            tool_calls=[
                dict(
                    id="p" * 128,
                    type="function",
                    function=dict(name="agent_profile_update", arguments=raw),
                )
            ],
        )
        call = ledger.request_call(turn["id"], native, timestamp=STAMP)
        proposal = dict(
            expected_draft_revision=7,
            before=dict(resource_id="agent-profile", name="Before", skill_ids=[]),
            after=dict(
                resource_id="agent-profile",
                name=arguments["name"],
                skill_ids=arguments["skill_ids"],
            ),
            expires_at="2026-01-01T00:02:00+00:00",
        )
        proposal["digest"] = proposal_digest(call["id"], grant["id"], proposal)
        before = len(encoded(ledger.exchanges(turn["id"])))
        ledger.propose(call["id"], proposal, timestamp=STAMP)
        held = ledger.reservation(turn["id"])["exchange_hold"]
        assert held > len(encoded(result(proposal)))
        ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
        ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
        after = len(encoded(ledger.exchanges(turn["id"])))
        assert 0 < after - before <= held
        assert ledger.reservation(turn["id"])["exchange_hold"] == 0
        storage.validate()
    finally:
        storage.close()


def test_projection_uses_maximum_provider_id_and_timestamp(tmp_path):
    storage, ledger, turn, _, proposal = prepared(tmp_path)
    try:
        receipt = result(proposal)
        receipt.update(before_revision=9007199254740990, after_revision=9007199254740991)
        receipt["audit"].update(
            id="a" * 64, created_at="9999-12-31T23:59:59." + "9" * 14 + "+00:00"
        )
        message = dict(
            role="tool",
            tool_call_id="p" * 128,
            content=encoded(dict(ok=True, result=receipt, error_code=None)).decode(),
        )
        messages = ledger.exchanges(turn["id"])
        projected_growth = len(encoded(messages + [message])) - len(encoded(messages))
        assert ledger.reservation(turn["id"])["exchange_hold"] >= projected_growth
    finally:
        storage.close()


def test_native_escaped_growth_refused_before_call_persistence(tmp_path):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    try:
        updated, turn, body = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, body), timestamp=STAMP)
        ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
        native = dict(
            role="assistant",
            content="\x01" * 16384,
            tool_calls=[
                dict(
                    id="p",
                    type="function",
                    function=dict(name="configuration_read", arguments='{"kind":"agent_profile"}'),
                )
            ],
        )
        assert len(encoded([native])) > EXCHANGE_BYTES
        before = ledger.usage()
        with pytest.raises(DraftError) as error:
            ledger.request_call(turn["id"], native, timestamp=STAMP)
        assert error.value.code == "CHAT_TOOL_LIMIT"
        assert ledger.transcript(turn["id"])["calls"] == []
        assert ledger.exchanges(turn["id"]) == [] and ledger.usage() == before
    finally:
        storage.close()
