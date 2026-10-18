"""The owner rechecks its original authority at decision intent admission."""

import asyncio
import json
import time

import pytest
from test_chat_integration import wait_turn
from test_chat_tool_routes_controls import waiting
from test_chat_tool_routes_runtime import companion, grant_turn
from test_chat_tool_runtime_lifecycle import world
from test_chat_tool_storage import STAMP, uid
from test_chat_tool_storage_decision_admission import assert_unadmitted
from test_chat_tool_storage_intents import prepared

from aiddos.api import chat_tool_runtime, chat_tool_storage
from aiddos.api.chat_runtime import ChatRuntime
from aiddos.api.chat_tool_models import DecisionInput
from aiddos.api.errors import DraftError
from aiddos.api.store import DraftStore


@pytest.mark.parametrize("decision", ["approve", "deny"])
@pytest.mark.parametrize(
    "loss",
    [
        "turn_equal",
        "turn_exceeded",
        "grant_equal",
        "grant_exceeded",
        "stop",
        "stopping",
        "inactive",
    ],
)
def test_owner_authority_lost_during_decision_preparation(tmp_path, monkeypatch, decision, loss):
    storage, ledger, turn, call, proposal = prepared(tmp_path)
    owner = ChatRuntime(DraftStore(tmp_path / "domain.json"))
    owner.storage, owner.ledger, owner.active = storage, ledger, turn["id"]
    # Original owner clocks, fixed once at fixture admission, never refreshed.
    owner.tool_deadline = 500 if loss.startswith("grant") else 220
    owner.tool_grant_deadline = 400
    deadlines = (owner.tool_deadline, owner.tool_grant_deadline)
    clock = [100]
    monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: clock[0])
    monkeypatch.setattr(chat_tool_storage, "now", lambda: STAMP)
    seam = "_projection" if decision == "approve" else "binding"
    original = getattr(ledger, seam)
    entered = []

    def prepare(*args):
        result = original(*args)
        if not entered:
            assert owner.lock.locked() and storage.db.in_transaction
            entered.append(True)
            if loss.startswith("turn"):
                clock[0] = owner.tool_deadline + int(loss.endswith("exceeded"))
            elif loss.startswith("grant"):
                clock[0] = owner.tool_grant_deadline + int(loss.endswith("exceeded"))
            elif loss == "stop":
                owner.stop_signal.set()
            elif loss == "stopping":
                owner.stopping = True
            else:
                owner.active = None
        return result

    monkeypatch.setattr(ledger, seam, prepare)
    value = DecisionInput(request_id=uid(), proposal_digest=proposal["digest"], decision=decision)

    async def run():
        try:
            with pytest.raises(DraftError) as error:
                await owner.decide_tool(call["id"], value)
            assert error.value.code == "CHAT_TOOL_APPROVAL_CONFLICT"
            assert entered == [True]
            assert not owner.decision_ready.is_set() and not owner.worker.busy
            assert (owner.tool_deadline, owner.tool_grant_deadline) == deadlines
            assert_unadmitted(storage, ledger, turn, call)
        finally:
            await owner.worker.shutdown()
            storage.close()

    asyncio.run(run())


@pytest.mark.parametrize("condition", ["ontime", "expired", "stop"])
def test_http_projection_return_is_before_decision_admission(tmp_path, monkeypatch, condition):
    with world(tmp_path) as (product, provider, saved, before):
        product.runtime.turn_seconds = 0.5
        _, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        owner = product.runtime
        ledger = owner.ledger
        original = ledger._projection
        observations = []
        dispatches = []
        update = owner.worker.update_agent_profile

        async def dispatch(**kwargs):
            dispatches.append(True)
            return await update(**kwargs)

        monkeypatch.setattr(owner.worker, "update_agent_profile", dispatch)

        def prepare(*args):
            result = original(*args)
            start = time.monotonic()
            if condition == "expired":
                time.sleep(0.65)
            elif condition == "stop":
                owner.stop_signal.set()
            observations.append((start, time.monotonic(), owner.tool_deadline))
            return result

        monkeypatch.setattr(ledger, "_projection", prepare)
        body = dict(
            request_id=uid(), proposal_digest=call["proposal"]["digest"], decision="approve"
        )
        status, response = product.request(
            f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
        )
        if condition == "stop":
            product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
        wait_turn(product, turn)
        current = companion(product, turn)["calls"][0]
        assert len(observations) == 1
        start, end, deadline = observations[0]
        assert start < deadline
        if condition == "ontime":
            assert status == 201 and current["status"] == "succeeded"
            assert dispatches == [True] and len(provider.requests) == 2
        else:
            if condition == "expired":
                assert end > deadline
            assert status == 409 and response["code"] == "CHAT_TOOL_APPROVAL_CONFLICT"
            assert dispatches == [] and len(provider.requests) == 1
            assert json.loads(product.state.read_text()) == before
            assert current["decision"] is None and current["status"] != "executing"
            assert product.on_loop(
                lambda: owner.storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone()
            ) == (0,)
            assert not product.on_loop(lambda: ledger.binding(turn["id"])["write_slot"])


@pytest.mark.parametrize("decision", ["approve", "deny"])
def test_http_exact_replay_skips_live_guard_after_terminal_stop_expiry(
    tmp_path, monkeypatch, decision
):
    with world(tmp_path) as (product, provider, saved, before):
        _, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        body = dict(request_id=uid(), proposal_digest=call["proposal"]["digest"], decision=decision)
        path = f"/api/v1/chat/tool-calls/{call['id']}/decision"
        status, receipt = product.request(path, "POST", body)
        assert status == 201
        wait_turn(product, turn)
        owner = product.runtime
        assert owner.active is None
        owner.stop_signal.set()
        owner.stopping = True
        monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: owner.tool_grant_deadline + 1)
        monkeypatch.setattr(chat_tool_storage, "now", lambda: "2099-01-01T00:00:00+00:00")
        original = owner.ledger.decide
        seen = []

        def replay(*args, **kwargs):
            assert callable(kwargs["admission_guard"])

            def forbidden(_):
                pytest.fail("runtime replay invoked admission guard")

            kwargs["admission_guard"] = forbidden
            seen.append(True)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner.ledger, "decide", replay)
        state = product.state.read_bytes()
        prior = product.on_loop(lambda: list(owner.storage.db.iterdump()))
        assert product.request(path, "POST", body) == (200, receipt)
        conflict = body | {"decision": "deny" if decision == "approve" else "approve"}
        status, response = product.request(path, "POST", conflict)
        assert status == 409 and response["code"] == "CHAT_TOOL_APPROVAL_CONFLICT"
        assert seen == [True, True]
        assert product.state.read_bytes() == state
        assert product.on_loop(lambda: list(owner.storage.db.iterdump())) == prior
        assert len(provider.requests) == 2
        if decision == "deny":
            assert json.loads(state) == before
