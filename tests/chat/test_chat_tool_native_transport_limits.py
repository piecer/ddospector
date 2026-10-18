"""Exact UTF-8/frame/body budget boundaries over owned HTTP and byte feeds."""

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
from test_chat_tool_native_transport_semantics import read_wire

from aiddos.api.errors import DraftError


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("extra", [0, 1])
def test_native_argument_utf8_limit(streaming, extra):
    prefix, suffix = '{"value":"', '"}'
    budget = 16384 - len((prefix + suffix).encode())
    arguments = prefix + "🌍" * (budget // 4) + "x" * (budget % 4 + extra) + suffix
    assert len(arguments.encode()) == 16384 + extra
    wire = native_wire(arguments) if streaming else completion_wire(arguments=arguments)
    events = read_wire(wire, streaming=streaming, code="CHAT_TOOL_PROTOCOL" if extra else None)
    if not extra:
        assert events[-2]["arguments"] == arguments


def padded_wire(size, streaming):
    if not streaming:
        wire = completion_wire(call=False, content="ok")
        return wire + b" " * (size - len(wire))
    terminal = frame({"content": "ok"}, "stop") + b"data: [DONE]\n\n"
    remaining = size - len(terminal)
    chunks = []
    while remaining > 60000:
        chunks.append(b":" + b"r" * 59997 + b"\n\n")
        remaining -= 60000
    assert remaining >= 3
    return b"".join(chunks) + b":" + b"r" * (remaining - 3) + b"\n\n" + terminal


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("extra", [0, 1])
def test_two_mib_is_cumulative_across_rounds(streaming, extra):
    wires = [padded_wire(1024 * 1024, streaming), padded_wire(1024 * 1024 + extra, streaming)]
    scenarios = [
        Scenario((w,), content_type="text/event-stream" if streaming else "application/json")
        for w in wires
    ]
    events = []
    with ProviderFixture(scenarios) as fixture:

        async def run():
            async with transport_class()(
                {"streaming": streaming}, fixture.base_url + "/chat/completions"
            ) as owner:
                assert [e async for e in owner.round(PAYLOAD)][-1]["reason"] == "stop"
                if extra:
                    with pytest.raises(DraftError) as exc:
                        async for event in owner.round(PAYLOAD):
                            events.append(event)
                    assert exc.value.code == "CHAT_OUTPUT_LIMIT"
                    assert not any(e["type"] == "finish" for e in events)
                else:
                    assert [e async for e in owner.round(PAYLOAD)][-1]["reason"] == "stop"
                assert owner.upstream_bytes == sum(map(len, wires))

        asyncio.run(run())
        fixture.wait_closed(2)
    assert fixture.opened == fixture.closed == 2


@pytest.mark.parametrize("separator", [b"\n\n", b"\r\n\r\n", b"\n\r\n", b"\r\n\n"])
@pytest.mark.parametrize("extra", [0, 1])
@pytest.mark.parametrize("split", [1, 4096, 65536, 65537, 70000])
def test_frame_limit_segmentation_invariant(separator, extra, split):
    from aiddos.api.chat_tool_transport import NativeParser

    raw = b":" + b"x" * (65535 + extra)
    wire = raw + separator + native_wire()
    parser = NativeParser()

    def parse():
        output = []
        for offset in range(0, len(wire), split):
            output.extend(parser.feed(wire[offset : offset + split]))
        return output + parser.end()

    if extra:
        with pytest.raises(DraftError) as exc:
            parse()
        assert exc.value.code == "CHAT_OUTPUT_LIMIT"
    else:
        assert parse()[-1] == {"type": "finish", "reason": "tool_calls"}


@pytest.mark.parametrize("extra", [0, 1])
def test_frame_limit_on_real_http(extra):
    read_wire(
        b":" + b"x" * (65535 + extra) + b"\r\n\r\n" + native_wire(),
        code="CHAT_OUTPUT_LIMIT" if extra else None,
    )


def test_pending_separator_overflow_at_eof():
    from aiddos.api.chat_tool_transport import NativeParser

    parser = NativeParser()
    assert list(parser.feed(b":" + b"x" * 65535 + b"\r")) == []
    with pytest.raises(DraftError) as exc:
        parser.end()
    assert exc.value.code == "CHAT_OUTPUT_LIMIT"


@pytest.mark.parametrize("extra", [0, 1])
def test_exact_id_limit_is_preserved(extra):
    events = read_wire(
        native_wire(identifier="a" * (128 + extra)), code="CHAT_TOOL_PROTOCOL" if extra else None
    )
    if not extra:
        assert events[-2]["id"] == "a" * 128
