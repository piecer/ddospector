"""Runtime composition controls beyond the primary tracer."""

import json
import sqlite3
import threading
import time
from uuid import uuid4

from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_native_transport import completion_wire, native_wire
from test_chat_tool_routes_controls import uncertain, waiting
from test_chat_tool_routes_runtime import approve, companion, grant_turn
from test_chat_tool_runtime_lifecycle import world


def test_nonstream_read_final_context_real_transport(tmp_path):
    with world(tmp_path, streaming=False) as (product, provider, saved, before):
        provider.scenarios = (
            Scenario((completion_wire(),), content_type="application/json"),
            Scenario(
                (completion_wire(call=False, content="final"),), content_type="application/json"
            ),
        )
        grant, turn, _ = grant_turn(product, saved)
        assert wait_turn(product, turn)["status"] == "succeeded"
        assert companion(product, turn)["calls"][0]["status"] == "succeeded"
        assert len(provider.requests) == 2
        assert all(r["body"]["stream"] is False for r in provider.requests)
        assert json.loads(product.state.read_text()) == before


def test_fence_a_clear_a_fence_b_historic_replay_does_not_clear_current(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        turn_a = uncertain(product, provider, saved, monkeypatch)
        fence_a = product.request("/api/v1/chat/tools/fence")[1]
        body = {
            "request_id": str(uuid4()),
            "expected_generation": fence_a["generation"],
            "expected_draft_revision": fence_a["current_draft_revision"],
            "acknowledge_uncertain": True,
        }
        status, receipt = product.request("/api/v1/chat/tools/reconcile", "POST", body)
        assert status == 201
        revision = json.loads(product.state.read_text())["audit_total"]
        raw = json.dumps({"expected_draft_revision": revision, "name": "Second", "skill_ids": []})
        provider.scenarios = (
            provider.scenarios[0],
            Scenario((native_wire(raw, name="agent_profile_update"),)),
        )
        turn_b = uncertain(product, provider, saved, monkeypatch, sequence=1)
        fence_b = product.request("/api/v1/chat/tools/fence")[1]
        assert fence_b["generation"] == fence_a["generation"] + 2 and fence_b["fenced"]
        assert product.request("/api/v1/chat/tools/reconcile", "POST", body) == (200, receipt)
        assert product.request("/api/v1/chat/tools/fence")[1] == fence_b
        assert companion(product, turn_a)["calls"][0]["status"] == "uncertain"
        assert companion(product, turn_b)["calls"][0]["status"] == "uncertain"
        assert len(provider.requests) == 2


def test_shutdown_waits_for_published_native_receipt_before_closing_storage(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (product, provider, saved, before):
        draft = product.runtime.draft
        original = draft._write

        def paused(state, **kwargs):
            result = original(state, **kwargs)
            entered.set()
            assert release.wait(4)
            return result

        monkeypatch.setattr(draft, "_write", paused)
        grant, turn, _ = grant_turn(product, saved)
        approve(product, waiting(product, turn))
        assert entered.wait(2)
        product.server.should_exit = True
        try:
            deadline = time.monotonic() + 2
            while not product.runtime.stopping and time.monotonic() < deadline:
                time.sleep(0.01)
            assert product.runtime.stopping and product.runtime.stop_signal.is_set()
            assert product.thread.is_alive() and product.runtime.active == turn["id"]
        finally:
            release.set()
        product.thread.join(4)
        assert not product.thread.is_alive()
        with sqlite3.connect(product.runtime.storage.path) as db:
            record = json.loads(db.execute("SELECT data FROM tool_calls").fetchone()[0])["call"]
            final = json.loads(db.execute("SELECT data FROM turns").fetchone()[0])
        assert record["status"] == "succeeded"
        assert final["status"] == "interrupted" and final["transport"] == "closed"
        assert json.loads(product.state.read_text())["audit_total"] == before["audit_total"] + 1
        assert len(provider.requests) == 1
