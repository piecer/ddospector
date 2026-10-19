"""Legacy bytes and all ordered scope substitutions against the actual ledger."""

import hashlib
from itertools import permutations

import pytest

from aiddos.api import chat_tool_models as m
from aiddos.api.chat_tool_runtime import schemas
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_ledger import admitted
from tests.chat.test_chat_skill_models import arguments
from tests.chat.test_chat_target_ledger import native
from tests.chat.test_chat_tool_storage import STAMP

WRITES = {
    1: ("agent_profile_update", dict(expected_draft_revision=0, name="agent", skill_ids=[])),
    2: (
        "target_create",
        dict(expected_draft_revision=0, name="target", address="host", kind="DUT"),
    ),
    3: ("skill_create", arguments()),
}


@pytest.mark.parametrize("owner,foreign", list(permutations((1, 2, 3), 2)))
def test_legacy_exports_and_all_ordered_scope_substitutions(tmp_path, monkeypatch, owner, foreign):
    assert (
        hashlib.sha256(m.encoded(schemas())).hexdigest()
        == "9dc6d6811fd75c59bef77c473c2dc21d5de7224b393c3a224e85e972b2d1dc06"
    )
    storage, ledger, turn, _ = admitted(tmp_path, owner)
    try:

        def forbidden():
            pytest.fail("wrong scope allocated Call identity")

        monkeypatch.setattr("aiddos.api.chat_tool_storage.uuid4", forbidden)
        before = ledger.usage()
        with pytest.raises(DraftError) as exc:
            ledger.request_call(turn["id"], native(*WRITES[foreign]), timestamp=STAMP)
        assert exc.value.code == "CHAT_TOOL_DENIED"
        assert ledger.transcript(turn["id"])["calls"] == [] and ledger.exchanges(turn["id"]) == []
        assert ledger.usage() == before
        storage.validate()
    finally:
        storage.close()


@pytest.mark.parametrize(
    "owner,kind",
    [
        (1, "targets"),
        (1, "target"),
        (2, "skills"),
        (2, "skill"),
        (2, "agent_profile"),
        (3, "agent_profile"),
        (3, "targets"),
        (3, "target"),
    ],
)
def test_read_scope_substitutions_before_call_allocation(tmp_path, owner, kind):
    storage, ledger, turn, _ = admitted(tmp_path, owner)
    args = dict(kind=kind)
    if kind in ("targets", "skills"):
        args.update(offset=0, limit=10)
    elif kind in ("target", "skill"):
        args["id"] = "domain-id"
    try:
        with pytest.raises(DraftError) as exc:
            ledger.request_call(turn["id"], native("configuration_read", args), timestamp=STAMP)
        assert exc.value.code == "CHAT_TOOL_DENIED"
        assert ledger.transcript(turn["id"])["calls"] == [] and ledger.exchanges(turn["id"]) == []
    finally:
        storage.close()


def test_authority_classifier_is_finite_not_non_v1_fallback():
    for grant in (
        dict(schema_version=4, proposal_tools=["skill_create"], read_scope=["skills"]),
        dict(
            schema_version=3,
            scope="target_create",
            proposal_tools=["skill_create"],
            read_scope=["skills"],
        ),
    ):
        assert not m.allows_call(grant, "skill_create", arguments())
        assert not m.allows_call(
            grant, "configuration_read", dict(kind="skills", offset=0, limit=10)
        )
