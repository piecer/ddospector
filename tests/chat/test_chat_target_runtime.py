"""Orchestrator component tests: real HTTP/provider/SQLite, synthetic domain interface.

Domain owner is not integrated in this exact-base workspace. TargetInterface is
an explicit test-only frozen-interface fixture, NOT a domain/store acceptance.
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


class TargetInterface:
    def __init__(self, revision, settings):
        self.revision, self.settings = revision, settings
        self.preparations, self.writes, self.reads = [], [], []
        self.failure = None

    async def read_configuration(self, arguments, locale, *, deadline=None, stop=None):
        self.reads.append(arguments)
        assert arguments == dict(kind="targets", offset=0, limit=10)
        return dict(kind="targets", draft_revision=self.revision, items=[], next_offset=None)

    async def prepare_target_create(
        self,
        expected_draft_revision,
        name,
        address,
        kind,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        assert expected_settings_revision == self.settings
        assert expected_draft_revision == self.revision
        assert deadline is not None and stop is not None
        self.preparations.append((name, address, kind))
        if self.failure:
            raise DraftError(self.failure)
        return dict(
            before_revision=self.revision,
            before=None,
            after=dict(name=name, address=address, kind=kind),
        )

    async def create_target(
        self,
        expected_draft_revision,
        name,
        address,
        kind,
        publication_guard,
        expected_settings_revision=None,
        *,
        deadline=None,
        stop=None,
    ):
        assert expected_settings_revision == self.settings
        assert expected_draft_revision == self.revision
        assert deadline is not None and stop is not None
        publication_guard()
        self.writes.append((name, address, kind))
        stamp = now()
        target = dict(
            id=str(uuid4()), name=name, address=address, kind=kind, status="draft", created_at=stamp
        )
        return dict(
            kind="target_created",
            before_revision=self.revision,
            after_revision=self.revision + 1,
            target=target,
            audit=dict(
                id=str(uuid4()),
                action="target.created",
                entity_id=target["id"],
                created_at=stamp,
                origin="local_operator",
            ),
        )


def install_interface(monkeypatch, product, before):
    interface = TargetInterface(before["audit_total"], before["ai_settings"]["revision"])
    for name in ("read_configuration", "prepare_target_create", "create_target"):
        monkeypatch.setattr(product.runtime.worker, name, getattr(interface, name), raising=False)
    return interface


def grant_turn(product, saved):
    body = dict(
        schema_version=2,
        scope="target_create",
        request_id=str(uuid4()),
        session_id=saved["id"],
        turn_request_id=str(uuid4()),
        expected_sequence=0,
        text="SYNTHETIC inert target creation",
    )
    status, grant = product.request("/api/v1/chat/tool-grants", "POST", body)
    assert status == 201, (status, grant)
    assert product.request("/api/v1/chat/tool-grants", "POST", body) == (200, grant)
    assert product.request(f"/api/v1/chat/tool-grants/by-request/{body['request_id']}") == (
        200,
        grant,
    )
    value = dict(
        request_id=body["turn_request_id"],
        expected_sequence=0,
        text=body["text"],
        grant_id=grant["id"],
    )
    status, turn = product.request(f"/api/v1/chat/sessions/{saved['id']}/tool-turns", "POST", value)
    assert status == 202, (status, turn)
    return grant, turn


def plan(before, final=None):
    args = dict(
        expected_draft_revision=before["audit_total"],
        name="SYNTHETIC 🌍",
        address="Example.COM.",
        kind="DUT",
    )
    return (
        Scenario(
            (
                native_wire(
                    json.dumps(dict(kind="targets", offset=0, limit=10)), identifier="target-read"
                ),
            )
        ),
        Scenario((native_wire(json.dumps(args), name="target_create", identifier="target-write"),)),
        final or Scenario.text("SYNTHETIC receipt explanation"),
    )


@pytest.mark.parametrize("failed_final", [False, True])
def test_target_orchestration_frozen_interface_and_saved_fact(tmp_path, monkeypatch, failed_final):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        provider.scenarios = plan(before, Scenario.text(terminal=False) if failed_final else None)
        grant, turn = grant_turn(product, saved)
        calls = companion(
            product, turn, lambda x: any(c["status"] == "awaiting_approval" for c in x["calls"])
        )["calls"]
        read, write = calls
        assert read["status"] == "succeeded" and read["result"]["kind"] == "targets"
        assert write["proposal"]["operation"] == "target_create"
        assert interface.writes == [] and len(interface.preparations) == 1
        assert json.loads(product.state.read_text()) == before
        assert len(provider.requests) == 2
        for request in provider.requests:
            payload = request["body"]
            assert [s["function"]["name"] for s in payload["tools"]] == [
                "configuration_read",
                "target_create",
            ]
            assert "syntax-only" in payload["messages"][0]["content"]
        approve(product, write)
        final = wait_turn(product, turn)
        assert final["status"] == ("failed" if failed_final else "succeeded")
        call = companion(product, turn)["calls"][1]
        assert call["status"] == "succeeded" and call["result"]["kind"] == "target_created"
        assert len(interface.writes) == 1
        assert len(provider.requests) == 3 and "tools" not in provider.requests[-1]["body"]
        # Fixture does not pretend to prove domain publication.
        assert json.loads(product.state.read_text()) == before


@pytest.mark.parametrize("fault", ["unexpected", "malformed-receipt"])
def test_entered_target_mutation_without_exact_receipt_is_uncertain(tmp_path, monkeypatch, fault):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        original = interface.create_target

        async def broken(*args, **kwargs):
            result = await original(*args, **kwargs)
            if fault == "unexpected":
                raise RuntimeError("SYNTHETIC post-entry failure")
            result["audit"]["entity_id"] = "wrong"
            return result

        monkeypatch.setattr(product.runtime.worker, "create_target", broken)
        provider.scenarios = plan(before)
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda x: any(c["status"] == "awaiting_approval" for c in x["calls"])
        )["calls"][-1]
        approve(product, call)
        final = wait_turn(product, turn)
        receipt = companion(product, turn)["calls"][-1]
        assert receipt["status"] == "uncertain" and receipt["error_code"] == "CHAT_TOOL_UNCERTAIN"
        assert final["error_code"] == "CHAT_TOOL_UNCERTAIN"
        assert product.request("/api/v1/chat/tools/fence")[1]["call_ids"] == [call["id"]]
        assert len(interface.writes) == 1 and len(provider.requests) == 2


@pytest.mark.parametrize(
    "control", ["deny", "conflict", "quota", "saturated", "stop-after-prepare"]
)
def test_target_refusal_has_no_mutation_or_generated_receipt(tmp_path, monkeypatch, control):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        expected = {
            "conflict": "CHAT_TOOL_CONFLICT",
            "quota": "CHAT_TOOL_LIMIT",
            "saturated": "CHAT_INVALID_REQUEST",
        }.get(control)
        if control == "saturated":
            from aiddos.api.chat_models import SAFE_INT

            interface.revision = SAFE_INT
            before = before | {"audit_total": SAFE_INT}
        interface.failure = expected
        if control == "stop-after-prepare":
            original = interface.prepare_target_create

            async def stopped(*args, **kwargs):
                prepared = await original(*args, **kwargs)
                product.runtime.stop_signal.set()
                return prepared

            monkeypatch.setattr(product.runtime.worker, "prepare_target_create", stopped)
        provider.scenarios = plan(before)
        _, turn = grant_turn(product, saved)
        if control == "deny":
            call = companion(
                product, turn, lambda x: any(c["status"] == "awaiting_approval" for c in x["calls"])
            )["calls"][-1]
            value = dict(
                request_id=str(uuid4()), proposal_digest=call["proposal"]["digest"], decision="deny"
            )
            assert (
                product.request(f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", value)[0]
                == 201
            )
        final = wait_turn(product, turn)
        call = companion(product, turn)["calls"][-1]
        assert interface.writes == [] and len(interface.preparations) == 1
        assert call["result"] is None
        assert call["error_code"] == (
            expected or ("CHAT_TOOL_DENIED" if control == "deny" else "CHAT_CANCELLED")
        )
        if control != "deny":
            assert call["proposal"] is None and call["decision"] is None
        if control == "stop-after-prepare":
            assert final["status"] == "cancelled" and len(provider.requests) == 2
        else:
            assert len(provider.requests) == 3 and "tools" not in provider.requests[-1]["body"]


@pytest.mark.parametrize(
    "target_grant,tool,args",
    [
        (
            False,
            "target_create",
            dict(expected_draft_revision=1, name="x", address="host", kind="DUT"),
        ),
        (False, "configuration_read", dict(kind="targets", offset=0, limit=10)),
        (True, "agent_profile_update", dict(expected_draft_revision=1, name="x", skill_ids=[])),
        (True, "configuration_read", dict(kind="agent_profile")),
    ],
)
def test_native_wrong_scope_is_denied_before_domain_or_call(
    tmp_path, monkeypatch, target_grant, tool, args
):
    from test_chat_tool_routes_runtime import grant_turn as legacy_grant_turn

    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        provider.scenarios = (Scenario((native_wire(json.dumps(args), name=tool),)),)
        if target_grant:
            _, turn = grant_turn(product, saved)
        else:
            _, turn, _ = legacy_grant_turn(product, saved)
        final = wait_turn(product, turn)
        assert final["error_code"] == "CHAT_TOOL_DENIED"
        assert companion(product, turn, lambda _: True)["calls"] == []
        assert interface.reads == interface.preparations == interface.writes == []
        assert len(provider.requests) == 1
        assert json.loads(product.state.read_text()) == before
