"""Owned real loopback API fixtures and cancellation barriers."""

import asyncio
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx2
import uvicorn
from provider_fixture import ProviderFixture, Scenario
from test_chat_integration import session, wait_turn
from test_chat_tool_native_transport import native_wire
from test_chat_tool_routes_runtime import approve, companion, grant_turn

from aiddos.api.app import create_app


class LiveProduct:
    def __init__(self, directory):
        self.directory = directory
        self.state = directory / "draft.json"
        self.app = create_app(state_path=self.state)
        self.runtime = self.app.state.chat
        owner = self

        class Server(uvicorn.Server):
            async def serve(self, sockets=None):
                owner.loop = asyncio.get_running_loop()
                await super().serve(sockets)

        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.base = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = Server(uvicorn.Config(self.app, log_level="error", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]})
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.server.started
        self.resource_path = directory / f"api-resource-{uuid4()}.json"
        self.resource = {
            "pid": os.getpid(),
            "start_ticks": Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19],
            "thread_native_id": self.thread.native_id,
            "endpoint": self.base,
            "cleanup_verified": False,
        }
        self.resource_path.write_text(json.dumps(self.resource))

    def request(self, path, method="GET", body=None, timeout=3):
        with httpx2.Client(trust_env=False, timeout=timeout) as client:
            response = client.request(method, self.base + path, json=body)
            return response.status_code, response.json()

    def on_loop(self, operation):
        async def run():
            return operation()

        return asyncio.run_coroutine_threadsafe(run(), self.loop).result(3)

    def close(self):
        self.server.should_exit = True
        self.thread.join(8)
        assert not self.thread.is_alive()
        assert self.socket.fileno() == -1
        self.resource["cleanup_verified"] = True
        self.resource_path.write_text(json.dumps(self.resource))


@contextmanager
def world(tmp_path, *, read=False, streaming=True):
    product = LiveProduct(tmp_path)
    try:
        with ProviderFixture([Scenario.text("unused")]) as provider:
            saved = session(product, provider, streaming=streaming)
            before = json.loads(product.state.read_text())
            raw = json.dumps(
                {
                    "expected_draft_revision": before["audit_total"],
                    "name": "Approved",
                    "skill_ids": before["agent_profile"]["skill_ids"],
                }
            )
            provider.scenarios = (
                (
                    Scenario((native_wire(),))
                    if read
                    else Scenario((native_wire(raw, name="agent_profile_update"),))
                ),
                Scenario.text("Saved."),
            )
            yield product, provider, saved, before
    finally:
        product.close()
        if "provider" in locals():
            receipt = {
                "endpoint": provider.base_url,
                "requests": len(provider.requests),
                "opened": provider.opened,
                "closed": provider.closed,
                "thread_alive": provider.thread.is_alive(),
                "listener_fd": provider.server.socket.fileno(),
            }
            (tmp_path / "provider-cleanup.json").write_text(json.dumps(receipt))


def test_blocked_prereplace_runtime_busy_and_stop_no_replace(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (product, provider, saved, before):
        draft = product.runtime.draft
        original = draft._write
        fired = []

        def paused(state, *, publication_guard=None):
            def gate():
                fired.append(True)
                entered.set()
                assert release.wait(5)
                publication_guard()

            return original(state, publication_guard=gate)

        monkeypatch.setattr(draft, "_write", paused)
        grant, turn, _ = grant_turn(product, saved)
        call = companion(
            product, turn, lambda t: t["calls"] and t["calls"][0]["status"] == "awaiting_approval"
        )["calls"][0]
        approve(product, call)
        assert entered.wait(3)
        try:
            start = time.monotonic()
            status, body = product.request("/api/v1/chat/runtime", timeout=0.5)
            assert status == 429 and body["code"] == "CHAT_BUSY"
            assert time.monotonic() - start < 0.5
            status, stopped = product.request(
                f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {}, timeout=0.5
            )
            assert status == 200 and stopped["status"] == "cancel_requested"
            assert product.runtime.stop_signal.is_set()
            assert product.runtime.active == turn["id"]
            assert product.request(f"/api/v1/chat/turns/{turn['id']}")[1]["transport"] == "open"
        finally:
            release.set()
        final = wait_turn(product, turn)
        assert final["status"] == "cancelled"
        assert companion(product, turn)["calls"][0]["status"] == "cancelled"
        assert json.loads(product.state.read_text()) == before
        assert fired == [True]
        assert len(provider.requests) == 1


def test_cancelled_read_retains_turn_until_native_retirement(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path, read=True) as (product, provider, saved, before):
        draft = product.runtime.draft
        original = draft._read
        armed = threading.Event()

        def paused():
            if armed.is_set():
                entered.set()
                assert release.wait(5)
            return original()

        # Arm only the actual read tool, not admission metadata.
        original_read = product.runtime.worker.read_configuration

        async def read(*args, **kwargs):
            armed.set()
            return await original_read(*args, **kwargs)

        monkeypatch.setattr(product.runtime.worker, "read_configuration", read)
        monkeypatch.setattr(draft, "_read", paused)
        grant, turn, _ = grant_turn(product, saved)
        assert entered.wait(3)
        try:
            product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
            time.sleep(0.08)
            pending = product.request(f"/api/v1/chat/turns/{turn['id']}")[1]
            assert pending["status"] == "cancel_requested", pending
            assert pending["transport"] == "open"
            assert product.runtime.active == turn["id"]
            assert product.runtime.worker.busy
        finally:
            release.set()
        assert wait_turn(product, turn)["status"] == "cancelled"
        assert companion(product, turn)["calls"][0]["status"] == "cancelled"
        assert not product.runtime.storage.fenced
        assert len(provider.requests) == 1
