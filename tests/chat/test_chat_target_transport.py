"""Native transport uses synthetic complete and streaming provider bytes."""

import pytest

from aiddos.api.chat_models import encoded
from aiddos.api.chat_tool_transport import NativeParser
from aiddos.api.errors import DraftError


@pytest.mark.parametrize("streaming", [False, True])
def test_target_native_transport_and_closed_tool_removal(streaming):
    args = '{ "expected_draft_revision":0,"name":"literal","address":"host","kind":"DUT" }'
    call = dict(
        id="synthetic-target", type="function", function=dict(name="target_create", arguments=args)
    )
    parser = NativeParser()
    if streaming:
        frame = encoded(
            dict(
                choices=[
                    dict(
                        index=0,
                        delta=dict(role="assistant", tool_calls=[call | {"index": 0}]),
                        finish_reason="tool_calls",
                    )
                ]
            )
        )
        wire = b"data: " + frame + b"\n\ndata: [DONE]\n\n"
        for byte in wire:
            assert list(parser.feed(bytes([byte]))) == []
        events = parser.end()
    else:
        wire = encoded(
            dict(
                choices=[
                    dict(
                        index=0,
                        message=dict(role="assistant", content="", tool_calls=[call]),
                        finish_reason="tool_calls",
                    )
                ]
            )
        )
        events = parser.completion(wire)
    assert events == [
        dict(type="call", id="synthetic-target", name="target_create", arguments=args),
        dict(type="finish", reason="tool_calls"),
    ]
    forbidden = NativeParser(allow_tools=False)
    with pytest.raises(DraftError) as exc:
        list(forbidden.feed(wire)) if streaming else forbidden.completion(wire)
    assert exc.value.code == "CHAT_TOOL_PROTOCOL"
