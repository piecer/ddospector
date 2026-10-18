"""Closed tool wire records, exact digests and UTF-8 boundaries."""

import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aiddos.api.chat_models import encoded


def test_closed_arguments_preserve_literals_and_reject_bool_counters():
    from aiddos.api.chat_tool_models import parse_arguments

    assert parse_arguments("configuration_read", '{"kind":"skill","id":"literal-id"}') == {
        "kind": "skill",
        "id": "literal-id",
    }
    for raw in (
        '{"kind":"skills","offset":true,"limit":1}',
        '{"kind":"agent_profile","extra":0}',
        '{"kind":"agent_profile","kind":"agent_profile"}',
    ):
        with pytest.raises(ValueError):
            parse_arguments("configuration_read", raw)


def test_digest_is_recursively_sorted_utf8():
    from aiddos.api.chat_tool_models import digest

    assert (
        digest({"z": {"b": "한😀", "a": 2}, "a": 1})
        == hashlib.sha256('{"a":1,"z":{"a":2,"b":"한😀"}}'.encode()).hexdigest()
    )


def call_record():
    from aiddos.api.chat_tool_models import digest

    arguments = {"kind": "agent_profile"}
    return dict(
        id=str(uuid4()),
        index=0,
        provider_call_id="call_1",
        tool="configuration_read",
        arguments=arguments,
        args_digest=digest(arguments),
        grant_id=str(uuid4()),
        actor="operator_authorized_model",
        status="requested",
        error_code=None,
        proposal=None,
        decision=None,
        result=None,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at=None,
    )


def test_call_state_is_closed_and_digest_bound():
    from aiddos.api.chat_tool_models import ToolCall

    call = call_record()
    assert ToolCall.model_validate(call).model_dump() == call
    for changes in (
        {"args_digest": "0" * 64},
        {"finished_at": call["started_at"]},
        {"status": "succeeded"},
        {"status": "uncertain"},
        {"unexpected": None},
    ):
        with pytest.raises(ValidationError):
            ToolCall.model_validate(call | changes)


def test_result_and_native_byte_limits_use_encoded_bytes():
    from aiddos.api.chat_tool_models import parse_arguments, validate_result

    with pytest.raises(ValueError):
        parse_arguments("configuration_read", " " * 16384 + '{"kind":"agent_profile"}')
    result = dict(
        kind="skill",
        draft_revision=0,
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
    assert len(encoded(result)) > 32768
    with pytest.raises(ValueError):
        validate_result(result)


def test_requested_write_cannot_carry_proposal_or_decision():
    from aiddos.api.chat_tool_models import ToolCall, digest, proposal_digest

    call = call_record()
    args = dict(expected_draft_revision=0, name="New", skill_ids=[])
    call.update(tool="agent_profile_update", arguments=args, args_digest=digest(args))
    proposal = dict(
        expected_draft_revision=0,
        before=dict(resource_id="agent-profile", name="Old", skill_ids=[]),
        after=dict(resource_id="agent-profile", name="New", skill_ids=[]),
        expires_at="2026-01-01T00:02:00+00:00",
    )
    proposal["digest"] = proposal_digest(call["id"], call["grant_id"], proposal)
    with pytest.raises(ValidationError):
        ToolCall.model_validate(call | {"proposal": proposal})


def test_explicit_denial_requires_matching_deny_decision():
    from aiddos.api.chat_tool_models import ToolCall

    call = call_record()
    call.update(status="denied", error_code="CHAT_TOOL_DENIED", finished_at=call["started_at"])
    with pytest.raises(ValidationError):
        ToolCall.model_validate(call)


def test_runtime_companion_is_closed_and_boolean_literals_are_strict():
    from aiddos.api.chat_tool_models import ToolRuntime

    value = dict(
        schema_version=1,
        mode="operator_approved_settings",
        supported=True,
        reason=None,
        tools=["configuration_read", "agent_profile_update"],
        max_calls=3,
        max_writes=1,
        requires_write_approval=True,
    )
    assert ToolRuntime.model_validate(value).model_dump() == value
    for mutation in (
        {"supported": False},
        {"max_writes": True},
        {"requires_write_approval": 1},
        {"tools": []},
    ):
        with pytest.raises(ValidationError):
            ToolRuntime.model_validate(value | mutation)
