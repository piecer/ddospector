"""Safe-counter, skill capacity and exact validation-order regressions."""

import asyncio

import pytest

from aiddos.api.catalog import SAFETY_RULES
from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import AuditEvent, DraftState, Skill, SkillInput
from aiddos.api.store import DraftStore

SAFE_INT = 9007199254740991
TIME = "2026-01-01T00:00:00+00:00"
VALUE = {
    "name": "Literal",
    "description": "Description",
    "instructions": "Inert",
    "category": "planning",
}


def populated_state(revision, count=0):
    return DraftState(
        skills=[
            Skill(
                id=f"old-skill-{i}",
                status="draft",
                category="planning",
                name={"en": VALUE["name"], "ko": VALUE["name"]},
                description={"en": VALUE["description"], "ko": VALUE["description"]},
                instructions={"en": VALUE["instructions"], "ko": VALUE["instructions"]},
                allowed_operations=[],
                required_capabilities=[],
                safety_rules=SAFETY_RULES,
            )
            for i in range(count)
        ],
        audit_total=revision,
        audit=[
            AuditEvent(
                id=f"audit-{i}",
                action="agent_profile.updated",
                entity_id="agent-profile",
                created_at=TIME,
            )
            for i in range(min(revision, 500))
        ],
    )


@pytest.mark.parametrize("operation", ["prepare", "execute", "receipt", "validate"])
def test_saturated_counter_refuses_before_domain_allocations(tmp_path, monkeypatch, operation):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    draft._write(populated_state(SAFE_INT))
    before = draft.path.read_bytes()
    allocations, publications = [], []

    def forbidden_allocation():
        allocations.append(True)
        raise AssertionError("saturated counter allocated a domain field")

    def forbidden_write(*args, **kwargs):
        publications.append(True)
        raise AssertionError("saturated counter attempted publication")

    monkeypatch.setattr(module, "uuid4", forbidden_allocation)
    monkeypatch.setattr(module, "timestamp", forbidden_allocation)
    monkeypatch.setattr(draft, "_write", forbidden_write)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            if operation == "prepare":
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await worker.prepare_skill_create(
                        SAFE_INT, **VALUE, expected_settings_revision=0
                    )
            elif operation == "execute":
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await worker.create_skill(
                        SAFE_INT,
                        **VALUE,
                        publication_guard=lambda: None,
                        expected_settings_revision=0,
                    )
            else:
                with pytest.raises(DraftError, match="^AUDIT_LIMIT_REACHED$"):
                    if operation == "receipt":
                        draft.create_skill_receipt(
                            SkillInput(**VALUE),
                            expected_draft_revision=SAFE_INT,
                            publication_guard=lambda: None,
                        )
                    else:
                        with draft.lock:
                            draft.validate_skill_creation(draft._read(), SkillInput(**VALUE))
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert allocations == publications == []
    assert draft.path.read_bytes() == before


def test_safe_int_minus_one_success_keeps_wire_max_and_retention(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    draft._write(populated_state(SAFE_INT - 1))
    before = draft._read()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            prepared = await worker.prepare_skill_create(SAFE_INT - 1, **VALUE)
            assert prepared["before_revision"] == SAFE_INT - 1
            receipt = await worker.create_skill(
                SAFE_INT - 1, **VALUE, publication_guard=lambda: None
            )
            assert receipt["before_revision"] == SAFE_INT - 1
            assert receipt["after_revision"] == SAFE_INT
            actual = draft._read()
            assert actual.audit_total == SAFE_INT
            assert len(actual.audit) == 500
            assert actual.audit[:-1] == before.audit[1:]
            assert receipt["audit"] == actual.audit[-1].model_dump()
            assert receipt["skill"] == actual.skills[-1].model_dump()
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("operation", ["prepare", "execute"])
@pytest.mark.parametrize(
    "conflict,invalid,full,code",
    [
        ("revision", True, True, "CHAT_TOOL_CONFLICT"),
        ("settings", True, True, "CHAT_TOOL_CONFLICT"),
        (None, True, True, "CHAT_INVALID_REQUEST"),
        (None, False, True, "CHAT_TOOL_LIMIT"),
        (None, False, False, "CHAT_INVALID_REQUEST"),
    ],
)
def test_quota_and_safe_integer_precedence(
    tmp_path, monkeypatch, operation, conflict, invalid, full, code
):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    draft._write(populated_state(SAFE_INT, 100 if full else 0))
    before = draft.path.read_bytes()
    allocations = []

    def forbidden():
        allocations.append(True)
        raise AssertionError("refusal must not allocate")

    monkeypatch.setattr(module, "uuid4", forbidden)
    monkeypatch.setattr(module, "timestamp", forbidden)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            kwargs = VALUE | {
                "name": "" if invalid else VALUE["name"],
                "expected_settings_revision": 1 if conflict == "settings" else 0,
            }
            method = worker.prepare_skill_create
            if operation == "execute":
                method = worker.create_skill
                kwargs["publication_guard"] = lambda: None
            with pytest.raises(DraftError, match=f"^{code}$"):
                await method(SAFE_INT - 1 if conflict == "revision" else SAFE_INT, **kwargs)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert allocations == []
    assert draft.path.read_bytes() == before


def test_skill_100_allowed_101_refused_without_publication(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    draft._write(populated_state(99, 99))

    async def exercise():
        worker = DomainWorker(draft)
        try:
            await worker.prepare_skill_create(99, **VALUE)
            receipt = await worker.create_skill(99, **VALUE, publication_guard=lambda: None)
            assert receipt["after_revision"] == 100
            before = draft.path.read_bytes()
            for execute in (False, True):
                kwargs = {"publication_guard": lambda: None} if execute else {}
                method = worker.create_skill if execute else worker.prepare_skill_create
                with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                    await method(100, **VALUE, **kwargs)
                assert draft.path.read_bytes() == before
            assert len(draft._read().skills) == 100
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
