"""Original-clock, exact CAS and terminal fact controls over real HTTP."""

import json
import threading
import time
from uuid import uuid4

import pytest
from test_chat_integration import wait_turn
from test_chat_tool_routes_controls import waiting
from test_chat_tool_routes_runtime import approve, companion, grant_turn
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.models import AgentProfileInput


@pytest.mark.parametrize(
    "position,action", [("before", "timeout"), ("after", "stop"), ("after", "timeout")]
)
def test_native_settlement_preserves_actual_outcome(tmp_path, monkeypatch, position, action):
    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (product, provider, saved, before):
        if action == "timeout":
            product.runtime.turn_seconds = 0.5
        original = product.runtime.draft._write
        fired = []

        def pause(state, *, publication_guard=None):
            if position == "before":

                def guard():
                    fired.append(True)
                    entered.set()
                    assert release.wait(4)
                    publication_guard()

                return original(state, publication_guard=guard)
            result = original(state, publication_guard=publication_guard)
            fired.append(True)
            entered.set()
            assert release.wait(4)
            return result

        monkeypatch.setattr(product.runtime.draft, "_write", pause)
        grant, turn, _ = grant_turn(product, saved)
        approve(product, waiting(product, turn))
        assert entered.wait(2)
        try:
            if action == "stop":
                product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
            else:
                time.sleep(0.6)
            assert product.runtime.active == turn["id"]
            assert product.runtime.worker.busy
            assert product.request(f"/api/v1/chat/turns/{turn['id']}")[1]["status"] not in {
                "failed",
                "cancelled",
                "succeeded",
            }
        finally:
            release.set()
        final = wait_turn(product, turn)
        assert final["error_code"] == (
            "CHAT_TIMEOUT" if action == "timeout" else "CHAT_CANCELLED"
        ), final
        call = companion(product, turn)["calls"][0]
        assert call["status"] == ("failed" if position == "before" else "succeeded"), call
        if position == "before":
            assert call["error_code"] == "CHAT_TIMEOUT"
        assert json.loads(product.state.read_text())["audit_total"] == before["audit_total"] + (
            position == "after"
        )
        assert fired == [True] and len(provider.requests) == 1


@pytest.mark.parametrize("aba", [False, True])
def test_manual_revision_change_is_not_rebased(tmp_path, aba):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        draft = product.runtime.draft
        draft.save_agent_profile(AgentProfileInput(name="manual", skill_ids=[], mcp_server_ids=[]))
        if aba:
            draft.save_agent_profile(
                AgentProfileInput(
                    name=before["agent_profile"]["name"], skill_ids=[], mcp_server_ids=[]
                )
            )
        written = product.state.read_bytes()
        approve(product, call)
        assert wait_turn(product, turn)["status"] == "succeeded"
        outcome = companion(product, turn)["calls"][0]
        assert outcome["status"] == "conflict" and outcome["error_code"] == "CHAT_TOOL_CONFLICT"
        assert product.state.read_bytes() == written
        assert len(provider.requests) == 2
        assert (
            json.loads(provider.requests[-1]["body"]["messages"][-1]["content"])["error_code"]
            == "CHAT_TOOL_CONFLICT"
        )


def test_original_proposal_deadline_expires_without_followup(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        product.runtime.turn_seconds = 0.35
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        final = wait_turn(product, turn, timeout=2)
        assert final["error_code"] == "CHAT_TIMEOUT"
        result = companion(product, turn)["calls"][0]
        assert result["status"] == "failed" and result["decision"] is None
        body = {
            "request_id": str(uuid4()),
            "proposal_digest": call["proposal"]["digest"],
            "decision": "approve",
        }
        assert (
            product.request(f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body)[0]
            == 409
        )
        assert json.loads(product.state.read_text()) == before
        assert len(provider.requests) == 1


def test_original_grant_monotonic_expiry_bounds_approval_wait(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        request = {
            "request_id": str(uuid4()),
            "session_id": saved["id"],
            "turn_request_id": str(uuid4()),
            "expected_sequence": 0,
            "text": "rename",
        }
        status, grant = product.request("/api/v1/chat/tool-grants", "POST", request)
        assert status == 201
        # Simulate a grant created almost 300 seconds earlier, independent of UTC adjustment.
        product.on_loop(
            lambda: product.runtime.grant_deadlines.update({grant["id"]: time.monotonic() + 0.35})
        )
        value = {
            "request_id": request["turn_request_id"],
            "expected_sequence": 0,
            "text": "rename",
            "grant_id": grant["id"],
        }
        status, turn = product.request(
            f"/api/v1/chat/sessions/{saved['id']}/tool-turns", "POST", value
        )
        assert status == 202
        waiting(product, turn)
        final = wait_turn(product, turn, timeout=1.5)
        assert final["error_code"] == "CHAT_TIMEOUT"
        assert companion(product, turn)["calls"][0]["error_code"] == "CHAT_TIMEOUT"
        assert len(provider.requests) == 1
