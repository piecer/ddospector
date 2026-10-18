"""HTTP authority/replay, failure facts and current-fence controls."""

import json
import threading
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_routes_runtime import approve, companion, grant_turn
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.errors import DraftError
from aiddos.api.models import AgentProfileInput


def waiting(product, turn):
    return companion(
        product, turn, lambda t: t["calls"] and t["calls"][-1]["status"] == "awaiting_approval"
    )["calls"][-1]


def test_grant_lookup_revoke_and_approval_replay_first(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        assert product.request(f"/api/v1/chat/tool-grants/by-request/{grant['request_id']}") == (
            200,
            {**grant, "status": "consumed"},
        )
        call = waiting(product, turn)
        body, receipt = approve(product, call)
        assert wait_turn(product, turn)["status"] == "succeeded"
        assert (
            product.request(f"/api/v1/chat/tool-calls/{uuid4()}/decision", "POST", body)[1]["code"]
            == "CHAT_TOOL_APPROVAL_CONFLICT"
        )
        assert product.request(f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body) == (
            200,
            receipt,
        )
        status, revoked = product.request(
            f"/api/v1/chat/tool-grants/{grant['id']}/revoke", "POST", {}
        )
        assert status == 200 and revoked["status"] == "revoked"
        assert product.request(f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body) == (
            200,
            receipt,
        )
        assert len(provider.requests) == 2


def test_revoke_waiting_turn_never_writes(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        waiting(product, turn)
        status, value = product.request(
            f"/api/v1/chat/tool-grants/{grant['id']}/revoke", "POST", {}
        )
        assert status == 200 and value["status"] == "revoked"
        assert wait_turn(product, turn)["status"] == "cancelled"
        assert companion(product, turn)["calls"][0]["status"] == "cancelled"
        assert json.loads(product.state.read_text()) == before
        assert len(provider.requests) == 1


@pytest.mark.parametrize("fault", ["prepublication", "postpublication", "readback", "final_model"])
def test_real_failure_seams_preserve_operation_truth(tmp_path, monkeypatch, fault):
    with world(tmp_path) as (product, provider, saved, before):
        draft = product.runtime.draft
        write = draft._write
        fired = []
        if fault == "final_model":
            provider.scenarios = (provider.scenarios[0], Scenario((b"unavailable",), status=503))
        else:

            def fail(state, **kwargs):
                if fault == "prepublication":
                    fired.append(fault)
                    raise DraftError("STATE_UNAVAILABLE")
                write(state, **kwargs)
                if fault == "postpublication":
                    fired.append(fault)
                    raise DraftError("STATE_COMMIT_UNCERTAIN")
                original = draft._read

                def readback():
                    fired.append(fault)
                    monkeypatch.setattr(draft, "_read", original)
                    raise OSError("injected authoritative readback")

                monkeypatch.setattr(draft, "_read", readback)

            monkeypatch.setattr(draft, "_write", fail)
        grant, turn, _ = grant_turn(product, saved)
        approve(product, waiting(product, turn))
        final = wait_turn(product, turn)
        assert final["status"] == "failed", final
        call = companion(product, turn)["calls"][0]
        expected = {
            "prepublication": "failed",
            "postpublication": "uncertain",
            "readback": "uncertain",
            "final_model": "succeeded",
        }[fault]
        assert call["status"] == expected
        state = json.loads(product.state.read_text())
        assert state["audit_total"] == before["audit_total"] + (fault != "prepublication")
        if fault != "final_model":
            assert fired == [fault]
            assert len(provider.requests) == 1
        else:
            assert len(provider.requests) == 2
        status, fence = product.request("/api/v1/chat/tools/fence")
        assert status == 200, (status, fence)
        assert fence["fenced"] == (expected == "uncertain")
        assert fence["current_draft_revision"] == state["audit_total"]


def uncertain(product, provider, saved, monkeypatch, sequence=0):
    draft = product.runtime.draft
    original = draft._write
    fired = []

    def fail(state, **kwargs):
        original(state, **kwargs)
        fired.append(True)
        raise DraftError("STATE_COMMIT_UNCERTAIN")

    monkeypatch.setattr(draft, "_write", fail)
    grant, turn, _ = grant_turn(product, saved, sequence=sequence)
    approve(product, waiting(product, turn))
    assert wait_turn(product, turn)["error_code"] == "CHAT_TOOL_UNCERTAIN"
    monkeypatch.setattr(draft, "_write", original)
    assert fired == [True]
    return turn


def test_reconcile_holds_draft_lock_through_sqlite_on_owner_thread(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        turn = uncertain(product, provider, saved, monkeypatch)
        status, fence = product.request("/api/v1/chat/tools/fence")
        assert status == 200, (status, fence)
        ledger = product.runtime.ledger
        original = ledger.reconcile
        started, done = threading.Event(), threading.Event()
        threads, facts = [], []
        draft = product.runtime.draft

        def manual():
            started.set()
            draft.save_agent_profile(
                AgentProfileInput(name="manual after clear", skill_ids=[], mcp_server_ids=[])
            )
            done.set()

        def observe(body, **kwargs):
            if kwargs["owner_idle"]:
                thread = threading.Thread(target=manual)
                threads.append(thread)
                thread.start()
                assert started.wait(1)
                assert not done.wait(0.05), "legacy write escaped lock-held revision/clear boundary"
                facts.append(threading.get_ident() == product.loop._thread_id)
            return original(body, **kwargs)

        monkeypatch.setattr(ledger, "reconcile", observe)
        body = {
            "request_id": str(uuid4()),
            "expected_generation": fence["generation"],
            "expected_draft_revision": fence["current_draft_revision"],
            "acknowledge_uncertain": True,
        }
        status, receipt = product.request("/api/v1/chat/tools/reconcile", "POST", body)
        try:
            assert status == 201, (status, receipt)
        finally:
            for thread in threads:
                thread.join(3)
                assert not thread.is_alive()
        assert facts == [True] and done.is_set()
        assert product.request("/api/v1/chat/tools/reconcile", "POST", body) == (200, receipt)
        assert facts == [True]
        assert companion(product, turn)["calls"][0]["status"] == "uncertain"
        current = product.request("/api/v1/chat/tools/fence")[1]
        assert not current["fenced"] and current["generation"] == fence["generation"] + 1
        assert current["current_draft_revision"] == fence["current_draft_revision"] + 1


def test_reconcile_callback_failure_releases_native_lease(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        uncertain(product, provider, saved, monkeypatch)
        status, fence = product.request("/api/v1/chat/tools/fence")
        assert status == 200, (status, fence)
        original = product.runtime.ledger.reconcile
        fired = []

        def fail(body, **kwargs):
            if kwargs["owner_idle"]:
                fired.append(True)
                raise DraftError("CHAT_STORAGE_ERROR")
            return original(body, **kwargs)

        monkeypatch.setattr(product.runtime.ledger, "reconcile", fail)
        body = {
            "request_id": str(uuid4()),
            "expected_generation": fence["generation"],
            "expected_draft_revision": fence["current_draft_revision"],
            "acknowledge_uncertain": True,
        }
        assert (
            product.request("/api/v1/chat/tools/reconcile", "POST", body)[1]["code"]
            == "CHAT_STORAGE_ERROR"
        )
        assert fired == [True]
        assert product.request("/api/v1/chat/runtime")[0] == 200
        assert product.request("/api/v1/chat/tools/fence")[1] == fence
