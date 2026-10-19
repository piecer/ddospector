"""Real owned SQLite authority tests; synthetic native inputs, no domain writes."""

from itertools import permutations

import pytest

from aiddos.api.chat_tool_models import proposal_digest
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_models import arguments, receipt
from tests.chat.test_chat_target_ledger import native
from tests.chat.test_chat_tool_storage import STAMP, admission, grant_body, setup_store, uid


def variant(version):
    return (
        {}
        if version == 1
        else dict(schema_version=version, scope={2: "target_create", 3: "skill_create"}[version])
    )


def admitted(tmp_path, version=3):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(grant_body(session, body) | variant(version), timestamp=STAMP)
    ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
    return storage, ledger, turn, grant


def proposal_for(call, ledger, turn):
    proposal = dict(
        operation="skill_create",
        expected_draft_revision=call["arguments"]["expected_draft_revision"],
        before=None,
        after={k: v for k, v in call["arguments"].items() if k != "expected_draft_revision"},
        expires_at=ledger.binding(turn["id"])["deadline_at"],
    )
    return proposal | {"digest": proposal_digest(call["id"], call["grant_id"], proposal)}


def approved(ledger, turn, args=None):
    call = ledger.request_call(
        turn["id"], native("skill_create", args or arguments()), timestamp=STAMP
    )
    proposal = proposal_for(call, ledger, turn)
    ledger.propose(call["id"], proposal, timestamp=STAMP)
    body = dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve")
    first = ledger.decide(call["id"], body, active_turn_id=turn["id"], timestamp=STAMP)
    assert not first[1]
    assert ledger.decide(
        call["id"], body, active_turn_id=None, timestamp="2030-01-01T00:00:00+00:00"
    ) == (first[0], True)
    return ledger.call(call["id"])


@pytest.mark.parametrize("first,second", list(permutations((1, 2, 3), 2)))
def test_request_replay_binds_exact_variant(tmp_path, monkeypatch, first, second):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    _, _, commitment = admission(session)
    body = grant_body(session, commitment)
    try:
        grant, replay = ledger.create_grant(body | variant(first), timestamp=STAMP)
        assert not replay

        def forbidden():
            pytest.fail("Replay/substitution allocated grant identity")

        monkeypatch.setattr("aiddos.api.chat_tool_storage.uuid4", forbidden)
        assert ledger.create_grant(
            body | variant(first), timestamp="2030-01-01T00:00:00+00:00"
        ) == (grant, True)
        with pytest.raises(DraftError) as exc:
            ledger.create_grant(body | variant(second), timestamp=STAMP)
        assert exc.value.code == "CHAT_TOOL_GRANT_CONFLICT"
        assert storage.db.execute("SELECT count(*) FROM tool_grants").fetchone() == (1,)
        storage.validate()
    finally:
        storage.close()


def test_exact_approval_and_complete_skill_receipt_are_linked(tmp_path):
    from copy import deepcopy

    from aiddos.api.chat_tool_models import ToolCall

    storage, ledger, turn, grant = admitted(tmp_path)
    try:
        assert grant["read_scope"] == ["skills", "skill"] and grant["proposal_tools"] == [
            "skill_create"
        ]
        call = approved(ledger, turn)
        result = receipt(call["arguments"])
        completed = call | dict(status="succeeded", result=result, finished_at=STAMP)
        assert ToolCall.model_validate(completed).model_dump() == completed
        for change in ("name", "description", "instructions", "category", "revision", "operation"):
            bad = deepcopy(completed)
            if change in ("name", "description", "instructions"):
                bad["result"]["skill"][change] = dict(en="different", ko="different")
            elif change == "category":
                bad["result"]["skill"][change] = "analysis"
            elif change == "revision":
                bad["result"].update(before_revision=1, after_revision=2)
            else:
                bad["proposal"]["operation"] = "target_create"
            with pytest.raises(ValueError):
                ToolCall.model_validate(bad)
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=result, timestamp=STAMP
        )
        assert retained and saved == completed
        assert ledger.binding(turn["id"])["write_slot"]
        storage.validate()
    finally:
        storage.close()
