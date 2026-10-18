"""Negative controls at actual ledger publication and restart boundaries."""

import json
import sqlite3

import pytest
from test_chat_tool_storage import STAMP, admission, grant_body, setup_store, uid
from test_chat_tool_storage_intents import prepared
from test_chat_tool_storage_limits import decision, result, terminal

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_models import proposal_digest
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError


@pytest.mark.parametrize(
    "operation",
    ["call", "binding", "grant", "transcript", "exchanges", "fence", "usage", "reservation"],
)
@pytest.mark.parametrize("phase", ["execute", "fetch"])
def test_all_ledger_reads_share_original_read_fence(tmp_path, operation, phase):
    storage, ledger, turn, call, _ = prepared(tmp_path)
    fired = []
    real = storage.db

    def fault():
        fired.append(phase)
        raise sqlite3.OperationalError("private")

    class Cursor:
        def fetchone(self):
            fault()

        def __iter__(self):
            fault()

    class Broken:
        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *args):
            if sql.startswith("SELECT"):
                if phase == "execute":
                    fault()
                return Cursor()
            return real.execute(sql, *args)

    storage.db = Broken()
    readers = dict(
        call=lambda: ledger.call(call["id"]),
        binding=lambda: ledger.binding(turn["id"]),
        grant=lambda: ledger.grant(call["grant_id"]),
        transcript=lambda: ledger.transcript(turn["id"]),
        exchanges=lambda: ledger.exchanges(turn["id"]),
        fence=ledger.fence,
        usage=ledger.usage,
        reservation=lambda: ledger.reservation(turn["id"]),
    )
    try:
        with pytest.raises(DraftError) as error:
            readers[operation]()
        assert error.value.code == "CHAT_COMMIT_UNCERTAIN" and fired == [phase]
        for read in readers.values():
            with pytest.raises(DraftError) as error:
                read()
            assert error.value.code == "CHAT_COMMIT_UNCERTAIN"
        assert fired == [phase]
    finally:
        storage.close()


def test_real_sqlite_full_during_receipt_recovers_intent_as_uncertain(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
    pages = storage.db.execute("PRAGMA page_count").fetchone()[0]
    storage.db.execute(f"PRAGMA max_page_count={pages}")
    fired = []
    storage.db.create_function("fired", 0, lambda: fired.append(True) or 0)
    storage.db.execute(
        "CREATE TEMP TRIGGER physical_fault BEFORE UPDATE ON tool_calls BEGIN "
        "SELECT fired(); INSERT INTO tool_exchanges VALUES ('fill', hex(zeroblob(2097152))); END"
    )
    actual_errors = []
    real = storage.db

    class ObservePhysicalError:
        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *args):
            try:
                return real.execute(sql, *args)
            except sqlite3.Error as exc:
                actual_errors.append(exc.sqlite_errorcode)
                raise

    storage.db = ObservePhysicalError()
    with pytest.raises(DraftError) as error:
        ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
    assert actual_errors == [sqlite3.SQLITE_FULL]
    assert error.value.code == "CHAT_COMMIT_UNCERTAIN"
    assert fired == [True] and storage.fenced and not storage.db.in_transaction
    with sqlite3.connect(storage.path) as observer:
        saved = json.loads(observer.execute("SELECT data FROM tool_calls").fetchone()[0])
        assert saved["call"]["status"] == "executing"
        assert observer.execute(
            "SELECT count(*) FROM tool_exchanges WHERE key='fill'"
        ).fetchone() == (0,)
    storage.close()
    storage = ChatStorage(tmp_path / "draft.json")
    try:
        storage.open()
        ledger = ToolLedger(storage)
        assert ledger.call(call["id"])["status"] == "uncertain"
        assert ledger.fence()["call_ids"] == [call["id"]]
        storage.validate()
    finally:
        storage.close()


def test_commit_then_raise_fences_live_owner_but_preserves_durable_receipt(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
    real = storage.db
    fired = []

    class CommitThenRaise:
        def __getattr__(self, name):
            return getattr(real, name)

        def commit(self):
            real.commit()
            fired.append(True)
            raise sqlite3.OperationalError("lost acknowledgement")

    storage.db = CommitThenRaise()
    with pytest.raises(DraftError):
        ledger.finish_call(call["id"], "succeeded", result=result(proposal), timestamp=STAMP)
    assert fired == [True] and storage.fenced
    storage.close()
    storage = ChatStorage(tmp_path / "draft.json")
    try:
        storage.open()
        ledger = ToolLedger(storage)
        assert ledger.call(call["id"])["status"] == "succeeded"
        assert not ledger.fence()["fenced"]
    finally:
        storage.close()


def test_fence_a_clear_a_fence_b_old_replay_cannot_clear_b(tmp_path):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(call["id"], decision(proposal), active_turn_id=turn["id"], timestamp=STAMP)
        ledger.finish_call(
            call["id"], "uncertain", error_code="CHAT_TOOL_UNCERTAIN", timestamp=STAMP
        )
        terminal(storage, turn)
        ledger.retire(turn["id"], owner_idle=True)
        body = dict(
            request_id=uid(),
            expected_generation=1,
            expected_draft_revision=8,
            acknowledge_uncertain=True,
        )
        receipt, _ = ledger.reconcile(body, current_draft_revision=8, owner_idle=True)
        session = storage.session(turn["session_id"])[0]
        updated, second, commitment = admission(session)
        grant, _ = ledger.create_grant(grant_body(session, commitment), timestamp=STAMP)
        ledger.admit(grant["id"], updated, second, commitment, timestamp=STAMP)
        native = dict(
            role="assistant",
            content="",
            tool_calls=[
                dict(
                    id="native-b",
                    type="function",
                    function=dict(
                        name="agent_profile_update", arguments=encoded(call["arguments"]).decode()
                    ),
                )
            ],
        )
        call_b = ledger.request_call(second["id"], native, timestamp=STAMP)
        proposal_b = proposal | {"digest": proposal_digest(call_b["id"], grant["id"], proposal)}
        ledger.propose(call_b["id"], proposal_b, timestamp=STAMP)
        ledger.decide(
            call_b["id"], decision(proposal_b), active_turn_id=second["id"], timestamp=STAMP
        )
        ledger.finish_call(
            call_b["id"], "uncertain", error_code="CHAT_TOOL_UNCERTAIN", timestamp=STAMP
        )
        before = ledger.fence()
        assert before["generation"] == 3 and before["call_ids"] == [call_b["id"]]
        assert ledger.reconcile(body, current_draft_revision=None, owner_idle=False) == (
            receipt,
            True,
        )
        assert ledger.fence() == before
        assert (
            ledger.call(call["id"])["status"] == ledger.call(call_b["id"])["status"] == "uncertain"
        )
        storage.validate()
    finally:
        storage.close()


@pytest.mark.parametrize(
    "stage", ["requested", "awaiting_approval", "read_executing", "pending_grant"]
)
def test_restart_unadmitted_authority_is_cancelled_not_uncertain(tmp_path, stage):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, commitment = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, commitment), timestamp=STAMP)
    call = None
    if stage != "pending_grant":
        ledger.admit(grant["id"], updated, turn, commitment, timestamp=STAMP)
        tool = "configuration_read" if stage == "read_executing" else "agent_profile_update"
        arguments = (
            dict(kind="agent_profile")
            if tool == "configuration_read"
            else dict(expected_draft_revision=0, name="New", skill_ids=[])
        )
        call = ledger.request_call(
            turn["id"],
            dict(
                role="assistant",
                content="",
                tool_calls=[
                    dict(
                        id="n",
                        type="function",
                        function=dict(name=tool, arguments=encoded(arguments).decode()),
                    )
                ],
            ),
            timestamp=STAMP,
        )
        if stage == "read_executing":
            ledger.start_read(call["id"], timestamp=STAMP)
        elif stage == "awaiting_approval":
            proposal = dict(
                expected_draft_revision=0,
                before=dict(resource_id="agent-profile", name="Old", skill_ids=[]),
                after=dict(resource_id="agent-profile", name="New", skill_ids=[]),
                expires_at="2026-01-01T00:02:00+00:00",
            )
            proposal["digest"] = proposal_digest(call["id"], grant["id"], proposal)
            ledger.propose(call["id"], proposal, timestamp=STAMP)
    storage.close()
    storage = ChatStorage(tmp_path / "draft.json")
    try:
        storage.open()
        ledger = ToolLedger(storage)
        if call:
            assert ledger.call(call["id"])["status"] == "cancelled"
            assert ledger.call(call["id"])["decision"] is None
        else:
            assert ledger.grant(grant["id"])["status"] == "expired"
        assert ledger.fence()["generation"] == 0
        storage.validate()
    finally:
        storage.close()
