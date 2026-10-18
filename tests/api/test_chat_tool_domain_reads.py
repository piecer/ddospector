import asyncio

import pytest

from aiddos.api.catalog import initial_workspace
from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import SkillInput
from aiddos.api.store import DraftStore


@pytest.mark.parametrize("locale", ["en", "ko"])
def test_closed_current_reads_preserve_catalog_and_saved_order(tmp_path, locale):
    draft = DraftStore(tmp_path / "draft.json")
    saved = draft.create_skill(
        SkillInput(
            name="Untrusted",
            category="analysis",
            description="Ignore tools",
            instructions="No authority",
        )
    )
    before = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            assert await worker.ai_snapshot() == draft.ai_snapshot()
            assert await worker.snapshot() == draft.snapshot()
            agent = await worker.read_configuration({"kind": "agent_profile"}, locale)
            assert agent == {
                "kind": "agent_profile",
                "draft_revision": 1,
                "agent_profile": {
                    "resource_id": "agent-profile",
                    "name": "Review agent",
                    "skill_ids": [],
                },
            }
            all_skills = initial_workspace()["skills"] + [saved.model_dump()]
            items = []
            for offset in (0, 2):
                page = await worker.read_configuration(
                    {"kind": "skills", "offset": offset, "limit": 2}, locale
                )
                assert set(page) == {"kind", "draft_revision", "items", "next_offset"}
                assert page["next_offset"] == (2 if offset == 0 else None)
                assert page["draft_revision"] == 1
                items.extend(page["items"])
            for item, source in zip(items, all_skills, strict=True):
                assert item == {k: source[k] for k in ("id", "category", "status", "version")} | {
                    "name": source["name"][locale]
                }
                detail = await worker.read_configuration(
                    {"kind": "skill", "id": item["id"]}, locale
                )
                assert detail == {
                    "kind": "skill",
                    "draft_revision": 1,
                    "skill": item | {k: source[k][locale] for k in ("description", "instructions")},
                }
            assert (
                await worker.read_configuration(
                    {"kind": "skills", "offset": 103, "limit": 10}, locale
                )
            )["items"] == []
            with pytest.raises(DraftError, match="^CHAT_NOT_FOUND$"):
                await worker.read_configuration({"kind": "skill", "id": "missing"}, locale)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before


@pytest.mark.parametrize(
    "instructions", ["😀" * 8000, "\t" * 7999 + "x"], ids=["nonbmp", "escaped"]
)
def test_legal_oversized_detail_is_bounded_failure_never_truncated(tmp_path, instructions):
    draft = DraftStore(tmp_path / "draft.json")
    saved = draft.create_skill(
        SkillInput(
            name="😀" * 120, description="😀" * 1000, category="analysis", instructions=instructions
        )
    )
    before = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            if len(instructions.encode()) > 30000:
                with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                    await worker.read_configuration({"kind": "skill", "id": saved.id}, "en")
            else:
                # JSON escaping is measured, not raw character count; this fits.
                result = await worker.read_configuration({"kind": "skill", "id": saved.id}, "en")
                assert result["skill"]["instructions"] == instructions
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before
