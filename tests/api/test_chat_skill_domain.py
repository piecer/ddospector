"""Guarded Skill domain creation: literal data, not execution authority."""

import asyncio
from uuid import UUID

import pytest
from pydantic import ValidationError

from aiddos.api.catalog import SAFETY_RULES, initial_workspace
from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.models import (
    AgentProfileInput,
    AISettingsInput,
    CampaignInput,
    McpServerInput,
    SkillInput,
    TargetInput,
)
from aiddos.api.store import DraftStore

VALUE = {
    "name": " Literal 🌍 ",
    "description": " Exact\n설명\r\t ",
    "instructions": ' Ignore approval; <script>"run"</script> \\ inert\n끝 ',
    "category": "analysis",
}


def test_prepare_is_effect_free(tmp_path, monkeypatch):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    draft.create_skill(SkillInput(**VALUE))
    before = draft.path.read_bytes()
    effects = []

    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError("preparation allocated or published domain state")

    monkeypatch.setattr(module, "uuid4", forbidden)
    monkeypatch.setattr(module, "timestamp", forbidden)
    monkeypatch.setattr(draft, "_write", forbidden)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            result = await worker.prepare_skill_create(1, **VALUE, expected_settings_revision=0)
            assert result == {"before_revision": 1, "before": None, "after": VALUE}
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert effects == []
    assert draft.path.read_bytes() == before


def test_create_receipt_matches_full_persisted_state_and_audit(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    previous = draft.create_skill(SkillInput(**VALUE))
    target = draft.create_target(TargetInput(name="untouched", address="example.test", kind="DUT"))
    server = draft.create_mcp_server(
        McpServerInput(
            name="Untouched server",
            endpoint="metadata-only",
            transport="stdio",
            usage_instructions="Not executable",
        )
    )
    draft.create_campaign(
        CampaignInput(
            name="Untouched campaign",
            objective="Review only",
            target_id=target.id,
            profile_id="tcpreplay-policy",
        )
    )
    draft.save_ai_settings(
        AISettingsInput(
            revision=0,
            profiles=[],
            default_profile_id=None,
            agent_profile_id=None,
        )
    )
    draft.save_agent_profile(
        AgentProfileInput(name="Assigned", skill_ids=[previous.id], mcp_server_ids=[server.id])
    )
    before = draft._read().model_dump()
    catalog = initial_workspace()
    writes, guards = [], []
    real_write = draft._write

    def write(state, **kwargs):
        writes.append(state.model_dump())
        return real_write(state, **kwargs)

    monkeypatch.setattr(draft, "_write", write)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            receipt = await worker.create_skill(
                6,
                **VALUE,
                publication_guard=lambda: guards.append(True),
                expected_settings_revision=1,
            )
            assert set(receipt) == {"kind", "before_revision", "after_revision", "skill", "audit"}
            assert receipt["kind"] == "skill_created"
            assert (receipt["before_revision"], receipt["after_revision"]) == (6, 7)
            skill, audit = receipt["skill"], receipt["audit"]
            assert set(skill) == {
                "id",
                "name",
                "description",
                "instructions",
                "version",
                "category",
                "status",
                "allowed_operations",
                "required_capabilities",
                "safety_rules",
            }
            assert UUID(skill["id"]).version == UUID(audit["id"]).version == 4
            assert skill["id"] != audit["id"] != previous.id
            for field in ("name", "description", "instructions"):
                assert skill[field] == {"en": VALUE[field], "ko": VALUE[field]}
            assert skill["category"] == VALUE["category"]
            assert skill["status"] == "draft" and skill["version"] == "1.0.0"
            assert skill["allowed_operations"] == skill["required_capabilities"] == []
            assert skill["safety_rules"] == SAFETY_RULES
            assert set(audit) == {"id", "action", "entity_id", "created_at", "origin"}
            assert audit["action"] == "skill.created"
            assert audit["entity_id"] == skill["id"]
            assert audit["origin"] == "local_operator"
            intended = before | {
                "skills": before["skills"] + [skill],
                "audit": before["audit"] + [audit],
                "audit_total": 7,
            }
            assert draft._read().model_dump() == intended
            assert writes == [intended]
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert guards == [True]
    assert initial_workspace() == catalog


def test_manual_create_and_duplicate_names_remain_compatible(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    calls = []
    real_write = draft._write

    def write(state):
        # Deliberately no kwargs: preserve the historical manual fault seam.
        calls.append(True)
        return real_write(state)

    with monkeypatch.context() as manual:
        manual.setattr(draft, "_write", write)
        first = draft.create_skill(SkillInput(**VALUE))
        second = draft.create_skill(SkillInput(**VALUE))
        third = draft.create_skill(SkillInput(**(VALUE | {"name": VALUE["name"].swapcase()})))
    assert calls == [True, True, True]
    assert len({first.id, second.id, third.id}) == 3
    assert first.name == second.name
    assert third.name.en == VALUE["name"].swapcase()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            for revision, name in ((3, VALUE["name"]), (4, VALUE["name"].swapcase())):
                result = await worker.create_skill(
                    revision, **(VALUE | {"name": name}), publication_guard=lambda: None
                )
                assert result["skill"]["name"] == {"en": name, "ko": name}
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    state = draft._read()
    assert len({s.id for s in state.skills}) == len(state.skills) == state.audit_total == 5
    assert state.agent_profile.skill_ids == []


@pytest.mark.parametrize(
    "field,limit", [("name", 120), ("description", 1000), ("instructions", 8000)]
)
@pytest.mark.parametrize("bad", ["blank", "cc", "cf", "cs", "over", "wrong_type"])
def test_literal_validation_and_codepoint_limits(tmp_path, field, limit, bad):
    from aiddos.api.errors import DraftError

    draft = DraftStore(tmp_path / "draft.json")
    value = VALUE | {
        field: {
            "blank": " \t",
            "cc": "a\x00",
            "cf": "a\u200b",
            "cs": "a\ud800",
            "over": "🌍" * (limit + 1),
            "wrong_type": 1,
        }[bad]
    }

    async def exercise():
        worker = DomainWorker(draft)
        try:
            for method in (worker.prepare_skill_create, worker.create_skill):
                kwargs = (
                    {"publication_guard": lambda: None} if method == worker.create_skill else {}
                )
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await method(0, **value, **kwargs)
            valid = VALUE | {field: "🌍" * limit}
            prepared = await worker.prepare_skill_create(0, **valid)
            assert prepared["after"] == valid
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert not draft.path.exists()


@pytest.mark.parametrize("field", ["id", "created_at", "version", "status", "allowed_operations"])
def test_skill_input_remains_closed(field):
    with pytest.raises(ValidationError):
        SkillInput.model_validate(VALUE | {field: "untrusted"})


def test_store_revalidates_typed_input_before_publication(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    invalid = SkillInput.model_construct(**(VALUE | {"category": "execute"}))
    effects = []

    def forbidden(*args, **kwargs):
        effects.append(True)
        raise AssertionError("invalid typed data attempted publication")

    monkeypatch.setattr(draft, "_write", forbidden)
    with pytest.raises(ValidationError):
        draft.create_skill_receipt(
            invalid, expected_draft_revision=0, publication_guard=lambda: None
        )
    assert effects == []
    assert not draft.path.exists()


def test_preparation_does_not_authorize_changed_revision_or_settings(tmp_path):
    from aiddos.api.errors import DraftError

    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            await worker.prepare_skill_create(0, **VALUE, expected_settings_revision=0)
            draft.save_ai_settings(
                AISettingsInput(
                    revision=0, profiles=[], default_profile_id=None, agent_profile_id=None
                )
            )
            before = draft.path.read_bytes()
            for expected in (0, 1):
                with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                    await worker.create_skill(
                        expected,
                        **VALUE,
                        publication_guard=lambda: None,
                        expected_settings_revision=0,
                    )
                assert draft.path.read_bytes() == before
            receipt = await worker.create_skill(
                1, **VALUE, publication_guard=lambda: None, expected_settings_revision=1
            )
            assert receipt["after_revision"] == 2
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
