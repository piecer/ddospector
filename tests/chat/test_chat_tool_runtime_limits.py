"""Real native boundaries: closed args, finite rounds, nested exchange budget."""

import json
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_native_transport import frame, native_wire
from test_chat_tool_routes_controls import waiting
from test_chat_tool_routes_runtime import companion, grant_turn
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.models import SkillInput


@pytest.mark.parametrize(
    "arguments",
    [
        '{"kind":"agent_profile","approve":true}',
        '{"kind":"skills","offset":true,"limit":1}',
        '{"kind":"skill","id":" bad "}',
    ],
)
def test_invalid_typed_native_arguments_make_no_call_or_domain_request(
    tmp_path, monkeypatch, arguments
):
    with world(tmp_path, read=True) as (product, provider, saved, before):
        provider.scenarios = (Scenario((native_wire(arguments),)),)
        accessed = []
        original = product.runtime.worker.read_configuration

        async def observe(*args, **kwargs):
            accessed.append(True)
            return await original(*args, **kwargs)

        monkeypatch.setattr(product.runtime.worker, "read_configuration", observe)
        grant, turn, _ = grant_turn(product, saved)
        final = wait_turn(product, turn)
        assert final["error_code"] == "CHAT_TOOL_PROTOCOL"
        assert companion(product, turn, lambda t: True)["calls"] == []
        assert not accessed and len(provider.requests) == 1


def test_three_reads_then_final_without_tools(tmp_path):
    with world(tmp_path, read=True) as (product, provider, saved, before):
        provider.scenarios = tuple(
            Scenario((native_wire(identifier=f"read-{i}"),)) for i in range(3)
        ) + (Scenario.text("final"),)
        grant, turn, _ = grant_turn(product, saved)
        assert wait_turn(product, turn)["status"] == "succeeded"
        calls = companion(product, turn)["calls"]
        assert len(calls) == 3 and all(c["status"] == "succeeded" for c in calls)
        assert len(provider.requests) == 4
        assert all("tools" in r["body"] for r in provider.requests[:-1])
        assert "tools" not in provider.requests[-1]["body"]
        assert [t["function"]["name"] for t in provider.requests[0]["body"]["tools"]] == [
            "configuration_read",
            "agent_profile_update",
        ]


@pytest.mark.parametrize("oversize", [True, False])
def test_legal_skill_result_and_nested_exchange_caps(tmp_path, oversize):
    with world(tmp_path, read=True) as (product, provider, saved, before):
        skill = product.runtime.draft.create_skill(
            SkillInput(
                name="😀" * 120,
                category="analysis",
                description="😀" * 1000,
                instructions="😀" * 8000 if oversize else "\\" * 7999 + "x",
            )
        )
        arguments = json.dumps({"kind": "skill", "id": skill.id})
        wire = native_wire(arguments)
        if not oversize:
            wire = wire.replace(
                frame({"role": "assistant", "content": "검사 🌍"}),
                frame({"role": "assistant", "content": "x" * 64000}),
            )
        provider.scenarios = (Scenario((wire,)), Scenario.text("final"))
        grant, turn, _ = grant_turn(product, saved)
        final = wait_turn(product, turn)
        call = companion(product, turn)["calls"][0]
        if oversize:
            assert call["status"] == "failed" and call["error_code"] == "CHAT_TOOL_LIMIT"
            assert call["result"] is None and len(provider.requests) == 2
            assert final["status"] == "succeeded"
        else:
            assert call["status"] == "succeeded", call
            assert final["error_code"] == "CHAT_TOOL_LIMIT", final
            assert len(provider.requests) == 1, "exhausted exchange must not dispatch a followup"


def test_deny_retains_exact_receipt_and_has_no_write(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        body = {
            "request_id": str(uuid4()),
            "proposal_digest": call["proposal"]["digest"],
            "decision": "deny",
        }
        status, decision = product.request(
            f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
        )
        assert status == 201
        assert wait_turn(product, turn)["status"] == "succeeded"
        call = companion(product, turn)["calls"][0]
        assert call["status"] == "denied" and call["decision"] == decision
        assert json.loads(product.state.read_text()) == before
        assert len(provider.requests) == 2
        assert json.loads(provider.requests[-1]["body"]["messages"][-1]["content"]) == {
            "ok": False,
            "result": None,
            "error_code": "CHAT_TOOL_DENIED",
        }
