"""Real HTTP tracer: native provider -> approval -> draft/audit -> ledger."""

import json
import time
from uuid import uuid4

from provider_fixture import ProviderFixture, Scenario
from test_chat_integration import Product, session, wait_turn
from test_chat_tool_native_transport import native_wire


def grant_turn(product, saved, text="Rename the Agent", sequence=0):
    value = {"request_id": str(uuid4()), "expected_sequence": sequence, "text": text}
    request = {
        "request_id": str(uuid4()),
        "session_id": saved["id"],
        "turn_request_id": value["request_id"],
        "expected_sequence": sequence,
        "text": text,
    }
    status, grant = product.request("/api/v1/chat/tool-grants", "POST", request)
    assert status == 201, (status, grant)
    value["grant_id"] = grant["id"]
    status, turn = product.request(f"/api/v1/chat/sessions/{saved['id']}/tool-turns", "POST", value)
    assert status == 202, (status, turn)
    return grant, turn, value


def companion(product, turn, predicate=lambda x: bool(x["calls"])):
    until = time.monotonic() + 8
    while time.monotonic() < until:
        status, result = product.request(f"/api/v1/chat/turns/{turn['id']}/tools")
        assert status == 200, (status, result)
        if predicate(result):
            return result
        time.sleep(0.02)
    raise AssertionError(result)


def approve(product, call):
    body = {
        "request_id": str(uuid4()),
        "proposal_digest": call["proposal"]["digest"],
        "decision": "approve",
    }
    status, receipt = product.request(
        f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
    )
    assert status == 201, (status, receipt)
    return body, receipt


def test_native_http_read_approve_write_receipt_final_and_restart(tmp_path):
    product = Product(tmp_path)
    try:
        with ProviderFixture([Scenario((native_wire(),)), Scenario.text("unused")]) as seed:
            saved = session(product, seed)
            status, view = product.request("/api/v1/chat/tools/runtime")
            assert status == 200, (status, view)
            assert view["tools"] == [
                "configuration_read",
                "agent_profile_update",
                "target_create",
                "skill_create",
            ]
            assert view["requires_write_approval"] is True
            # Settings bootstrap is itself an audited write; read actual persisted revision.
            before = json.loads(product.state.read_text())
            revision = before["audit_total"]
            raw = json.dumps(
                {
                    "expected_draft_revision": revision,
                    "name": "Approved 🌍",
                    "skill_ids": before["agent_profile"]["skill_ids"],
                },
                ensure_ascii=False,
            )
            seed.scenarios = (
                Scenario((native_wire(),)),
                Scenario((native_wire(raw, name="agent_profile_update", identifier="write-1"),)),
                Scenario.text("Saved with operator approval."),
            )
            grant, turn, value = grant_turn(product, saved)
            transcript = companion(
                product, turn, lambda t: any(c["status"] == "awaiting_approval" for c in t["calls"])
            )
            read, write = transcript["calls"]
            assert read["status"] == "succeeded"
            assert read["result"]["draft_revision"] == revision
            assert json.loads(product.state.read_text()) == before
            assert len(seed.requests) == 2
            assert seed.closed == 2
            decision, receipt = approve(product, write)
            final = wait_turn(product, turn)
            assert final["status"] == "succeeded", final
            assert final["transport"] == "closed"
            after = json.loads(product.state.read_text())
            assert after["audit_total"] == revision + 1
            assert after["agent_profile"]["name"] == "Approved 🌍"
            for key in before["agent_profile"]:
                if key != "name":
                    assert after["agent_profile"][key] == before["agent_profile"][key]
            terminal = companion(product, turn)
            assert terminal["calls"][1]["status"] == "succeeded"
            result = terminal["calls"][1]["result"]
            assert result["audit"]["action"] == "agent_profile.updated"
            assert result["after_revision"] == after["audit_total"]
            assert product.request(
                f"/api/v1/chat/tool-calls/{write['id']}/decision", "POST", decision
            ) == (200, receipt)
            assert (
                product.request(f"/api/v1/chat/sessions/{saved['id']}/tool-turns", "POST", value)[0]
                == 200
            )
            assert len(seed.requests) == 3
            payload = seed.requests[-1]["body"]
            assert "tools" not in payload
            assert payload["messages"][-2]["tool_calls"][0]["function"]["arguments"] == raw
            assert json.loads(payload["messages"][-1]["content"])["result"] == result
            product.restart()
            assert companion(product, turn) == terminal
            assert json.loads(product.state.read_text()) == after
            assert len(seed.requests) == 3
    finally:
        product.child.stop()
        assert product.child.cleaned
