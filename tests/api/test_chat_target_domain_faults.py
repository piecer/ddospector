"""Actual storage injection selectors, publication outcomes and ownership controls."""

import asyncio
import os
import threading
from time import monotonic

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import TargetInput
from aiddos.api.store import DraftStore

VALUE = TargetInput(name="literal target", address="Example.COM.", kind="DUT")


def test_target_guard_after_file_sync_before_replace(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    draft.create_target(VALUE)
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
        draft.create_target_receipt(VALUE, expected_draft_revision=1, publication_guard=deny)
    assert events == ["sync", "guard"]
    assert draft.path.read_bytes() == before
    assert list(tmp_path.glob(".ui-drafts-*")) == []
    events.clear()
    draft.create_target_receipt(
        VALUE, expected_draft_revision=1, publication_guard=lambda: events.append("guard")
    )
    assert events == ["sync", "guard", "replace", "sync"]


@pytest.mark.parametrize(
    "seam",
    [
        "temp",
        "file_sync",
        "replace",
        "directory_sync",
        "readback",
        "target",
        "audit",
        "revision",
        "unrelated",
        "retained_target",
    ],
)
@pytest.mark.parametrize("surface", ["store", "worker"])
def test_target_faults_fire_once_and_compare_complete_state(tmp_path, monkeypatch, seam, surface):
    import aiddos.api.store as module

    draft = DraftStore(tmp_path / "draft.json")
    draft.create_target(VALUE)
    before = draft.path.read_bytes()
    real_sync, real_replace, real_read = os.fsync, os.replace, draft._read
    real_temp = module.tempfile.mkstemp
    fired, published, sync_calls = [], [], []

    def temp(*args, **kwargs):
        if seam == "temp":
            fired.append(seam)
            raise OSError("private")
        return real_temp(*args, **kwargs)

    def sync(fd):
        sync_calls.append(fd)
        if (seam == "file_sync" and len(sync_calls) == 1) or (
            seam == "directory_sync" and len(sync_calls) == 2
        ):
            fired.append(seam)
            raise OSError("private")
        return real_sync(fd)

    def replace(*args):
        if seam == "replace":
            fired.append(seam)
            raise OSError("private")
        real_replace(*args)
        published.append(True)

    def read():
        state = real_read()
        if published and seam not in {"temp", "file_sync", "replace", "directory_sync"}:
            fired.append(seam)
            if seam == "readback":
                raise DraftError("STATE_UNAVAILABLE")
            if seam == "target":
                state.targets[-1].name = "Changed"
            elif seam == "audit":
                state.audit[-1].id = "foreign-event"
            elif seam == "revision":
                state.audit_total += 1
            elif seam == "unrelated":
                state.agent_profile.name = "Changed"
            elif seam == "retained_target":
                state.targets[0].address = "other.example"
        return state

    monkeypatch.setattr(module.tempfile, "mkstemp", temp)
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(draft, "_read", read)
    prepublication = seam in {"temp", "file_sync", "replace"}
    if surface == "store":
        code = "STATE_UNAVAILABLE" if prepublication else "STATE_COMMIT_UNCERTAIN"
        with pytest.raises(DraftError, match=f"^{code}$"):
            draft.create_target_receipt(
                VALUE, expected_draft_revision=1, publication_guard=lambda: None
            )
    else:

        async def exercise():
            worker = DomainWorker(draft)
            try:
                code = "CHAT_STORAGE_ERROR" if prepublication else "CHAT_TOOL_UNCERTAIN"
                with pytest.raises(DraftError, match=f"^{code}$"):
                    await worker.create_target(
                        1, **VALUE.model_dump(), publication_guard=lambda: None
                    )
            finally:
                await worker.shutdown()

        asyncio.run(exercise())
    assert fired == [seam]
    assert published == ([] if prepublication else [True])
    if prepublication:
        assert draft.path.read_bytes() == before
    else:
        actual = real_read()
        assert actual.audit_total == len(actual.targets) == len(actual.audit) == 2
        assert (
            actual.targets[-1].model_dump(include={"name", "address", "kind"}) == VALUE.model_dump()
        )
    assert list(tmp_path.glob(".ui-drafts-*")) == []


@pytest.mark.parametrize("published", [False, True])
def test_unclassified_mutation_failure_is_uncertain_and_never_retried(
    tmp_path, monkeypatch, published
):
    draft = DraftStore(tmp_path / "draft.json")
    real_write, fired = draft._write, []

    def write(state, **kwargs):
        fired.append(True)
        if published:
            real_write(state, **kwargs)
        raise RuntimeError("private fault")

    monkeypatch.setattr(draft, "_write", write)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_TOOL_UNCERTAIN$"):
                await worker.create_target(0, **VALUE.model_dump(), publication_guard=lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert fired == [True]
    assert draft._read().audit_total == (1 if published else 0)
    assert len(draft._read().targets) == (1 if published else 0)


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
                await worker.create_target(
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
                await worker.create_target(
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
            worker.create_target(0, **VALUE.model_dump(), publication_guard=lambda: None)
        )
        try:
            await wait_for(entered)
            assert worker.busy
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.targets_snapshot()
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.prepare_target_create(0, **VALUE.model_dump())
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
                assert receipt["target"] == draft._read().targets[0].model_dump()
            assert not worker.busy
        finally:
            release.set()
            await worker.shutdown()
        assert not worker._thread.is_alive()

    asyncio.run(exercise())
    assert len(calls) == (1 if phase == "file" else 2)
    assert list(tmp_path.glob(".ui-drafts-*")) == []


def test_cancelled_inspection_keeps_native_lease_and_loop_responsive(tmp_path, monkeypatch):
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
        task = asyncio.create_task(worker.targets_snapshot())
        try:
            await wait_for(entered)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert worker.busy
            with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                await worker.targets_snapshot()
            release.set()
            await worker.settle()
            assert not worker.busy
        finally:
            release.set()
            await worker.shutdown()
        assert not worker._thread.is_alive()

    asyncio.run(exercise())
    assert not draft.path.exists()


@pytest.mark.parametrize("operation", ["prepare", "create", "snapshot", "read"])
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
                    await worker.prepare_target_create(1, **VALUE.model_dump(), **kwargs)
                elif operation == "create":
                    await worker.create_target(
                        1, **VALUE.model_dump(), publication_guard=lambda: None, **kwargs
                    )
                elif operation == "snapshot":
                    await worker.targets_snapshot(**kwargs)
                else:
                    await worker.read_configuration(
                        {"kind": "targets", "offset": 0, "limit": 1}, "en", **kwargs
                    )
        finally:
            await worker.shutdown()
        assert worker._executor is None

    asyncio.run(exercise())
    assert reads == []


@pytest.mark.parametrize("operation", ["prepare", "snapshot", "read"])
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
                    await worker.prepare_target_create(0, **VALUE.model_dump(), deadline=10.0)
                elif operation == "snapshot":
                    await worker.targets_snapshot(deadline=10.0)
                else:
                    await worker.read_configuration(
                        {"kind": "targets", "offset": 0, "limit": 1}, "en", deadline=10.0
                    )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert reads == [True]
    assert not draft.path.exists()


@pytest.mark.parametrize("corruption", ["malformed", "duplicate", "unavailable"])
def test_target_reads_fail_closed_on_actual_store_errors(tmp_path, corruption):
    import json

    draft = DraftStore(tmp_path / "draft.json")
    draft.create_target(VALUE)
    if corruption == "malformed":
        draft.path.write_bytes(b"{")
    elif corruption == "duplicate":
        state = json.loads(draft.path.read_bytes())
        state["targets"].append(state["targets"][0])
        draft.path.write_text(json.dumps(state))
    else:
        target = tmp_path / "actual.json"
        draft.path.rename(target)
        draft.path.symlink_to(target)
    original = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_STORAGE_ERROR$"):
                await worker.targets_snapshot()
            with pytest.raises(DraftError, match="^CHAT_STORAGE_ERROR$"):
                await worker.read_configuration({"kind": "targets", "offset": 0, "limit": 1}, "en")
            with pytest.raises(DraftError, match="^CHAT_STORAGE_ERROR$"):
                await worker.create_target(1, **VALUE.model_dump(), publication_guard=lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == original


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
        return draft.create_target_receipt(
            VALUE, expected_draft_revision=0, publication_guard=lambda: None
        )

    def peer_create():
        peer_attempt.set()
        return peer.create_target(VALUE)

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
        target, audit = first.result(timeout=5)
        other = second.result(timeout=5)
    actual = peer._read()
    assert actual.targets == [target, other]
    assert actual.audit[0] == audit
    assert actual.audit_total == 2
    assert len(reads) == 2
