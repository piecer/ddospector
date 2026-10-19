"""Actual Skill publication fault seams; each injection must fire exactly once."""

import asyncio
import os
import threading
from time import monotonic

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import AgentProfileInput, SkillInput
from aiddos.api.store import DraftStore

VALUE = SkillInput(
    name="literal", description="description", instructions="inert", category="planning"
)


def invoke(draft, surface, revision, code, guard=lambda: None):
    if surface == "store":
        with pytest.raises(DraftError, match=f"^{code}$"):
            draft.create_skill_receipt(
                VALUE, expected_draft_revision=revision, publication_guard=guard
            )
    else:

        async def exercise():
            worker = DomainWorker(draft)
            try:
                with pytest.raises(DraftError, match=f"^{code}$"):
                    await worker.create_skill(
                        revision, **VALUE.model_dump(), publication_guard=guard
                    )
            finally:
                await worker.shutdown()

        asyncio.run(exercise())


@pytest.mark.parametrize("seam", ["temp", "file_sync", "replace", "directory_sync", "readback"])
@pytest.mark.parametrize("surface", ["store", "worker"])
def test_publication_boundary_faults(tmp_path, monkeypatch, seam, surface):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    draft.create_skill(VALUE)
    before = draft.path.read_bytes()
    real_temp, real_sync = module.tempfile.mkstemp, os.fsync
    real_replace, real_read = os.replace, draft._read
    fired, published, syncs = [], [], []

    def temp(*args, **kwargs):
        if seam == "temp":
            fired.append(seam)
            raise OSError("injected temp refusal")
        return real_temp(*args, **kwargs)

    def sync(fd):
        syncs.append(fd)
        if (seam == "file_sync" and len(syncs) == 1) or (
            seam == "directory_sync" and len(syncs) == 2
        ):
            fired.append(seam)
            raise OSError("injected sync failure")
        return real_sync(fd)

    def replace(*args):
        if seam == "replace":
            fired.append(seam)
            raise OSError("injected replace refusal")
        real_replace(*args)
        published.append(True)

    def read():
        if published and seam == "readback":
            fired.append(seam)
            raise DraftError("STATE_UNAVAILABLE")
        return real_read()

    monkeypatch.setattr(module.tempfile, "mkstemp", temp)
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(draft, "_read", read)
    pre = seam in {"temp", "file_sync", "replace"}
    code = (
        ("STATE_UNAVAILABLE" if pre else "STATE_COMMIT_UNCERTAIN")
        if surface == "store"
        else ("CHAT_STORAGE_ERROR" if pre else "CHAT_TOOL_UNCERTAIN")
    )
    try:
        invoke(draft, surface, 1, code)
    finally:
        assert fired == [seam]
        assert published == ([] if pre else [True])
    if pre:
        assert draft.path.read_bytes() == before
    else:
        actual = real_read()
        assert actual.audit_total == len(actual.skills) == len(actual.audit) == 2
    assert list(tmp_path.glob(".ui-drafts-*")) == []


@pytest.mark.parametrize(
    "seam", ["skill", "audit", "revision", "prior_skill", "assignment", "settings"]
)
@pytest.mark.parametrize("surface", ["store", "worker"])
def test_full_readback_mismatch_is_uncertain(tmp_path, monkeypatch, seam, surface):
    draft = DraftStore(tmp_path / "draft.json")
    old = draft.create_skill(VALUE)
    draft.save_agent_profile(
        AgentProfileInput(name="Assigned", skill_ids=[old.id], mcp_server_ids=[])
    )
    real_read, real_replace = draft._read, os.replace
    fired, published = [], []

    def replace(*args):
        real_replace(*args)
        published.append(True)

    def read():
        state = real_read()
        if published:
            fired.append(seam)
            if seam == "skill":
                state.skills[-1].instructions.en = "changed"
            elif seam == "audit":
                state.audit[-1].id = "foreign-audit"
            elif seam == "revision":
                state.audit_total += 1
            elif seam == "prior_skill":
                state.skills[0].description.en = "changed"
            elif seam == "assignment":
                state.agent_profile.skill_ids = []
            else:
                state.ai_settings.connection_status = "changed"
        return state

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(draft, "_read", read)
    try:
        invoke(
            draft,
            surface,
            2,
            "STATE_COMMIT_UNCERTAIN" if surface == "store" else "CHAT_TOOL_UNCERTAIN",
        )
    finally:
        assert fired == [seam]
        assert published == [True]
    actual = real_read()
    assert actual.audit_total == 3 and len(actual.skills) == 2
    assert actual.agent_profile.skill_ids == [old.id]


@pytest.mark.parametrize("published", [False, True])
def test_unclassified_mutation_failure_is_uncertain(tmp_path, monkeypatch, published):
    draft = DraftStore(tmp_path / "draft.json")
    real_write, fired = draft._write, []

    def write(state, **kwargs):
        fired.append(True)
        if published:
            real_write(state, **kwargs)
        raise RuntimeError("unexpected fault after mutation entry")

    monkeypatch.setattr(draft, "_write", write)
    try:
        invoke(draft, "worker", 0, "CHAT_TOOL_UNCERTAIN")
    finally:
        assert fired == [True]
    assert draft._read().audit_total == (1 if published else 0)


def test_skill_guard_after_file_sync_before_replace(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    draft.create_skill(VALUE)
    before = draft.path.read_bytes()
    events = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd):
        events.append("sync")
        return real_sync(fd)

    def replace(*args):
        events.append("replace")
        return real_replace(*args)

    def deny():
        events.append("guard")
        raise DraftError("CHAT_CANCELLED")

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(DraftError, match="^CHAT_CANCELLED$"):
        draft.create_skill_receipt(VALUE, expected_draft_revision=1, publication_guard=deny)
    assert events == ["sync", "guard"]
    assert draft.path.read_bytes() == before
    assert list(tmp_path.glob(".ui-drafts-*")) == []
    events.clear()
    draft.create_skill_receipt(
        VALUE, expected_draft_revision=1, publication_guard=lambda: events.append("guard")
    )
    assert events == ["sync", "guard", "replace", "sync"]


@pytest.mark.parametrize("reason", ["stop", "deadline", "stop_and_deadline", "guard"])
def test_worker_rechecks_stop_and_original_deadline_at_publication(tmp_path, monkeypatch, reason):
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    stop = threading.Event()
    clock = [0.0]
    real_sync = os.fsync
    synced, guards = [], []
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    def sync(fd):
        real_sync(fd)
        synced.append(True)
        if reason in {"stop", "stop_and_deadline"}:
            stop.set()
        if reason in {"deadline", "stop_and_deadline"}:
            clock[0] = 10.0

    def guard():
        guards.append(True)
        raise DraftError("CHAT_TOOL_GRANT_INVALID")

    monkeypatch.setattr(os, "fsync", sync)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            code = {"deadline": "CHAT_TIMEOUT", "guard": "CHAT_TOOL_GRANT_INVALID"}.get(
                reason, "CHAT_CANCELLED"
            )
            with pytest.raises(DraftError, match=f"^{code}$"):
                await worker.create_skill(
                    0, **VALUE.model_dump(), publication_guard=guard, deadline=10.0, stop=stop
                )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert synced == [True]
    assert guards == ([True] if reason == "guard" else [])
    assert not draft.path.exists()
    assert list(tmp_path.glob(".ui-drafts-*")) == []


@pytest.mark.parametrize("reason", ["stop", "deadline"])
def test_worker_checks_after_synchronous_approval_guard(tmp_path, monkeypatch, reason):
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    stop, clock, guards = threading.Event(), [0.0], []
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    def guard():
        guards.append(True)
        if reason == "stop":
            stop.set()
        else:
            clock[0] = 10.0

    async def exercise():
        worker = DomainWorker(draft)
        try:
            code = "CHAT_CANCELLED" if reason == "stop" else "CHAT_TIMEOUT"
            with pytest.raises(DraftError, match=f"^{code}$"):
                await worker.create_skill(
                    0, **VALUE.model_dump(), publication_guard=guard, deadline=10.0, stop=stop
                )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert guards == [True]
    assert not draft.path.exists()


async def wait_for(event):
    async with asyncio.timeout(5):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("phase", ["file", "directory"])
def test_write_cancellation_retains_single_worker_until_settlement(tmp_path, monkeypatch, phase):
    draft = DraftStore(tmp_path / "draft.json")
    entered, release = threading.Event(), threading.Event()
    real_sync, calls = os.fsync, []

    def sync(fd):
        calls.append(fd)
        if len(calls) == (1 if phase == "file" else 2):
            entered.set()
            assert release.wait(5), "owner never released native fixture"
        real_sync(fd)

    monkeypatch.setattr(os, "fsync", sync)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(
            worker.create_skill(0, **VALUE.model_dump(), publication_guard=lambda: None)
        )
        try:
            await wait_for(entered)
            assert worker.busy
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.skills_snapshot()
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.prepare_skill_create(0, **VALUE.model_dump())
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert worker.busy
            release.set()
            if phase == "file":
                with pytest.raises(DraftError, match="^CHAT_CANCELLED$"):
                    await task
                assert not draft.path.exists()
            else:
                receipt = await task
                assert receipt["after_revision"] == 1
                assert receipt["skill"] == draft._read().skills[0].model_dump()
            assert not worker.busy
        finally:
            release.set()
            await worker.shutdown()
        assert not worker._thread.is_alive()

    asyncio.run(exercise())
    assert len(calls) == (1 if phase == "file" else 2)
    assert list(tmp_path.glob(".ui-drafts-*")) == []


@pytest.mark.parametrize("operation", ["prepare", "create", "snapshot", "detail", "read"])
@pytest.mark.parametrize("reason", ["stop", "deadline", "both"])
def test_pre_admission_stop_deadline_precedence_no_draft_read(
    tmp_path, monkeypatch, operation, reason
):
    draft = DraftStore(tmp_path / "draft.json")
    reads = []

    def read():
        reads.append(True)
        raise AssertionError("expired or stopped operation read state")

    monkeypatch.setattr(draft, "_read", read)
    stop = threading.Event()
    if reason in {"stop", "both"}:
        stop.set()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            kwargs = {"stop": stop, "deadline": monotonic() - 1 if reason != "stop" else None}
            code = "CHAT_TIMEOUT" if reason == "deadline" else "CHAT_CANCELLED"
            with pytest.raises(DraftError, match=f"^{code}$"):
                if operation == "prepare":
                    await worker.prepare_skill_create(1, **VALUE.model_dump(), **kwargs)
                elif operation == "create":
                    await worker.create_skill(
                        1, **VALUE.model_dump(), publication_guard=lambda: None, **kwargs
                    )
                elif operation == "snapshot":
                    await worker.skills_snapshot(**kwargs)
                elif operation == "detail":
                    await worker.skill_snapshot("missing-skill", **kwargs)
                else:
                    await worker.read_configuration(
                        {"kind": "skills", "offset": 0, "limit": 1}, "en", **kwargs
                    )
        finally:
            await worker.shutdown()
        assert worker._executor is None

    asyncio.run(exercise())
    assert reads == []


@pytest.mark.parametrize("operation", ["prepare", "snapshot", "detail", "read"])
def test_delayed_read_cannot_return_after_original_deadline(tmp_path, monkeypatch, operation):
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    real_read = draft._read
    clock, reads = [0.0], []
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    def read():
        state = real_read()
        reads.append(True)
        clock[0] = 10.0
        return state

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_TIMEOUT$"):
                if operation == "prepare":
                    await worker.prepare_skill_create(0, **VALUE.model_dump(), deadline=10.0)
                elif operation == "snapshot":
                    await worker.skills_snapshot(deadline=10.0)
                elif operation == "detail":
                    from aiddos.api.catalog import SKILLS_V1

                    await worker.skill_snapshot(SKILLS_V1[0]["id"], deadline=10.0)
                else:
                    await worker.read_configuration(
                        {"kind": "skills", "offset": 0, "limit": 1}, "en", deadline=10.0
                    )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert reads == [True]
    assert not draft.path.exists()


def test_receipt_holds_shared_draft_lock_through_authoritative_readback(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    draft = DraftStore(tmp_path / "draft.json")
    peer = DraftStore(draft.path)
    readback, release, peer_attempt = threading.Event(), threading.Event(), threading.Event()
    real_read = draft._read
    reads = []

    def read():
        state = real_read()
        reads.append(True)
        if len(reads) == 2:
            readback.set()
            assert release.wait(5), "receipt readback fixture not released"
        return state

    def create():
        return draft.create_skill_receipt(
            VALUE, expected_draft_revision=0, publication_guard=lambda: None
        )

    def peer_create():
        peer_attempt.set()
        return peer.create_skill(VALUE)

    monkeypatch.setattr(draft, "_read", read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(create)
        try:
            assert readback.wait(5)
            second = pool.submit(peer_create)
            assert peer_attempt.wait(5)
            assert not second.done()
        finally:
            release.set()
        skill, audit = first.result(timeout=5)
        other = second.result(timeout=5)
    actual = peer._read()
    assert actual.skills == [skill, other]
    assert actual.audit[0] == audit
    assert actual.audit_total == 2
    assert len(reads) == 2


@pytest.mark.parametrize("reason", ["stop", "deadline"])
def test_original_clock_rechecked_after_path_lock_acquisition(tmp_path, monkeypatch, reason):
    import aiddos.api.chat_tool_domain as module

    draft = DraftStore(tmp_path / "draft.json")
    stop, clock, reads = threading.Event(), [0.0], []
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    def read():
        reads.append(True)
        raise AssertionError("expired operation read under the path lock")

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        draft.lock.acquire()
        task = asyncio.create_task(
            worker.create_skill(
                0, **VALUE.model_dump(), publication_guard=lambda: None, stop=stop, deadline=10.0
            )
        )
        try:
            async with asyncio.timeout(5):
                while worker._thread is None:
                    await asyncio.sleep(0.001)
            if reason == "stop":
                stop.set()
            else:
                clock[0] = 10.0
        finally:
            draft.lock.release()
        try:
            code = "CHAT_CANCELLED" if reason == "stop" else "CHAT_TIMEOUT"
            with pytest.raises(DraftError, match=f"^{code}$"):
                await task
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert reads == []
    assert not draft.path.exists()


def test_two_workers_same_cas_publish_once(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    peer = DraftStore(draft.path)
    publications = []
    real_replace = os.replace

    def replace(*args):
        real_replace(*args)
        publications.append(True)

    monkeypatch.setattr(os, "replace", replace)

    async def exercise():
        workers = [DomainWorker(draft), DomainWorker(peer)]
        try:
            results = await asyncio.gather(
                *[
                    worker.create_skill(0, **VALUE.model_dump(), publication_guard=lambda: None)
                    for worker in workers
                ],
                return_exceptions=True,
            )
            receipts = [r for r in results if isinstance(r, dict)]
            errors = [r for r in results if isinstance(r, DraftError)]
            assert len(receipts) == len(errors) == 1
            assert errors[0].code == "CHAT_TOOL_CONFLICT"
            state = draft._read()
            assert receipts[0]["skill"] == state.skills[0].model_dump()
            assert receipts[0]["audit"] == state.audit[0].model_dump()
            assert state.audit_total == len(state.skills) == 1
        finally:
            for worker in workers:
                await worker.shutdown()

    asyncio.run(exercise())
    assert publications == [True]
