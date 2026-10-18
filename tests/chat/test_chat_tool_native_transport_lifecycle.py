"""Ownership, cancellation and real socket idle timeout (no mocked provider)."""

import asyncio
from contextlib import aclosing

import httpx2
import pytest
from provider_fixture import ProviderFixture, Scenario
from test_chat_tool_native_transport import PAYLOAD, frame, native_wire, transport_class

from aiddos.api.errors import DraftError


def test_context_exit_closes_paused_response_before_iterator_is_closed(monkeypatch):
    responses = []
    send = httpx2.AsyncClient.send

    async def observed(client, *args, **kwargs):
        response = await send(client, *args, **kwargs)
        responses.append(response)
        return response

    monkeypatch.setattr(httpx2.AsyncClient, "send", observed)
    with ProviderFixture(
        [Scenario((frame({"content": "early"}), native_wire()), (0, 2))]
    ) as fixture:

        async def run():
            owner = transport_class()({"streaming": True}, fixture.base_url + "/chat/completions")
            stream = None
            try:
                async with owner:
                    stream = owner.round(PAYLOAD)
                    assert await anext(stream) == {"type": "text", "text": "early"}
                    assert len(responses) == 1 and not responses[0].is_closed
                assert responses[0].is_closed
                assert owner.closed and not owner.response_open
            finally:
                if stream is not None:
                    await stream.aclose()

        asyncio.run(run())
        fixture.wait_closed()
    assert fixture.opened == fixture.closed == 1


def test_concurrent_round_is_refused_without_a_second_request():
    with ProviderFixture(
        [Scenario((frame({"content": "early"}), native_wire()), (0, 2))]
    ) as fixture:

        async def run():
            async with (
                transport_class()(
                    {"streaming": True}, fixture.base_url + "/chat/completions"
                ) as owner,
                aclosing(owner.round(PAYLOAD)) as first,
            ):
                assert (await anext(first))["type"] == "text"
                with pytest.raises(DraftError) as exc:
                    async with aclosing(owner.round(PAYLOAD)) as second:
                        await asyncio.wait_for(anext(second), 0.25)
                assert exc.value.code == "CHAT_BUSY"
                assert owner.requests_started == 1 and owner.response_open

        asyncio.run(run())
        fixture.wait_closed()
        assert len(fixture.requests) == 1


def test_client_cannot_be_reentered_or_round_started_outside_context():
    async def run():
        owner = transport_class()({"streaming": True}, "http://127.0.0.1:1/v1/chat/completions")
        with pytest.raises(RuntimeError):
            await anext(owner.round(PAYLOAD))
        async with owner:
            with pytest.raises(RuntimeError):
                await owner.__aenter__()
        with pytest.raises(RuntimeError):
            await owner.__aenter__()
        with pytest.raises(RuntimeError):
            await anext(owner.round(PAYLOAD))
        assert owner.requests_started == 0 and owner.closed

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["cancel", "deadline", "iterator_close"])
def test_stop_closes_real_socket_without_terminal_call(mode):
    events = []
    with ProviderFixture(
        [Scenario((frame({"content": "early"}), native_wire()), (0, 2))]
    ) as fixture:

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                async with aclosing(owner.round(PAYLOAD)) as stream:
                    events.append(await anext(stream))
                    if mode == "cancel":
                        task = asyncio.create_task(anext(stream))
                        await asyncio.sleep(0.03)
                        task.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await task
                    elif mode == "deadline":
                        with pytest.raises(TimeoutError):
                            async with asyncio.timeout(0.03):
                                await anext(stream)
                assert not owner.response_open and not owner.closed
            assert owner.closed

        asyncio.run(run())
        fixture.wait_closed()
        assert fixture.peer_closed >= 1
        assert len(fixture.requests) == 1
    assert events == [{"type": "text", "text": "early"}]


def test_native_call_is_not_emitted_while_done_or_http_eof_is_pending():
    wire = native_wire()
    with ProviderFixture([Scenario((wire, b": after done\n\n"), (0, 2))]) as fixture:

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                async with aclosing(owner.round(PAYLOAD)) as stream:
                    assert (await anext(stream))["type"] == "text"
                    with pytest.raises(TimeoutError):
                        async with asyncio.timeout(0.03):
                            await anext(stream)
                assert not owner.response_open

        asyncio.run(run())
        fixture.wait_closed()


def test_real_thirty_second_idle_read_timeout_closes_response_without_retry():
    events = []
    with ProviderFixture(
        [Scenario((frame({"content": "early"}), native_wire()), (0, 34))]
    ) as fixture:

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                with pytest.raises(DraftError) as exc:
                    async for event in owner.round(PAYLOAD):
                        events.append(event)
                assert exc.value.code == "CHAT_TIMEOUT"
                assert not owner.response_open and not owner.closed
                assert owner.requests_started == 1
            assert owner.closed

        asyncio.run(run())
        fixture.wait_closed()
        assert len(fixture.requests) == 1 and fixture.peer_closed >= 1
    assert events == [{"type": "text", "text": "early"}]
