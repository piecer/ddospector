"""Real SQLite v2 authorization and lifecycle; synthetic native inputs."""

import pytest

from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from tests.chat.test_chat_tool_storage import STAMP, admission, grant_body, setup_store


@pytest.mark.parametrize("target_first", [False, True])
def test_cross_variant_grant_replay_is_conflict_before_allocation(tmp_path, target_first):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    _, _, commitment = admission(session)
    legacy = grant_body(session, commitment)
    target = legacy | dict(schema_version=2, scope="target_create")
    first, second = (target, legacy) if target_first else (legacy, target)
    try:
        grant, replay = ledger.create_grant(first, timestamp=STAMP)
        assert not replay
        assert ledger.create_grant(first, timestamp="2030-01-01T00:00:00+00:00") == (grant, True)
        with pytest.raises(DraftError) as exc:
            ledger.create_grant(second, timestamp=STAMP)
        assert exc.value.code == "CHAT_TOOL_GRANT_CONFLICT"
        assert storage.db.execute("SELECT count(*) FROM tool_grants").fetchone() == (1,)
        assert grant["schema_version"] == (2 if target_first else 1)
        if target_first:
            assert grant["read_scope"] == ["targets", "target"]
            assert grant["proposal_tools"] == ["target_create"]
            assert "proposal_fields" not in grant
        storage.validate()
    finally:
        storage.close()


def native(tool, args, provider_id="synthetic-call"):
    from aiddos.api.chat_models import encoded

    return dict(
        role="assistant",
        content="",
        tool_calls=[
            dict(
                id=provider_id,
                type="function",
                function=dict(name=tool, arguments=encoded(args).decode()),
            )
        ],
    )


def admitted(tmp_path, target=True):
    storage, session = setup_store(tmp_path)
    ledger = ToolLedger(storage)
    updated, turn, body = admission(session)
    grant, _ = ledger.create_grant(
        grant_body(session, body)
        | (dict(schema_version=2, scope="target_create") if target else {}),
        timestamp=STAMP,
    )
    ledger.admit(grant["id"], updated, turn, body, timestamp=STAMP)
    return storage, ledger, turn, grant


@pytest.mark.parametrize(
    "target,tool,args",
    [
        (False, "configuration_read", dict(kind="targets", offset=0, limit=10)),
        (
            False,
            "target_create",
            dict(expected_draft_revision=0, name="new", address="Example.COM.", kind="DUT"),
        ),
        (True, "configuration_read", dict(kind="agent_profile")),
        (True, "configuration_read", dict(kind="skills", offset=103, limit=10)),
        (True, "agent_profile_update", dict(expected_draft_revision=0, name="new", skill_ids=[])),
    ],
)
def test_scope_denied_before_call_identity_or_exchange(tmp_path, monkeypatch, target, tool, args):
    storage, ledger, turn, _ = admitted(tmp_path, target)

    def forbidden():
        pytest.fail("denied call allocated identity")

    monkeypatch.setattr("aiddos.api.chat_tool_storage.uuid4", forbidden)
    try:
        before = ledger.usage()
        with pytest.raises(DraftError) as exc:
            ledger.request_call(turn["id"], native(tool, args), timestamp=STAMP)
        assert exc.value.code == "CHAT_TOOL_DENIED"
        assert ledger.transcript(turn["id"])["calls"] == []
        assert ledger.exchanges(turn["id"]) == []
        assert ledger.usage() == before
    finally:
        storage.close()


def proposal_for(call, ledger, turn):
    from aiddos.api.chat_tool_models import proposal_digest

    args = call["arguments"]
    proposal = dict(
        operation="target_create",
        expected_draft_revision=args["expected_draft_revision"],
        before=None,
        after={k: args[k] for k in ("name", "address", "kind")},
        expires_at=ledger.binding(turn["id"])["deadline_at"],
    )
    proposal["digest"] = proposal_digest(call["id"], call["grant_id"], proposal)
    return proposal


def receipt_for(call):
    args = call["arguments"]
    target = dict(
        id="existing-grammar-id",
        name=args["name"],
        address=args["address"],
        kind=args["kind"],
        status="draft",
        created_at=STAMP,
    )
    return dict(
        kind="target_created",
        before_revision=args["expected_draft_revision"],
        after_revision=args["expected_draft_revision"] + 1,
        target=target,
        audit=dict(
            id="audit-id",
            action="target.created",
            entity_id=target["id"],
            created_at=STAMP,
            origin="local_operator",
        ),
    )


def approved(ledger, turn, *, revision=0, name='target " 🌍', provider_id="synthetic-call"):
    from tests.chat.test_chat_tool_storage import uid

    call = ledger.request_call(
        turn["id"],
        native(
            "target_create",
            dict(expected_draft_revision=revision, name=name, address="Example.COM.", kind="DUT"),
            provider_id,
        ),
        timestamp=STAMP,
    )
    proposal = proposal_for(call, ledger, turn)
    ledger.propose(call["id"], proposal, timestamp=STAMP)
    decision = dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve")
    first = ledger.decide(call["id"], decision, active_turn_id=turn["id"], timestamp=STAMP)
    assert first[1] is False
    assert ledger.decide(
        call["id"], decision, active_turn_id=None, timestamp="2030-01-01T00:00:00+00:00"
    ) == (first[0], True)
    return ledger.call(call["id"])


def test_target_proposal_decision_receipt_and_operation_digest(tmp_path):
    from aiddos.api.chat_tool_models import digest, proposal_digest

    storage, ledger, turn, grant = admitted(tmp_path)
    try:
        call = approved(ledger, turn)
        proposal = call["proposal"]
        expected = {k: v for k, v in proposal.items() if k != "digest"} | dict(
            call_id=call["id"], grant_id=grant["id"]
        )
        assert proposal["digest"] == digest(expected)
        assert (
            proposal_digest(call["id"], grant["id"], proposal | {"operation": "other"})
            != proposal["digest"]
        )
        result = receipt_for(call)
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=result, timestamp=STAMP
        )
        assert retained and saved["result"] == result
        assert ledger.binding(turn["id"])["write_slot"]
        storage.validate()
    finally:
        storage.close()
