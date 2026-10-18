"""Owner metadata admission and callback-cancellation drain controls."""

import asyncio
import threading
import time
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_routes_runtime import grant_turn
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.store import DraftStore


def test_tool_owner_reserves_native_admission_across_provider_wait(tmp_path):
    with world(tmp_path, read=True) as (product, provider, saved, before):
        provider.scenarios = (Scenario.slow(),)
        grant, turn, _ = grant_turn(product, saved)
        wait_turn(product, turn, lambda t: bool(t["assistant_text"]))
        # No unrelated metadata lease can strand an already-armed writer later.
        status, value = product.request("/api/v1/chat/runtime")
        assert status == 429 and value["code"] == "CHAT_BUSY"
        assert product.request("/api/v1/chat/tools/runtime")[0] == 429
        status, fence = product.request("/api/v1/chat/tools/fence")
        assert status == 200 and fence["current_draft_revision"] is None
        body = {
            "request_id": str(uuid4()),
            "settings_revision": saved["settings_revision"],
            "profile_id": saved["profile_id"],
            "approved_endpoint": saved["endpoint"],
            "locale": "ko",
        }
        assert product.request("/api/v1/chat/sessions", "POST", body)[0] == 429
        product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
        assert wait_turn(product, turn)["status"] == "cancelled"
        assert product.request("/api/v1/chat/runtime")[0] == 200


def test_grant_monotonic_clock_precedes_sqlite_commit(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        ledger = product.runtime.ledger
        original = ledger.create_grant
        clocks = []

        def delayed(*args, **kwargs):
            clocks.append(time.monotonic())
            result = original(*args, **kwargs)
            time.sleep(0.08)
            return result

        monkeypatch.setattr(ledger, "create_grant", delayed)
        body = {
            "request_id": str(uuid4()),
            "session_id": saved["id"],
            "turn_request_id": str(uuid4()),
            "expected_sequence": 0,
            "text": "next",
        }
        status, grant = product.request("/api/v1/chat/tool-grants", "POST", body)
        assert status == 201
        assert product.runtime.grant_deadlines[grant["id"]] <= clocks[0] + 300


def test_locked_revision_cancellation_has_no_late_callback_or_stranded_lease(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "bridge.json")
    entered, release = threading.Event(), threading.Event()
    original = draft._read
    calls = []

    def blocked():
        entered.set()
        assert release.wait(4)
        return original()

    monkeypatch.setattr(draft, "_read", blocked)

    async def run():
        worker = DomainWorker(draft)
        try:
            task = asyncio.create_task(
                worker.locked_revision(lambda revision: calls.append(revision))
            )
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and worker.busy
            with pytest.raises(DraftError, match="CHAT_BUSY"):
                await worker.snapshot()
            release.set()
            with pytest.raises(DraftError, match="CHAT_CANCELLED"):
                await task
            assert not worker.busy and calls == []
            assert await worker.locked_revision(lambda revision: revision) == 0
        finally:
            release.set()
            await worker.shutdown()

    asyncio.run(run())
