"""Safe-counter, target capacity and exact validation-order regressions."""

import asyncio

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import AuditEvent, DraftState, Target, TargetInput
from aiddos.api.store import DraftStore

SAFE_INT = 9007199254740991
TIME = "2026-01-01T00:00:00+00:00"
VALUE = {"name": "Literal", "address": "Example.COM.", "kind": "DUT"}


def populated_state(revision, count=0):
    return DraftState(
        targets=[Target(**VALUE, id=f"old-target-{i}", created_at=TIME) for i in range(count)],
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
                    await worker.prepare_target_create(
                        SAFE_INT, **VALUE, expected_settings_revision=0
                    )
            elif operation == "execute":
                with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                    await worker.create_target(
                        SAFE_INT,
                        **VALUE,
                        publication_guard=lambda: None,
                        expected_settings_revision=0,
                    )
            else:
                with pytest.raises(DraftError, match="^AUDIT_LIMIT_REACHED$"):
                    if operation == "receipt":
                        draft.create_target_receipt(
                            TargetInput(**VALUE),
                            expected_draft_revision=SAFE_INT,
                            publication_guard=lambda: None,
                        )
                    else:
                        with draft.lock:
                            draft.validate_target_creation(draft._read(), TargetInput(**VALUE))
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
            prepared = await worker.prepare_target_create(SAFE_INT - 1, **VALUE)
            assert prepared["before_revision"] == SAFE_INT - 1
            receipt = await worker.create_target(
                SAFE_INT - 1, **VALUE, publication_guard=lambda: None
            )
            assert receipt["before_revision"] == SAFE_INT - 1
            assert receipt["after_revision"] == SAFE_INT
            actual = draft._read()
            assert actual.audit_total == SAFE_INT
            assert len(actual.audit) == 500
            assert actual.audit[:-1] == before.audit[1:]
            assert receipt["audit"] == actual.audit[-1].model_dump()
            assert receipt["target"] == actual.targets[-1].model_dump()
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
def test_cas_input_quota_headroom_precedence(
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
            method = worker.prepare_target_create
            if operation == "execute":
                method = worker.create_target
                kwargs["publication_guard"] = lambda: None
            with pytest.raises(DraftError, match=f"^{code}$"):
                await method(SAFE_INT - 1 if conflict == "revision" else SAFE_INT, **kwargs)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert allocations == []
    assert draft.path.read_bytes() == before


def test_target_100_allowed_101_refused_without_publication(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    draft._write(populated_state(99, 99))

    async def exercise():
        worker = DomainWorker(draft)
        try:
            await worker.prepare_target_create(99, **VALUE)
            receipt = await worker.create_target(99, **VALUE, publication_guard=lambda: None)
            assert receipt["after_revision"] == 100
            before = draft.path.read_bytes()
            for execute in (False, True):
                kwargs = {"publication_guard": lambda: None} if execute else {}
                method = worker.create_target if execute else worker.prepare_target_create
                with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                    await method(100, **VALUE, **kwargs)
                assert draft.path.read_bytes() == before
            assert len(draft._read().targets) == 100
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("name", ["🌍" * 120, '"\\' * 60], ids=["nonbmp", "escaping"])
def test_maximum_inventory_and_page_remain_complete_and_bounded(tmp_path, name, record_property):
    from aiddos.api.chat_models import encoded

    draft = DraftStore(tmp_path / "draft.json")
    state = populated_state(SAFE_INT, 100)
    address = ".".join(["a" * 63] * 3 + ["b" * 61]) + "."
    timestamp = "2026-01-01T00:00:00.12345678901234+00:00"
    assert len(address) == 254
    assert len(timestamp) == 40
    for i, target in enumerate(state.targets):
        target.id = f"{i:064d}"
        target.name, target.address, target.created_at = name, address, timestamp
    # Admit the witness under actual producer types before persistence.
    state = DraftState.model_validate(state.model_dump())
    draft._write(state)
    original = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            inspection = await worker.targets_snapshot()
            assert inspection == {
                "schema_version": 1,
                "draft_revision": SAFE_INT,
                "targets": [target.model_dump() for target in state.targets],
            }
            assert len(encoded(inspection)) <= 131072
            record_property("inspection_bytes", len(encoded(inspection)))
            pages = []
            for offset in range(0, 100, 10):
                page = await worker.read_configuration(
                    {"kind": "targets", "offset": offset, "limit": 10}, "en"
                )
                assert page["draft_revision"] == SAFE_INT
                assert page["next_offset"] == (offset + 10 if offset < 90 else None)
                assert len(encoded(page)) <= 32768
                pages.extend(page["items"])
            record_property("last_page_bytes", len(encoded(page)))
            assert pages == inspection["targets"]
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == original


@pytest.mark.parametrize("surface,cap", [("inspection", 131072), ("page", 32768)])
def test_projection_encoded_cap_is_enforced_not_truncated(tmp_path, monkeypatch, surface, cap):
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    encoded_sizes = []

    async def exercise():
        worker = DomainWorker(draft)
        try:
            for size in (cap, cap + 1):

                def encode(value, size=size):
                    encoded_sizes.append(size)
                    return b"x" * size

                monkeypatch.setattr(module, "encoded", encode)
                if surface == "inspection":
                    operation = worker.targets_snapshot()
                else:
                    operation = worker.read_configuration(
                        {"kind": "targets", "offset": 0, "limit": 1}, "en"
                    )
                if size == cap:
                    result = await operation
                    assert result["draft_revision"] == 0
                else:
                    with pytest.raises(DraftError, match="^CHAT_TOOL_LIMIT$"):
                        await operation
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert encoded_sizes == [cap, cap + 1]
    assert not draft.path.exists()


def test_manual_saturated_counter_retains_public_error_and_status(client, state_path):
    draft = DraftStore(state_path)
    draft._write(populated_state(SAFE_INT))
    original = state_path.read_bytes()
    response = client.post("/api/v1/targets", json=VALUE)
    assert response.status_code == 409
    assert response.json()["code"] == "AUDIT_LIMIT_REACHED"
    assert state_path.read_bytes() == original
