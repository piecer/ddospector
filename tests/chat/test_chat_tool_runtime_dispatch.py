"""No provider dispatch after an original deadline consumed in durable publication."""

import time

import httpx2
from test_chat_integration import wait_turn
from test_chat_tool_routes_runtime import companion, grant_turn
from test_chat_tool_runtime_lifecycle import world


def test_running_publication_latency_cannot_dispatch_after_deadline(tmp_path, monkeypatch):
    with world(tmp_path, read=True) as (product, provider, saved, before):
        product.runtime.turn_seconds = 0.12
        update = product.runtime.update
        send = httpx2.AsyncClient.send
        fired, attempts = [], []

        def delayed(turn_id, **kwargs):
            value = update(turn_id, **kwargs)
            if kwargs.get("transport") == "open":
                fired.append(True)
                time.sleep(0.18)
            return value

        async def observe(client, request, *args, **kwargs):
            attempts.append(str(request.url))
            return await send(client, request, *args, **kwargs)

        monkeypatch.setattr(product.runtime, "update", delayed)
        monkeypatch.setattr(httpx2.AsyncClient, "send", observe)
        grant, turn, _ = grant_turn(product, saved)
        final = wait_turn(product, turn)
        assert final["error_code"] == "CHAT_TIMEOUT"
        assert fired == [True]
        assert attempts == [] and provider.requests == []
        assert companion(product, turn, lambda t: True)["calls"] == []
