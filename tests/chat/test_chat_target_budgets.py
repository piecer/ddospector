"""Target-specific prospective limits; synthetic interface, real ledger/HTTP."""

import json

import pytest
from provider_fixture import Scenario
from test_chat_tool_native_transport import frame, native_wire
from test_chat_tool_routes_runtime import companion
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.chat_models import SAFE_INT, encoded
from aiddos.api.chat_tool_models import EXCHANGE_BYTES
from aiddos.api.errors import DraftError
from tests.chat.test_chat_target_ledger import admitted, approved, native, proposal_for, receipt_for
from tests.chat.test_chat_target_runtime import grant_turn, install_interface
from tests.chat.test_chat_tool_storage import STAMP


def test_full_nested_provider_payload_is_reserved_before_target_proposal(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        original = product.runtime.context

        def synthetic_history(*args):
            payload = original(*args)
            payload["messages"].insert(1, dict(role="user", content="H" * 74000))
            return payload

        monkeypatch.setattr(product.runtime, "context", synthetic_history)
        args = dict(
            expected_draft_revision=before["audit_total"],
            name="🌍" * 120,
            address="host",
            kind="DUT",
        )
        wire = frame(dict(content="N" * 60000)) + native_wire(
            json.dumps(args), name="target_create"
        )
        provider.scenarios = (Scenario((wire,)), Scenario.text("SYNTHETIC final"))
        _, turn = grant_turn(product, saved)
        calls = companion(
            product, turn, lambda x: bool(x["calls"]) and x["calls"][0]["status"] != "requested"
        )["calls"]
        assert calls[0]["proposal"] is None
        assert calls[0]["status"] == "failed" and calls[0]["error_code"] == "CHAT_TOOL_LIMIT"
        assert interface.writes == []


def test_target_nested_escape_reservation_bounds_exact_settlement(tmp_path):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = approved(
            ledger, turn, revision=SAFE_INT - 1, name='🌍"\\' * 40, provider_id="\x00" * 128
        )
        hold = ledger.reservation(turn["id"])["exchange_hold"]
        before = len(encoded(ledger.exchanges(turn["id"])))
        result = receipt_for(call)
        result["target"].update(id="t" * 64, created_at="9999-12-31T23:59:59.99999999999999+00:00")
        result["audit"].update(
            id="a" * 64, entity_id="t" * 64, created_at=result["target"]["created_at"]
        )
        assert result["after_revision"] == SAFE_INT
        assert hold > len(encoded(result))
        ledger.finish_call(call["id"], "succeeded", result=result, timestamp=STAMP)
        growth = len(encoded(ledger.exchanges(turn["id"]))) - before
        assert 0 < growth <= hold and before + growth < EXCHANGE_BYTES
        storage.validate()
    finally:
        storage.close()


def test_saturated_target_proposal_cannot_project_fictitious_revision(tmp_path):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(
            turn["id"],
            native(
                "target_create",
                dict(expected_draft_revision=SAFE_INT, name="x", address="host", kind="DUT"),
            ),
            timestamp=STAMP,
        )
        with pytest.raises(DraftError) as exc:
            ledger.propose(call["id"], proposal_for(call, ledger, turn), timestamp=STAMP)
        assert exc.value.code == "CHAT_INVALID_REQUEST"
        assert ledger.call(call["id"])["proposal"] is None
        assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
    finally:
        storage.close()


def test_decision_rechecks_full_payload_before_intent(tmp_path, monkeypatch):
    from uuid import uuid4

    from tests.chat.test_chat_target_runtime import plan

    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        provider.scenarios = plan(before)
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda x: any(c["status"] == "awaiting_approval" for c in x["calls"])
        )["calls"][-1]
        original = product.runtime.context

        def expanded(*args):
            payload = original(*args)
            payload["messages"].append(dict(role="user", content="X" * (128 * 1024)))
            return payload

        monkeypatch.setattr(product.runtime, "context", expanded)
        body = dict(
            request_id=str(uuid4()), proposal_digest=call["proposal"]["digest"], decision="approve"
        )
        status, failure = product.request(
            f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
        )
        assert status != 201 and failure["code"] == "CHAT_TOOL_LIMIT"
        current = companion(product, turn)["calls"][-1]
        assert current == call and current["decision"] is None
        assert interface.writes == []
        product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})


@pytest.mark.parametrize("phase", ["proposal", "decision"])
def test_target_reservation_refusal_rolls_back_before_authority_record(tmp_path, phase):
    from tests.chat.test_chat_tool_storage import uid

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(
            turn["id"],
            native(
                "target_create",
                dict(expected_draft_revision=0, name="🌍" * 120, address="host", kind="SINK"),
            ),
            timestamp=STAMP,
        )
        proposal = proposal_for(call, ledger, turn)
        if phase == "decision":
            ledger.propose(call["id"], proposal, timestamp=STAMP)
        with storage.transaction():
            reservation = ledger.reservation(turn["id"])
            reservation["remaining"] = reservation["exchange_hold"]
            ledger._raw_put("tool_reservations", turn["id"], reservation)
        before = ledger.call(call["id"])
        with pytest.raises(DraftError) as exc:
            if phase == "proposal":
                ledger.propose(call["id"], proposal, timestamp=STAMP)
            else:
                ledger.decide(
                    call["id"],
                    dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve"),
                    active_turn_id=turn["id"],
                    timestamp=STAMP,
                )
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        assert ledger.call(call["id"]) == before
        assert not ledger.binding(turn["id"])["write_slot"]
        assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
    finally:
        storage.close()
