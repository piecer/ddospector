"""Real draft publications, not synthetic operation receipts."""

import asyncio
import json

import pytest

from aiddos.api.errors import DraftError
from aiddos.api.models import AgentProfileInput, AISettingsInput, McpServerInput, TargetInput
from aiddos.api.store import DraftStore


def test_native_worker_writes_real_agent_with_exact_audit_and_preserved_fields(tmp_path):
    from aiddos.api.chat_tool_domain import DomainWorker

    draft = DraftStore(tmp_path / "draft.json")
    mcp = draft.create_mcp_server(
        McpServerInput(
            name="Observer", endpoint="observer", transport="stdio", usage_instructions="Read only"
        )
    )
    draft.save_agent_profile(
        AgentProfileInput(name="Before", skill_ids=[], mcp_server_ids=[mcp.id])
    )
    before = json.loads(draft.path.read_bytes())

    async def exercise():
        worker = DomainWorker(draft)
        try:
            result = await worker.update_agent_profile(
                before["audit_total"], "After", ["policy-validation"], lambda: None
            )
            assert set(result) == {
                "kind",
                "before_revision",
                "after_revision",
                "agent_profile",
                "audit",
            }
            disk = json.loads(draft.path.read_bytes())
            assert result == {
                "kind": "agent_profile_updated",
                "before_revision": 2,
                "after_revision": 3,
                "agent_profile": {
                    "resource_id": "agent-profile",
                    "name": "After",
                    "skill_ids": ["policy-validation"],
                },
                "audit": disk["audit"][-1],
            }
            assert result["audit"]["action"] == "agent_profile.updated"
            assert result["audit"]["origin"] == "local_operator"
            assert result["audit"]["id"] not in {e["id"] for e in before["audit"]}
            for field in before:
                if field not in {"agent_profile", "audit", "audit_total"}:
                    assert disk[field] == before[field]
            assert disk["audit"][:-1] == before["audit"]
            assert disk["agent_profile"] == {
                **before["agent_profile"],
                "name": "After",
                "skill_ids": ["policy-validation"],
            }
        finally:
            await worker.shutdown()
        assert not worker.busy

    asyncio.run(exercise())


@pytest.mark.parametrize("interference", ["manual_aba", "unrelated_save", "ai_settings"])
def test_cas_rejects_every_legacy_write_even_agent_aba(tmp_path, interference):
    from aiddos.api.chat_tool_domain import DomainWorker

    draft = DraftStore(tmp_path / "draft.json")
    original = AgentProfileInput(name="Original", skill_ids=[], mcp_server_ids=[])
    draft.save_agent_profile(original)
    if interference == "manual_aba":
        draft.save_agent_profile(original.model_copy(update={"name": "Intervening"}))
        draft.save_agent_profile(original)
    elif interference == "unrelated_save":
        draft.create_target(TargetInput(name="Other", address="localhost", kind="DUT"))
    else:
        draft.save_ai_settings(
            AISettingsInput(revision=0, profiles=[], default_profile_id=None, agent_profile_id=None)
        )
    before = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                await worker.update_agent_profile(1, "Stale", [], lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before


def test_prepare_is_read_only_and_both_paths_reuse_business_validation(tmp_path):
    from aiddos.api.chat_tool_domain import DomainWorker

    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            proposal = await worker.prepare_update(0, "Approved", ["policy-validation"])
            assert proposal == {
                "before_revision": 0,
                "before": {"resource_id": "agent-profile", "name": "Review agent", "skill_ids": []},
                "after": {
                    "resource_id": "agent-profile",
                    "name": "Approved",
                    "skill_ids": ["policy-validation"],
                },
            }
            assert not draft.path.exists()
            for name, ids in [
                ("", []),
                ("Valid", ["missing"]),
                ("Valid", ["policy-validation"] * 2),
            ]:
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await worker.prepare_update(0, name, ids)
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await worker.update_agent_profile(0, name, ids, lambda: None)
                assert not draft.path.exists()
            with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                await worker.prepare_update(1, "Stale", [])
            with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                await worker.update_agent_profile(
                    0, "Bad settings", [], lambda: None, expected_settings_revision=1
                )
            assert not draft.path.exists()
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_legacy_agent_save_keeps_default_write_seam_and_supports_opt_in_cas(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    value = AgentProfileInput(name="Manual", skill_ids=[], mcp_server_ids=[])
    real_write = draft._write
    calls = []

    def write(state):
        calls.append(state.audit_total)
        real_write(state)

    with monkeypatch.context() as context:
        context.setattr(draft, "_write", write)
        assert draft.save_agent_profile(value).name == "Manual"
    assert calls == [1]
    original = draft.path.read_bytes()
    with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
        draft.save_agent_profile(value, expected_draft_revision=0)
    assert draft.path.read_bytes() == original
    guards = []
    draft.save_agent_profile(
        value, expected_draft_revision=1, publication_guard=lambda: guards.append(True)
    )
    assert guards == [True]
    assert draft._read().audit_total == 2
