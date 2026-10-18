"""Fresh draft admission and exact successful native history regression tests."""

import asyncio
import threading
import time
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_routes_controls import waiting
from test_chat_tool_routes_runtime import approve, companion, grant_turn
from test_chat_tool_runtime_lifecycle import world


@pytest.mark.parametrize("operation", ["session", "ordinary_turn"])
def test_ordinary_fresh_io_refuses_busy_worker_without_locking_loop(
    tmp_path, monkeypatch, operation
):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (product, provider, saved, before):
        original = product.runtime.draft.snapshot

        def blocked():
            entered.set()
            assert release.wait(4)
            return original()

        monkeypatch.setattr(product.runtime.draft, "snapshot", blocked)
        future = asyncio.run_coroutine_threadsafe(product.runtime.worker.snapshot(), product.loop)
        assert entered.wait(2)
        try:
            if operation == "session":
                body = {
                    "request_id": str(uuid4()),
                    "settings_revision": saved["settings_revision"],
                    "profile_id": saved["profile_id"],
                    "approved_endpoint": saved["endpoint"],
                    "locale": "ko",
                }
                path = "/api/v1/chat/sessions"
            else:
                body = {"request_id": str(uuid4()), "expected_sequence": 0, "text": "ordinary"}
                path = f"/api/v1/chat/sessions/{saved['id']}/turns"
            start = time.monotonic()
            status, response = product.request(path, "POST", body, timeout=0.5)
            assert status == 429 and response["code"] == "CHAT_BUSY"
            assert time.monotonic() - start < 0.5
        finally:
            release.set()
            future.result(3)
        assert not provider.requests


def test_prior_successful_native_exchanges_preserved_for_ordinary_turn(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        provider.scenarios = (*provider.scenarios, Scenario.text("ordinary final"))
        grant, turn, _ = grant_turn(product, saved)
        approve(product, waiting(product, turn))
        assert wait_turn(product, turn)["status"] == "succeeded"
        expected = product.on_loop(lambda: product.runtime.ledger.exchanges(turn["id"]))
        body = {"request_id": str(uuid4()), "expected_sequence": 1, "text": "followup"}
        status, ordinary = product.request(
            f"/api/v1/chat/sessions/{saved['id']}/turns", "POST", body
        )
        assert status == 202, (status, ordinary)
        assert wait_turn(product, ordinary)["status"] == "succeeded"
        payload = provider.requests[-1]["body"]
        assert "tools" not in payload
        assert payload["messages"][2:-1] == expected
        assert companion(product, ordinary, lambda t: True)["calls"] == []


def test_metadata_read_never_holds_async_publication_lock(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (product, provider, saved, before):
        original = product.runtime.draft.ai_snapshot

        def blocked():
            entered.set()
            assert release.wait(4)
            return original()

        monkeypatch.setattr(product.runtime.draft, "ai_snapshot", blocked)
        body = {
            "request_id": str(uuid4()),
            "settings_revision": saved["settings_revision"],
            "profile_id": saved["profile_id"],
            "approved_endpoint": saved["endpoint"],
            "locale": "ko",
        }
        errors = []

        def create():
            try:
                product.request("/api/v1/chat/sessions", "POST", body)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=create)
        thread.start()
        assert entered.wait(2)
        try:
            status, value = product.request("/api/v1/chat/sessions", timeout=0.5)
            assert status == 200, (status, value)
        finally:
            release.set()
            thread.join(4)
        assert not thread.is_alive() and not errors
