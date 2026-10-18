"""Native wire tests use only invocation-owned ephemeral HTTP providers."""

import asyncio
import importlib.util

import httpx2
import pytest
from provider_fixture import ProviderFixture, Scenario

from aiddos.api.chat_models import encoded

ARGUMENTS = ' { "kind" : "agent_profile" } '
PAYLOAD = {"model": "fixture", "stream": True, "tools": [{"type": "function"}]}


def transport_class():
    name = "aiddos.api.chat_tool_transport"
    assert importlib.util.find_spec(name) is not None, "native ToolTransport is not implemented"
    return __import__(name, fromlist=["ToolTransport"]).ToolTransport


def frame(delta, finish=None):
    return (
        b"data: "
        + encoded({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})
        + b"\n\n"
    )


def native_wire(arguments=ARGUMENTS, *, name="configuration_read", identifier="call-1"):
    return (
        frame({"role": "assistant", "content": "검사 🌍"})
        + frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": identifier,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments[:9]},
                    }
                ]
            }
        )
        + frame({"tool_calls": [{"index": 0, "function": {"arguments": arguments[9:]}}]})
        + frame({}, "tool_calls")
        + b"data: [DONE]\n\n"
    )


def test_fragmented_native_call_is_preserved_and_response_closed_before_dispatch(monkeypatch):
    cls = transport_class()
    responses = []
    original = httpx2.Response.aclose

    async def observe_close(response):
        await original(response)
        responses.append(response)

    monkeypatch.setattr(httpx2.Response, "aclose", observe_close)
    wire = native_wire()
    with ProviderFixture([Scenario(tuple(bytes([b]) for b in wire))]) as fixture:

        async def run():
            async with cls({"streaming": True}, fixture.base_url + "/chat/completions") as owner:
                events = []
                async for event in owner.round(PAYLOAD):
                    if event["type"] != "text":
                        assert responses and all(response.is_closed for response in responses)
                    events.append(event)
                assert events == [
                    {"type": "text", "text": "검사 🌍"},
                    {
                        "type": "call",
                        "id": "call-1",
                        "name": "configuration_read",
                        "arguments": ARGUMENTS,
                    },
                    {"type": "finish", "reason": "tool_calls"},
                ]

        asyncio.run(run())
        fixture.wait_closed()
        assert fixture.requests == [{"path": "/v1/chat/completions", "body": PAYLOAD}]
    assert fixture.opened == fixture.closed == 1
    assert fixture.server.socket.fileno() == -1
    assert not fixture.thread.is_alive()


def completion_wire(*, call=True, content=None, arguments=ARGUMENTS):
    message = {"role": "assistant", "content": content}
    if call:
        message["tool_calls"] = [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "configuration_read", "arguments": arguments},
            }
        ]
    return encoded(
        {
            "choices": [
                {"index": 0, "message": message, "finish_reason": "tool_calls" if call else "stop"}
            ]
        }
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_one_client_across_native_and_final_text_rounds(streaming, monkeypatch):
    cls = transport_class()
    clients, responses = [], []
    client_enter, response_close = httpx2.AsyncClient.__aenter__, httpx2.Response.aclose

    async def entered(client):
        clients.append(client)
        return await client_enter(client)

    async def closed(response):
        await response_close(response)
        responses.append(response)

    monkeypatch.setattr(httpx2.AsyncClient, "__aenter__", entered)
    monkeypatch.setattr(httpx2.Response, "aclose", closed)
    wires = (
        [native_wire(), frame({"content": "done"}) + frame({}, "stop") + b"data: [DONE]\n\n"]
        if streaming
        else [completion_wire(), completion_wire(call=False, content="done")]
    )
    scenarios = [
        Scenario((wire,), content_type="text/event-stream" if streaming else "application/json")
        for wire in wires
    ]
    with ProviderFixture(scenarios) as fixture:

        async def run():
            async with cls(
                {"streaming": streaming}, fixture.base_url + "/chat/completions"
            ) as owner:
                first = [event async for event in owner.round({**PAYLOAD, "stream": streaming})]
                assert first[-2:] == [
                    {
                        "type": "call",
                        "id": "call-1",
                        "name": "configuration_read",
                        "arguments": ARGUMENTS,
                    },
                    {"type": "finish", "reason": "tool_calls"},
                ]
                assert len(clients) == 1 and not clients[0].is_closed
                assert responses and all(response.is_closed for response in responses)
                final = [event async for event in owner.round({"stream": streaming})]
                assert final == [
                    {"type": "text", "text": "done"},
                    {"type": "finish", "reason": "stop"},
                ]
                assert not clients[0].is_closed
            assert clients[0].is_closed

        asyncio.run(run())
        fixture.wait_closed(2)
        assert len(fixture.requests) == 2
    assert fixture.opened == fixture.closed == 2
