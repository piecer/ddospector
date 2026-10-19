"""Target-domain receipts from real JSON publications; no model or network."""

import asyncio
import json
from uuid import UUID

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import TargetInput
from aiddos.api.store import DraftStore

VALUE = {"name": "승인된 대상 🌍", "address": "Example.COM.", "kind": "DUT"}


def test_guarded_creation_has_one_publication_and_exact_authoritative_receipt(
    tmp_path, monkeypatch
):
    draft = DraftStore(tmp_path / "draft.json")
    original = draft.create_target(TargetInput(**VALUE))
    before = json.loads(draft.path.read_bytes())
    publications, guards = [], []
    real_write = draft._write

    def write(state, **kwargs):
        publications.append(state.model_dump())
        real_write(state, **kwargs)

    monkeypatch.setattr(draft, "_write", write)
    target, audit = draft.create_target_receipt(
        TargetInput(**VALUE),
        expected_draft_revision=1,
        publication_guard=lambda: guards.append(True),
    )
    disk = json.loads(draft.path.read_bytes())
    assert len(publications) == 1
    assert guards == [True]
    assert target.model_dump() == disk["targets"][-1]
    assert audit.model_dump() == disk["audit"][-1]
    assert target.id != original.id
    assert UUID(target.id).version == UUID(audit.id).version == 4
    assert target.model_dump() == VALUE | {
        "id": target.id,
        "created_at": target.created_at,
        "status": "draft",
    }
    assert audit.model_dump() == {
        "id": audit.id,
        "action": "target.created",
        "entity_id": target.id,
        "created_at": target.created_at,
        "origin": "local_operator",
    }
    assert disk == before | {
        "targets": before["targets"] + [target.model_dump()],
        "audit": before["audit"] + [audit.model_dump()],
        "audit_total": 2,
    }
    with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
        draft.create_target_receipt(
            TargetInput(**VALUE), expected_draft_revision=1, publication_guard=lambda: None
        )
    assert len(publications) == 1


def test_native_prepare_is_effect_free_and_execution_returns_real_receipt(tmp_path, monkeypatch):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    allocations = []

    def forbidden():
        allocations.append(True)
        raise AssertionError("preparation allocated domain identity/time")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with monkeypatch.context() as context:
                context.setattr(module, "uuid4", forbidden)
                context.setattr(module, "timestamp", forbidden)
                prepared = await worker.prepare_target_create(
                    0, **VALUE, expected_settings_revision=0
                )
            assert prepared == {"before_revision": 0, "before": None, "after": VALUE}
            assert allocations == []
            assert not draft.path.exists()
            result = await worker.create_target(
                0, **VALUE, publication_guard=lambda: None, expected_settings_revision=0
            )
            disk = json.loads(draft.path.read_bytes())
            assert result == {
                "kind": "target_created",
                "before_revision": 0,
                "after_revision": 1,
                "target": disk["targets"][0],
                "audit": disk["audit"][0],
            }
            assert result["target"] | VALUE == result["target"]
        finally:
            await worker.shutdown()
        assert not worker.busy
        assert not worker._thread.is_alive()

    asyncio.run(exercise())


def test_native_target_reads_are_literal_ordered_paginated_and_independent(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    for i in range(12):
        draft.create_target(TargetInput(**(VALUE | {"name": str(i)})))
    state = draft._read()
    # Existing domain IDs are not restricted to UUID4.
    old_id = state.targets[0].id
    state.targets[0].id = "old-target-01"
    for audit in state.audit:
        if audit.entity_id == old_id:
            audit.entity_id = state.targets[0].id
    draft._write(state)
    before = draft.path.read_bytes()
    expected = [item.model_dump() for item in state.targets]

    async def exercise():
        worker = DomainWorker(draft)
        try:
            inventory = await worker.targets_snapshot()
            assert inventory == {"schema_version": 1, "draft_revision": 12, "targets": expected}
            for offset, limit, end in ((0, 10, 10), (10, 10, None), (12, 1, None), (100, 10, None)):
                assert await worker.read_configuration(
                    {"kind": "targets", "offset": offset, "limit": limit}, "ko"
                ) == {
                    "kind": "targets",
                    "draft_revision": 12,
                    "items": expected[offset : offset + limit],
                    "next_offset": end,
                }
            assert await worker.read_configuration(
                {"kind": "target", "id": expected[0]["id"]}, "en"
            ) == {"kind": "target", "draft_revision": 12, "target": expected[0]}
            with pytest.raises(DraftError, match="^CHAT_NOT_FOUND$"):
                await worker.read_configuration({"kind": "target", "id": "missing"}, "en")
            inventory["targets"][0]["name"] = "observer changed copy"
            assert (await worker.targets_snapshot())["targets"] == expected
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == before


@pytest.mark.parametrize(
    "arguments",
    [
        {"kind": "targets", "offset": True, "limit": 1},
        {"kind": "targets", "offset": 0.0, "limit": 1},
        {"kind": "targets", "offset": -1, "limit": 1},
        {"kind": "targets", "offset": 101, "limit": 1},
        {"kind": "targets", "offset": 0, "limit": False},
        {"kind": "targets", "offset": 0, "limit": 1.0},
        {"kind": "targets", "offset": 0, "limit": 0},
        {"kind": "targets", "offset": 0, "limit": 11},
        {"kind": "targets", "offset": 0},
        {"kind": "targets", "offset": 0, "limit": 1, "extra": 0},
        {"kind": "target"},
        {"kind": "target", "id": 1},
        {"kind": "target", "id": "bad id"},
        {"kind": "target", "id": "valid", "extra": 0},
        {"kind": "definitely_unknown"},
    ],
)
def test_native_target_read_validation_is_closed(tmp_path, arguments):
    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                await worker.read_configuration(arguments, "en")
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert not draft.path.exists()


def test_manual_target_uses_shared_validation_and_preserves_no_guard_writer(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    real_validate, real_write = draft.validate_target_creation, draft._write
    validated, written = [], []

    def validate(state, value):
        validated.append(value.model_dump())
        return real_validate(state, value)

    def write(state):
        written.append(state.audit_total)
        return real_write(state)

    monkeypatch.setattr(draft, "validate_target_creation", validate)
    monkeypatch.setattr(draft, "_write", write)
    assert draft.create_target(TargetInput(**VALUE)).model_dump(include=set(VALUE)) == VALUE
    assert validated == [VALUE]
    assert written == [1]


@pytest.mark.parametrize(
    "address,accepted",
    [
        ("Example.COM.", True),
        ("localhost", True),
        ("127.0.0.1", True),
        ("2001:DB8::1", True),
        ("::ffff:192.0.2.1", True),
        ("123", False),
        ("127.000.0.1", False),
        ("fe80::1%eth0", False),
        ("http://example.com", False),
        (" example.com", False),
        ("example.com\n", False),
        ("a;touch-b", False),
    ],
)
def test_literal_validation_uses_actual_target_input_oracle(tmp_path, address, accepted):
    from pydantic import ValidationError

    value = VALUE | {"name": '  literal "\\ target 🌍  ', "address": address, "kind": "SINK"}
    if accepted:
        assert TargetInput(**value).model_dump() == value
    else:
        with pytest.raises(ValidationError):
            TargetInput(**value)
    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            if accepted:
                assert (await worker.prepare_target_create(0, **value))["after"] == value
                receipt = await worker.create_target(0, **value, publication_guard=lambda: None)
                assert {key: receipt["target"][key] for key in value} == value
                assert receipt["target"]["status"] == "draft"
            else:
                for execute in (False, True):
                    method = worker.create_target if execute else worker.prepare_target_create
                    kwargs = {"publication_guard": lambda: None} if execute else {}
                    with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                        await method(0, **value, **kwargs)
                assert not draft.path.exists()
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("interference", ["aba", "target", "settings"])
def test_prepare_does_not_rebase_execution_over_intervening_manual_writes(tmp_path, interference):
    from aiddos.api.models import AgentProfileInput, AISettingsInput

    draft = DraftStore(tmp_path / "draft.json")

    async def exercise():
        worker = DomainWorker(draft)
        try:
            await worker.prepare_target_create(0, **VALUE, expected_settings_revision=0)
            if interference == "aba":
                for name in ("Intervening", "Review agent"):
                    draft.save_agent_profile(
                        AgentProfileInput(name=name, skill_ids=[], mcp_server_ids=[])
                    )
            elif interference == "target":
                draft.create_target(TargetInput(**VALUE))
            else:
                draft.save_ai_settings(
                    AISettingsInput(
                        revision=0, profiles=[], default_profile_id=None, agent_profile_id=None
                    )
                )
            before = draft.path.read_bytes()
            with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                await worker.create_target(
                    0, **VALUE, publication_guard=lambda: None, expected_settings_revision=0
                )
            if interference == "settings":
                # Even a current draft CAS cannot substitute stale session settings.
                with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                    await worker.create_target(
                        1, **VALUE, publication_guard=lambda: None, expected_settings_revision=0
                    )
                with pytest.raises(DraftError, match="^CHAT_TOOL_CONFLICT$"):
                    await worker.prepare_target_create(1, **VALUE, expected_settings_revision=0)
            assert draft.path.read_bytes() == before
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_concurrent_guarded_creators_share_lock_and_only_one_cas_can_publish(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    one = DraftStore(tmp_path / "draft.json")
    two = DraftStore(tmp_path / "draft.json")
    assert one.lock is two.lock
    barrier = Barrier(2)
    guards = []

    def create(draft):
        barrier.wait(timeout=5)
        try:
            return draft.create_target_receipt(
                TargetInput(**VALUE),
                expected_draft_revision=0,
                publication_guard=lambda: guards.append(True),
            )
        except DraftError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, (one, two)))
    assert sum(isinstance(value, tuple) for value in outcomes) == 1
    assert outcomes.count("CHAT_TOOL_CONFLICT") == 1
    assert guards == [True]
    actual = one._read()
    assert actual.audit_total == len(actual.targets) == len(actual.audit) == 1
