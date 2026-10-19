"""Bounded operator Skill inspection, separate from legacy model projections."""

import asyncio
import json
import threading

import pytest

from aiddos.api.catalog import SAFETY_RULES, SKILLS_V1
from aiddos.api.chat_models import encoded
from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import AuditEvent, DraftState, Skill
from aiddos.api.store import DraftStore

SAFE_INT = 9007199254740991


def maximal_state():
    # Synthetic valid persisted-state envelope, not a fresh product create receipt.
    skills = [
        Skill(
            id=f"{i:064d}",
            status="draft",
            category="measurement",
            name={"en": "🌍" * 120, "ko": "🌍" * 120},
            description={"en": "🌍" * 1000, "ko": "🌍" * 1000},
            instructions={"en": "🌍" * 8000, "ko": "🌍" * 8000},
            allowed_operations=[],
            required_capabilities=[],
            safety_rules=SAFETY_RULES,
        )
        for i in range(100)
    ]
    return DraftState(
        skills=skills,
        audit_total=SAFE_INT,
        audit=[
            AuditEvent(
                id=f"audit-{i}",
                action="agent_profile.updated",
                entity_id="agent-profile",
                created_at="2026-01-01T00:00:00+00:00",
            )
            for i in range(500)
        ],
    )


def test_summary_and_full_detail_bounds_and_template_identity(tmp_path, record_property):
    draft = DraftStore(tmp_path / "draft.json")
    state = maximal_state()
    draft._write(state)
    before = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            summary = await worker.skills_snapshot()
            records = SKILLS_V1 + [skill.model_dump() for skill in state.skills]
            fields = {"id", "name", "category", "status", "version"}
            assert summary == {
                "schema_version": 1,
                "draft_revision": SAFE_INT,
                "skills": [{k: v for k, v in skill.items() if k in fields} for skill in records],
            }
            assert len(summary["skills"]) == len({s["id"] for s in summary["skills"]}) == 103
            assert len(encoded(summary)) == 112418 < 131072
            record_property("summary_bytes", len(encoded(summary)))
            detail = await worker.skill_snapshot(state.skills[-1].id)
            assert detail == {
                "schema_version": 1,
                "draft_revision": SAFE_INT,
                "skill": state.skills[-1].model_dump(),
            }
            assert len(encoded(detail)) == 73824 < 131072
            record_property("detail_bytes", len(encoded(detail)))
            for template in SKILLS_V1:
                inspected = await worker.skill_snapshot(template["id"])
                assert inspected["skill"] == template
                assert len(encoded(inspected)) < 131072
                inspected["skill"]["instructions"]["en"] = "local alias mutation"
                assert (await worker.skill_snapshot(template["id"]))["skill"] == template
            # Existing model projection remains single-locale and 32KiB bounded.
            page = await worker.read_configuration(
                {"kind": "skills", "offset": 0, "limit": 10}, "ko"
            )
            assert page["items"][0]["name"] == SKILLS_V1[0]["name"]["ko"]
            with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                await worker.read_configuration({"kind": "skill", "id": state.skills[0].id}, "en")
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before


@pytest.mark.parametrize("surface", ["summary", "detail"])
def test_operator_byte_meter_exact_and_plus_one(tmp_path, monkeypatch, surface):
    """Meter-only boundary: validated record envelopes cannot reach 128KiB."""
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    sizes = []

    async def exercise():
        worker = DomainWorker(draft)
        try:
            for size in (131072, 131073):

                def encode(value, size=size):
                    sizes.append(size)
                    return b"x" * size

                monkeypatch.setattr(module, "encoded", encode)
                operation = (
                    worker.skills_snapshot()
                    if surface == "summary"
                    else (worker.skill_snapshot(SKILLS_V1[0]["id"]))
                )
                if size == 131072:
                    assert (await operation)["draft_revision"] == 0
                else:
                    with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                        await operation
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert sizes == [131072, 131073]
    assert not draft.path.exists()


@pytest.mark.parametrize("identifier", ["", "a" * 65, "bad/id", "bad id", "🌍", 1, None, True])
def test_invalid_selector_is_not_missing_record(tmp_path, identifier):
    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                await worker.skill_snapshot(identifier)
            with pytest.raises(DraftError, match="^CHAT_NOT_FOUND$"):
                await worker.skill_snapshot("valid-but-missing")
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert not draft.path.exists()


@pytest.mark.parametrize("surface", ["summary", "detail"])
def test_native_owner_cancel_and_busy_semantics(tmp_path, monkeypatch, surface):
    draft = DraftStore(tmp_path / "draft.json")
    entered, release = threading.Event(), threading.Event()
    real_read = draft._read

    def read():
        entered.set()
        assert release.wait(5), "owner never released native fixture"
        return real_read()

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(
            worker.skills_snapshot()
            if surface == "summary"
            else worker.skill_snapshot(SKILLS_V1[0]["id"])
        )
        try:
            async with asyncio.timeout(5):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert worker.busy
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.skills_snapshot()
            release.set()
            await worker.settle()
            assert not worker.busy
        finally:
            release.set()
            await worker.shutdown()
        assert not worker._thread.is_alive()

    asyncio.run(exercise())
    assert not draft.path.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "template",
        "reserved_id",
        "duplicate_id",
        "translated",
        "policy",
        "extra",
        "oversize",
        "missing",
        "malformed",
        "unavailable",
    ],
)
def test_operator_reads_reject_corrupt_custom_or_arbitrary_template(tmp_path, corruption):
    from aiddos.api.models import SkillInput

    draft = DraftStore(tmp_path / "draft.json")
    created = draft.create_skill(
        SkillInput(name="Read me", description="Literal", instructions="Inert", category="planning")
    )
    payload = json.loads(draft.path.read_bytes())
    skill = payload["skills"][0]
    if corruption == "template":
        skill["status"] = "template"
    elif corruption == "reserved_id":
        skill["id"] = SKILLS_V1[0]["id"]
        payload["audit"][0]["entity_id"] = skill["id"]
    elif corruption == "duplicate_id":
        payload["skills"].append(skill)
    elif corruption == "translated":
        skill["instructions"]["ko"] = "Invented translation"
    elif corruption == "policy":
        skill["allowed_operations"] = ["execute"]
    elif corruption == "extra":
        skill["created_at"] = "2026-01-01T00:00:00+00:00"
    elif corruption == "oversize":
        skill["instructions"] = {"en": "x" * 8001, "ko": "x" * 8001}
    elif corruption == "missing":
        del skill["version"]
    if corruption == "malformed":
        draft.path.write_bytes(b"{")
    elif corruption == "unavailable":
        target = tmp_path / "original.json"
        draft.path.rename(target)
        draft.path.symlink_to(target)
    else:
        draft.path.write_text(json.dumps(payload))
    before = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_STORAGE_ERROR$"):
                await worker.skills_snapshot()
            with pytest.raises(DraftError, match="^CHAT_STORAGE_ERROR$"):
                await worker.skill_snapshot(created.id)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before
