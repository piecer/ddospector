"""Provider object parameters retain the closed, discriminator-selected ingress."""

import json
from pathlib import Path

import pytest
from provider_fixture import Scenario
from pydantic import TypeAdapter, ValidationError
from test_chat_integration import wait_turn
from test_chat_tool_native_transport import native_wire
from test_chat_tool_routes_runtime import companion, grant_turn
from test_chat_tool_runtime_lifecycle import world

from aiddos.api import chat_tool_models, chat_tool_runtime, chat_tool_transport
from aiddos.api.chat_tool_models import ReadArguments, UpdateArguments, parse_arguments
from aiddos.api.chat_tool_runtime import schemas
from aiddos.api.chat_tool_transport import NativeParser

# Exact malformed arguments observed in the captured diagnostic response, not
# an accepted alternate spelling. The earlier missing response remains unknown.
CAPTURED_ARGUMENTS = {"AgentRead": '{"kind": "agent_profile"}'}


def test_read_parameters_are_explicit_object_with_direct_properties():
    parameters = schemas()[0]["function"]["parameters"]
    assert parameters.get("type") == "object"
    assert set(parameters["properties"]) == {"kind", "id", "offset", "limit"}
    assert parameters["properties"]["kind"] == {
        "type": "string",
        "enum": ["agent_profile", "skills", "skill"],
    }
    assert parameters["required"] == ["kind"]
    assert parameters["additionalProperties"] is False
    assert len(parameters["oneOf"]) == 3
    exported = json.dumps(parameters)
    for internal in ("$defs", "$ref", "discriminator", "AgentRead", "SkillsRead", "SkillRead"):
        assert internal not in exported


def test_captured_wrapper_passes_native_parser_but_remains_rejected_at_ingress():
    parser = NativeParser()
    list(parser.feed(native_wire(json.dumps(CAPTURED_ARGUMENTS))))
    call, finish = parser.end()
    assert finish == {"type": "finish", "reason": "tool_calls"}
    assert json.loads(call["arguments"]) == CAPTURED_ARGUMENTS
    with pytest.raises(ValidationError) as caught:
        parse_arguments(call["name"], call["arguments"])
    assert [error["type"] for error in caught.value.errors()] == ["union_tag_not_found"]


def test_inlined_branches_preserve_all_original_validation_keywords():
    original = TypeAdapter(ReadArguments).json_schema()
    exported = schemas()[0]["function"]["parameters"]
    assert set(original) == {"$defs", "discriminator", "oneOf"}
    expected = [
        {
            key: value
            for key, value in original["$defs"][ref["$ref"].split("/")[-1]].items()
            if key != "title"
        }
        for ref in original["oneOf"]
    ]
    assert exported["oneOf"] == expected

    # Structural implication, not a sampled validator: every old branch implies
    # each added root constraint. Combined with unchanged oneOf above, this
    # proves equality of the schema languages without adding jsonschema.
    assert set(exported) == {"type", "properties", "required", "additionalProperties", "oneOf"}
    assert set(exported["properties"]) == set().union(*(b["properties"] for b in expected))
    for branch in expected:
        assert branch["type"] == exported["type"] == "object"
        assert branch["additionalProperties"] is exported["additionalProperties"] is False
        assert set(exported["required"]) <= set(branch["required"])
        for name, constraint in branch["properties"].items():
            root_constraint = exported["properties"][name]
            if name == "kind":
                assert set(constraint) == {"const", "type", "title"}
                assert constraint["type"] == root_constraint["type"] == "string"
                assert constraint["const"] in root_constraint["enum"]
            else:
                assert constraint == root_constraint


def test_update_schema_serialization_is_unchanged():
    expected = {
        "type": "function",
        "function": {
            "name": "agent_profile_update",
            "parameters": UpdateArguments.model_json_schema(),
        },
    }
    assert json.dumps(schemas()[1]) == json.dumps(expected)


def test_mutating_an_export_cannot_change_next_export_or_ingress():
    baseline = schemas()
    changed = schemas()
    parameters = changed[0]["function"]["parameters"]
    parameters["properties"]["kind"]["enum"].append("invented")
    parameters["properties"]["limit"]["maximum"] = 1000
    parameters["oneOf"][0]["additionalProperties"] = True
    parameters["oneOf"][1]["required"].clear()
    changed[1]["function"]["parameters"]["required"].clear()
    assert schemas() == baseline
    with pytest.raises(ValueError):
        parse_arguments("configuration_read", '{"kind":"skills","offset":0,"limit":11}')


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "agent_profile"},
        {"kind": "skills", "offset": 0, "limit": 1},
        {"kind": "skills", "offset": 103, "limit": 10},
        {"kind": "skills", "offset": 52, "limit": 5},
        {"kind": "skill", "id": "a"},
        {"kind": "skill", "id": "a" * 64},
        {"kind": "skill", "id": "literal-id-09"},
    ],
)
def test_read_ingress_accepts_only_direct_valid_arguments(value):
    assert parse_arguments("configuration_read", json.dumps(value)) == value


@pytest.mark.parametrize(
    "value",
    [
        {},
        None,
        [],
        "agent_profile",
        {"kind": None},
        {"kind": 1},
        {"kind": "unknown"},
        {"kind": "skill"},
        {"kind": "skills"},
        {"kind": "skills", "offset": 0},
        {"kind": "skills", "limit": 1},
        {"kind": "agent_profile", "id": "a"},
        {"kind": "agent_profile", "offset": 0},
        {"kind": "agent_profile", "limit": 1},
        {"kind": "skill", "id": "a", "offset": 0},
        {"kind": "skill", "id": "a", "limit": 1},
        {"kind": "skills", "offset": 0, "limit": 1, "id": "a"},
        *[
            {"kind": "skills", "offset": bad, "limit": 1}
            for bad in (-1, 104, True, 0.0, 0.5, "0", None, [], {})
        ],
        *[
            {"kind": "skills", "offset": 0, "limit": bad}
            for bad in (0, 11, True, 1.0, 1.5, "1", None, [], {})
        ],
        *[
            {"kind": "skill", "id": bad}
            for bad in ("", "a" * 65, "UPPER", "a b", "a/b", "한", 1, True, None, [], {})
        ],
        *[
            value | {"extra": None}
            for value in (
                {"kind": "agent_profile"},
                {"kind": "skills", "offset": 0, "limit": 1},
                {"kind": "skill", "id": "a"},
            )
        ],
        CAPTURED_ARGUMENTS,
        {"AgentRead": {"kind": "agent_profile"}},
        {"kind": "agent_profile", **CAPTURED_ARGUMENTS},
    ],
)
def test_read_ingress_rejects_missing_cross_kind_type_bound_and_extra_fields(value):
    with pytest.raises(ValueError):
        parse_arguments("configuration_read", json.dumps(value))


@pytest.mark.parametrize("malformed", [False, True])
def test_actual_request_uses_object_export_and_wrapper_never_becomes_call(
    tmp_path, malformed, record_property
):
    root = Path(__file__).resolve().parents[2]
    for module in (chat_tool_runtime, chat_tool_models, chat_tool_transport):
        origin = Path(module.__file__).resolve()
        assert origin == root / "src/aiddos/api" / (module.__name__.split(".")[-1] + ".py")
        record_property(module.__name__, str(origin))
    record_property("test_origin", str(Path(__file__).resolve()))
    with world(tmp_path, read=True) as (product, provider, saved, before):
        if malformed:
            provider.scenarios = (Scenario((native_wire(json.dumps(CAPTURED_ARGUMENTS)),)),)
        _, turn, _ = grant_turn(product, saved)
        final = wait_turn(product, turn)
        sent = provider.requests[0]["body"]["tools"]
        assert sent == schemas()
        assert sent[0]["function"]["parameters"]["type"] == "object"
        calls = companion(product, turn, lambda _: True)["calls"]
        if malformed:
            assert final["status"] == "failed"
            assert final["error_code"] == "CHAT_TOOL_PROTOCOL"
            assert calls == []
            assert len(provider.requests) == 1
        else:
            assert final["status"] == "succeeded"
            assert len(calls) == 1 and calls[0]["status"] == "succeeded"
            assert calls[0]["arguments"] == {"kind": "agent_profile"}
            assert len(provider.requests) == 2
        assert json.loads(product.state.read_text()) == before
    assert provider.server.socket.fileno() == -1 and not provider.thread.is_alive()
    assert provider.opened == provider.closed == len(provider.requests)
