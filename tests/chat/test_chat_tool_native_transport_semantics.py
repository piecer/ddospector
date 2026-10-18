"""Adversarial native wire semantics, never a synthetic domain executor."""

import asyncio

import pytest
from provider_fixture import ProviderFixture, Scenario
from test_chat_tool_native_transport import (
    PAYLOAD,
    completion_wire,
    frame,
    native_wire,
    transport_class,
)

from aiddos.api.chat_models import encoded
from aiddos.api.encoding import strict_json
from aiddos.api.errors import DraftError


def read_wire(wire, *, streaming=True, tools=True, code=None):
    events = []
    with ProviderFixture(
        [Scenario((wire,), content_type=("text/event-stream" if streaming else "application/json"))]
    ) as fixture:

        async def run():
            async with transport_class()(
                {"streaming": streaming}, fixture.base_url + "/chat/completions"
            ) as owner:
                async for event in owner.round(PAYLOAD if tools else {"stream": streaming}):
                    events.append(event)

        if code:
            with pytest.raises(DraftError) as exc:
                asyncio.run(run())
            assert exc.value.code == code
            assert all(event["type"] == "text" for event in events)
        else:
            asyncio.run(run())
        fixture.wait_closed()
        assert len(fixture.requests) == 1
    assert fixture.opened == fixture.closed == 1
    return events


@pytest.mark.parametrize("streaming", [True, False])
def test_final_request_omitting_tools_refuses_native_call(streaming):
    read_wire(
        native_wire() if streaming else completion_wire(),
        streaming=streaming,
        tools=False,
        code="CHAT_TOOL_PROTOCOL",
    )


@pytest.mark.parametrize("content", [False, 0, [], {}, "bad\x00", "bad\ud800"])
@pytest.mark.parametrize("streaming", [True, False])
def test_non_string_or_invalid_text_is_not_silently_empty(content, streaming):
    import json

    if streaming:
        wire = (
            b"data: "
            + json.dumps(
                {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": "stop"}]}
            ).encode()
            + b"\n\ndata: [DONE]\n\n"
        )
    else:
        wire = json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()
    read_wire(wire, streaming=streaming, code="CHAT_TOOL_PROTOCOL")


@pytest.mark.parametrize("identifier", ["", "x" * 129, "한", "a\x00b"])
def test_provider_id_is_bounded_ascii(identifier):
    read_wire(native_wire(identifier=identifier), code="CHAT_TOOL_PROTOCOL")


@pytest.mark.parametrize(
    "arguments",
    ["{", "[]", "null", '{"k":1,"k":2}', '{"x":NaN}', '{"x":' + "[" * 33 + "0" + "]" * 33 + "}"],
)
@pytest.mark.parametrize("streaming", [True, False])
def test_incomplete_duplicate_non_object_or_nonfinite_arguments(arguments, streaming):
    read_wire(
        native_wire(arguments) if streaming else completion_wire(arguments=arguments),
        streaming=streaming,
        code="CHAT_TOOL_PROTOCOL",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "parallel",
        "index",
        "index_bool",
        "legacy",
        "unknown",
        "extra_call",
        "extra_function",
        "missing_type",
        "missing_id",
        "bad_type",
        "args_type",
        "finish_stop",
        "finish_length",
        "null_calls",
    ],
)
@pytest.mark.parametrize("streaming", [True, False])
def test_native_structure_is_strict(mutation, streaming):
    obj = strict_json(completion_wire())
    choice = obj["choices"][0]
    message = choice["message"]
    call = message["tool_calls"][0]
    if mutation == "parallel":
        message["tool_calls"].append(dict(call))
    elif mutation == "index":
        choice["index"] = 1
    elif mutation == "index_bool":
        choice["index"] = False
    elif mutation == "legacy":
        message["function_call"] = {}
    elif mutation == "unknown":
        call["function"]["name"] = "arbitrary_shell"
    elif mutation == "extra_call":
        call["unrecognized"] = True
    elif mutation == "extra_function":
        call["function"]["unrecognized"] = True
    elif mutation == "missing_type":
        del call["type"]
    elif mutation == "missing_id":
        del call["id"]
    elif mutation == "bad_type":
        call["type"] = "shell"
    elif mutation == "args_type":
        call["function"]["arguments"] = {}
    elif mutation == "finish_stop":
        choice["finish_reason"] = "stop"
    elif mutation == "finish_length":
        choice["finish_reason"] = "length"
    elif mutation == "null_calls":
        message["tool_calls"] = None
    if streaming:
        for item in message["tool_calls"] or []:
            item["index"] = 0
        choice["delta"] = choice.pop("message")
        wire = b"data: " + encoded(obj) + b"\n\ndata: [DONE]\n\n"
    else:
        wire = encoded(obj)
    read_wire(wire, streaming=streaming, code="CHAT_TOOL_PROTOCOL")


@pytest.mark.parametrize(
    "suffix",
    [
        b"",
        b"data: [DONE]\n\ndata: [DONE]\n\n",
        b"data: [DONE]\n\ntrailing",
        b"data: [DONE]\n\n" + frame({}),
        frame({}, "tool_calls") + b"data: [DONE]\n\n",
    ],
)
def test_sse_terminal_must_be_unique_complete_and_at_end(suffix):
    wire = native_wire().removesuffix(b"data: [DONE]\n\n") + suffix
    read_wire(wire, code="CHAT_TOOL_PROTOCOL")


@pytest.mark.parametrize(
    "wire",
    [
        b"data: \xff\n\n",
        b'data: {"choices":[],"choices":[]}\n\n',
        b'data: {"choices":[null]}\n\n',
        b"data: [DONE]\n\n",
    ],
)
def test_strict_wire_decoding(wire):
    read_wire(wire, code="CHAT_TOOL_PROTOCOL")


@pytest.mark.parametrize("arguments", ['{"x":"\\ud800"}', '{"x":1e999}', '{"x":-1e999}'])
@pytest.mark.parametrize("streaming", [True, False])
def test_arguments_require_encodable_finite_parsed_json(arguments, streaming):
    read_wire(
        native_wire(arguments) if streaming else completion_wire(arguments=arguments),
        streaming=streaming,
        code="CHAT_TOOL_PROTOCOL",
    )


@pytest.mark.parametrize("index", [0, 1, False])
def test_nonstream_does_not_repair_extra_native_index(index):
    obj = strict_json(completion_wire())
    obj["choices"][0]["message"]["tool_calls"][0]["index"] = index
    read_wire(encoded(obj), streaming=False, code="CHAT_TOOL_PROTOCOL")


def test_fragmented_id_name_and_arguments_and_known_update_tool():
    wire = (
        frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "type": "function",
                        "id": "call-",
                        "function": {"name": "agent_", "arguments": " {"},
                    }
                ]
            }
        )
        + frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "1",
                        "function": {"name": "profile_update", "arguments": '"name":"🌍"} '},
                    }
                ]
            }
        )
        + frame({}, "tool_calls")
        + b"data: [DONE]\n\n"
    )
    assert read_wire(wire) == [
        {
            "type": "call",
            "id": "call-1",
            "name": "agent_profile_update",
            "arguments": ' {"name":"🌍"} ',
        },
        {"type": "finish", "reason": "tool_calls"},
    ]
