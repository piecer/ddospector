"""Frozen default schema export and additive runtime/grant wire controls."""

import pytest

from aiddos.api import chat_tool_models as m
from aiddos.api.chat_tool_runtime import schemas
from tests.chat.test_chat_target_ledger import admitted


def test_schemas_are_selected_by_stored_grant_and_legacy_export_is_exact(tmp_path):
    assert m.digest(schemas()) == "09616007ee85d4093e8e596c115d1fa6857503ffc72074ed88c4d6cf1552b469"
    storage, _, _, grant = admitted(tmp_path)
    try:
        target = schemas(grant)
        assert [t["function"]["name"] for t in target] == ["configuration_read", "target_create"]
        read = target[0]["function"]["parameters"]
        assert read["type"] == "object" and "$ref" not in read and "$defs" not in read
        assert [b["properties"]["kind"]["const"] for b in read["oneOf"]] == ["targets", "target"]
        assert read["properties"]["offset"]["maximum"] == 100
        assert schemas()[0]["function"]["parameters"]["properties"]["offset"]["maximum"] == 103
        assert all(b["additionalProperties"] is False for b in read["oneOf"])
    finally:
        storage.close()


def test_v2_runtime_keeps_closed_v1_consumer():
    value = dict(
        schema_version=2,
        mode="operator_approved_settings",
        supported=True,
        reason=None,
        tools=["configuration_read", "agent_profile_update", "target_create"],
        max_calls=3,
        max_writes=1,
        requires_write_approval=True,
    )
    assert m.ToolRuntimeV2.model_validate(value).model_dump() == value
    with pytest.raises(ValueError):
        m.ToolRuntime.model_validate(value)
    for mutation in (
        {"schema_version": True},
        {"schema_version": 2.0},
        {"tools": ["target_create"]},
        {"extra": None},
    ):
        with pytest.raises(ValueError):
            m.ToolRuntimeV2.model_validate(value | mutation)


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 1},
        {"schema_version": True},
        {"schema_version": 2.0},
        {"scope": "agent_update"},
        {"proposal_fields": ["name"]},
        {"read_scope": ["targets"]},
    ],
)
def test_grant_input_does_not_admit_extra_or_coerced_authority(tmp_path, mutation):
    from tests.chat.test_chat_tool_storage import admission, grant_body, setup_store

    storage, session = setup_store(tmp_path)
    try:
        _, _, body = admission(session)
        legacy = grant_body(session, body)
        target = legacy | dict(schema_version=2, scope="target_create")
        with pytest.raises(ValueError):
            m.GrantRequest.model_validate(target | mutation)
        with pytest.raises(ValueError):
            m.GrantRequest.model_validate(legacy | dict(schema_version=1))
        assert m.GrantRequest.model_validate(legacy).model_dump() == legacy
        assert m.GrantRequest.model_validate(target).model_dump() == target
    finally:
        storage.close()


def test_target_grant_reopens_expired_without_authority_rewrite(tmp_path):
    from aiddos.api.chat_storage import ChatStorage
    from aiddos.api.chat_tool_storage import ToolLedger
    from tests.chat.test_chat_tool_storage import STAMP, admission, grant_body, setup_store

    storage, session = setup_store(tmp_path)
    _, _, body = admission(session)
    request = grant_body(session, body) | dict(schema_version=2, scope="target_create")
    grant, _ = ToolLedger(storage).create_grant(request, timestamp=STAMP)
    storage.close()
    reopened = ChatStorage(tmp_path / "draft.json")
    try:
        assert reopened.open()
        found = ToolLedger(reopened).grant(grant["id"])
        assert found == grant | {"status": "expired"}
        assert ToolLedger(reopened).create_grant(request) == (found, True)
        assert reopened.db.execute("PRAGMA user_version").fetchone() == (2,)
    finally:
        reopened.close()


def test_legacy_retained_denied_then_unproposed_write_graph_stays_readable(tmp_path):
    # Old ledger admitted a second requested write after denial, then rejected its
    # proposal. Preserve that historical graph without authorizing new attempts.
    from tests.chat.test_chat_target_ledger import native
    from tests.chat.test_chat_tool_storage import STAMP, uid
    from tests.chat.test_chat_tool_storage_intents import prepared
    from tests.chat.test_chat_tool_storage_limits import decision

    storage, ledger, turn, call, proposal = prepared(tmp_path)
    try:
        ledger.decide(
            call["id"],
            decision(proposal) | {"decision": "deny"},
            active_turn_id=turn["id"],
            timestamp=STAMP,
        )
        second = call | dict(
            id=uid(),
            index=1,
            provider_call_id="legacy-second",
            status="requested",
            proposal=None,
            decision=None,
            result=None,
            error_code=None,
            finished_at=None,
        )
        with storage.transaction():
            ledger._append(
                turn["id"], native("agent_profile_update", second["arguments"], "legacy-second")
            )
            ledger._save_call(turn["id"], second)
        storage.validate()
    finally:
        storage.close()
