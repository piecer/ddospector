"""Strict selected native vocabulary; default legacy vocabulary is unchanged."""

import pytest
from test_chat_scenario_proposal_runtime import native_bytes

from aiddos.api.chat_tool_models import ScenarioAssistantCall
from aiddos.api.chat_tool_transport import NativeParser
from aiddos.api.errors import DraftError


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
@pytest.mark.parametrize("streaming", [False, True])
def test_selected_parser_retains_exact_native_tokens(operation, streaming):
    raw = ' { "kind" : "scenario_context" } '
    parser = NativeParser(tool_names=("configuration_read", operation))
    wire = native_bytes("configuration_read", raw, "call-1", streaming)
    events = []
    if streaming:
        for byte in wire:
            events.extend(parser.feed(bytes([byte])))
        events.extend(parser.end())
    else:
        events = parser.completion(wire)
    assert events[-2] == dict(type="call", id="call-1", name="configuration_read", arguments=raw)
    assert events[-1] == dict(type="finish", reason="tool_calls")


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
@pytest.mark.parametrize(
    "foreign", ["agent_profile_update", "target_create", "skill_create", "other_scenario"]
)
@pytest.mark.parametrize("streaming", [False, True])
def test_selected_parser_rejects_foreign_vocabulary(operation, foreign, streaming):
    if foreign == "other_scenario":
        foreign = "scenario_append" if operation == "scenario_create" else "scenario_create"
    parser = NativeParser(tool_names=("configuration_read", operation))
    wire = native_bytes(foreign, "{}", "call-1", streaming)
    with pytest.raises(DraftError, match="CHAT_TOOL_PROTOCOL"):
        if streaming:
            list(parser.feed(wire))
            parser.end()
        else:
            parser.completion(wire)


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_legacy_default_and_text_only_round_still_deny_scenario(operation):
    wire = native_bytes(operation, "{}", "call-1", False)
    for parser in (
        NativeParser(),
        NativeParser(tool_names=("configuration_read", operation), allow_tools=False),
    ):
        with pytest.raises(DraftError, match="CHAT_TOOL_PROTOCOL"):
            parser.completion(wire)


@pytest.mark.parametrize(
    "raw",
    [
        '{"kind":"scenario_context","kind":"scenario_context"}',
        '{"kind":"scenarios","offset":0.0,"limit":1}',
        '{"kind":"scenarios","offset":0e0,"limit":1}',
        '{"kind":"scenario_context","extra":null}',
        '{"kind":"scenarios","offset":false,"limit":1}',
        '{"kind":"scenarios","offset":0,"limit":1.5}',
    ],
)
def test_strict_native_argument_model_rejects_original_tokens(raw):
    message = dict(
        role="assistant",
        content="",
        tool_calls=[
            dict(id="c", type="function", function=dict(name="configuration_read", arguments=raw))
        ],
    )
    with pytest.raises(ValueError):
        ScenarioAssistantCall.model_validate(message)


def test_argument_and_frame_budgets_are_not_enlarged():
    parser = NativeParser(tool_names=("configuration_read", "scenario_create"))
    raw = '{"kind":"scenario_context"}'
    raw += " " * (16384 - len(raw))
    wire = native_bytes("configuration_read", raw, "c", False)
    assert parser.completion(wire)[-2]["arguments"] == raw
    with pytest.raises(DraftError, match="CHAT_TOOL_PROTOCOL"):
        NativeParser(tool_names=("configuration_read", "scenario_create")).completion(
            native_bytes("configuration_read", raw + " ", "c", False)
        )
    with pytest.raises(DraftError, match="CHAT_OUTPUT_LIMIT"):
        list(NativeParser(tool_names=("configuration_read", "scenario_create")).feed(b":" * 65537))
