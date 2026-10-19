"""Runtime component seam: real HTTP/provider/SQLite, labelled Skill worker double.

This does not prove native Skill publication; the sibling DomainWorker hooks are
absent at this base. No claim of combined-domain acceptance is made here.
"""

import json
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_native_transport import native_wire
from test_chat_tool_routes_runtime import approve, companion
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.chat_models import now
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_models import arguments, receipt


class SkillInterface:
    def __init__(self, revision, settings, runtime):
        self.revision, self.settings, self.runtime = revision, settings, runtime
        self.preparations, self.writes, self.reads, self.guards = [], [], [], []
        self.control = "success"

    async def prepare_skill_create(
        self,
        expected_draft_revision,
        name,
        description,
        instructions,
        category,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        assert (
            expected_settings_revision == self.settings and expected_draft_revision == self.revision
        )
        assert deadline is not None and stop is self.runtime.stop_signal
        self.preparations.append((name, description, instructions, category))
        assert self.runtime.ledger.transcript(self.runtime.active)["calls"][-1]["proposal"] is None
        if self.control == "prepare-fail":
            raise DraftError("CHAT_INVALID_REQUEST")
        if self.control == "stop-after-prepare":
            stop.set()
        return dict(
            before_revision=self.revision,
            before=None,
            after=dict(
                name=name, description=description, instructions=instructions, category=category
            ),
        )

    async def create_skill(
        self,
        expected_draft_revision,
        name,
        description,
        instructions,
        category,
        publication_guard,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        assert (
            expected_settings_revision == self.settings and expected_draft_revision == self.revision
        )
        assert deadline is not None and stop is self.runtime.stop_signal
        assert (
            self.runtime.ledger.transcript(self.runtime.active)["calls"][-1]["status"]
            == "executing"
        )
        if self.control == "stop-at-guard":
            stop.set()
        self.guards.append(True)
        publication_guard()
        if self.control == "unexpected":
            raise RuntimeError("unknown mutation boundary")
        self.writes.append((name, description, instructions, category))
        value = receipt(
            arguments(
                expected_draft_revision=expected_draft_revision,
                name=name,
                description=description,
                instructions=instructions,
                category=category,
            )
        )
        value["audit"]["created_at"] = now()
        return value


def install_interface(monkeypatch, product, before):
    interface = SkillInterface(
        before["audit_total"], before["ai_settings"]["revision"], product.runtime
    )
    for name in ("prepare_skill_create", "create_skill"):
        monkeypatch.setattr(product.runtime.worker, name, getattr(interface, name), raising=False)
    return interface


def grant_turn(product, saved):
    body = dict(
        schema_version=3,
        scope="skill_create",
        request_id=str(uuid4()),
        session_id=saved["id"],
        turn_request_id=str(uuid4()),
        expected_sequence=0,
        text="SYNTHETIC inert Skill creation",
    )
    status, grant = product.request("/api/v1/chat/tool-grants", "POST", body)
    assert status == 201, (status, grant)
    assert product.request("/api/v1/chat/tool-grants", "POST", body) == (200, grant)
    assert product.request(f"/api/v1/chat/tool-grants/by-request/{body['request_id']}") == (
        200,
        grant,
    )
    status, turn = product.request(
        f"/api/v1/chat/sessions/{saved['id']}/tool-turns",
        "POST",
        dict(
            request_id=body["turn_request_id"],
            expected_sequence=0,
            text=body["text"],
            grant_id=grant["id"],
        ),
    )
    assert status == 202, (status, turn)
    return grant, turn


@pytest.mark.parametrize(
    "control",
    [
        "success",
        "prepare-fail",
        "stop-after-prepare",
        "stop-at-guard",
        "unexpected",
        "deny",
        "failed-final",
    ],
)
def test_prepare_before_proposal_and_final_decision_guard(tmp_path, monkeypatch, control):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        interface.control = control
        args = arguments(expected_draft_revision=before["audit_total"])
        raw = json.dumps(args, ensure_ascii=False) + " \n\t"
        provider.scenarios = (
            Scenario((native_wire(raw, name="skill_create"),)),
            Scenario.text(terminal=False)
            if control == "failed-final"
            else Scenario.text("SYNTHETIC final"),
        )
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda t: bool(t["calls"]) and t["calls"][0]["status"] != "requested"
        )["calls"][0]
        assert len(interface.preparations) == 1
        if control in ("prepare-fail", "stop-after-prepare"):
            assert call["proposal"] is None and call["decision"] is None
        else:
            assert call["status"] == "awaiting_approval", call
            assert interface.writes == []
            assert json.loads(product.state.read_text()) == before
            if control == "deny":
                status, _ = product.request(
                    f"/api/v1/chat/tool-calls/{call['id']}/decision",
                    "POST",
                    dict(
                        request_id=str(uuid4()),
                        proposal_digest=call["proposal"]["digest"],
                        decision="deny",
                    ),
                )
                assert status == 201
            else:
                body, ack = approve(product, call)
                assert product.request(
                    f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
                ) == (200, ack)
        final = wait_turn(product, turn)
        call = companion(product, turn)["calls"][0]
        expected = {
            "success": "succeeded",
            "failed-final": "succeeded",
            "prepare-fail": "failed",
            "stop-after-prepare": "cancelled",
            "stop-at-guard": "cancelled",
            "unexpected": "uncertain",
            "deny": "denied",
        }[control]
        assert call["status"] == expected, call
        assert len(interface.writes) == int(control in ("success", "failed-final"))
        assert (
            json.loads(product.state.read_text()) == before
        )  # Double never publishes domain state.
        if control in ("success", "failed-final"):
            assert call["result"]["skill"] == receipt(args)["skill"]
            assert interface.guards == [True]
            assert len(provider.requests) == 2 and "tools" not in provider.requests[-1]["body"]
            assert (
                provider.requests[-1]["body"]["messages"][-2]["tool_calls"][0]["function"][
                    "arguments"
                ]
                == raw
            )
        if control == "success":
            assert final["status"] == "succeeded"
        if control == "failed-final":
            assert final["status"] == "failed" and call["result"] is not None
        if control == "unexpected":
            assert product.request("/api/v1/chat/tools/fence")[1]["call_ids"] == [call["id"]]


def test_stop_during_final_proposal_projection_never_publishes_approval(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        args = arguments(expected_draft_revision=before["audit_total"])
        provider.scenarios = (Scenario((native_wire(json.dumps(args), name="skill_create"),)),)
        original = product.runtime.ledger._projection
        fired = []

        def projected(*values):
            result = original(*values)
            fired.append(True)
            product.runtime.stop_signal.set()
            return result

        monkeypatch.setattr(product.runtime.ledger, "_projection", projected)
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda t: bool(t["calls"]) and t["calls"][0]["status"] != "requested"
        )["calls"][0]
        try:
            assert fired == [True]
            assert call["proposal"] is None and call["decision"] is None
            assert call["status"] == "cancelled" and call["error_code"] == "CHAT_CANCELLED"
            assert interface.writes == [] and len(provider.requests) == 1
        finally:
            product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
