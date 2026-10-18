import asyncio
import os
import threading
from time import monotonic

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.store import DraftStore


async def entered(event):
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("reason", ["stop", "deadline", "task_cancel", "shutdown"])
def test_final_gate_refuses_after_blocked_fsync_while_metadata_and_stop_remain_responsive(
    tmp_path, monkeypatch, reason
):
    import aiddos.api.chat_tool_domain as domain

    draft = DraftStore(tmp_path / "draft.json")
    started, release, stop = threading.Event(), threading.Event(), threading.Event()
    real_sync, real_replace = os.fsync, os.replace
    events = []
    clock = [monotonic()]
    deadline = clock[0] + 120
    monkeypatch.setattr(domain, "monotonic", lambda: clock[0], raising=False)

    def sync(fd):
        real_sync(fd)
        events.append("file_sync")
        started.set()
        assert release.wait(3)

    def replace(*args):
        events.append("replace")
        return real_replace(*args)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(
            worker.update_agent_profile(
                0,
                "Never saved",
                [],
                lambda: events.append("identity_guard"),
                deadline=deadline,
                stop=stop,
            )
        )
        close = None
        try:
            await entered(started)
            async with asyncio.timeout(0.2):
                assert not draft.lock.acquire(blocking=False)
                with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                    await worker.ai_snapshot()
                if reason == "stop":
                    stop.set()
                elif reason == "deadline":
                    clock[0] = deadline
                elif reason == "task_cancel":
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()  # repeated cancellation cannot detach settlement
                else:
                    close = asyncio.create_task(worker.shutdown())
                await asyncio.sleep(0)
                assert worker.busy
                assert not task.done()
            release.set()
            code = "CHAT_TIMEOUT" if reason == "deadline" else "CHAT_CANCELLED"
            with pytest.raises(DraftError, match="^" + code + "$"):
                await task
            assert events == ["file_sync"]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            if close:
                await close
            await worker.shutdown()
        assert not worker.busy

    asyncio.run(exercise())
    assert not draft.path.exists()
    assert list(tmp_path.glob(".ui-drafts-*")) == []


def test_cancel_after_publication_keeps_success_and_readback_before_retirement(
    tmp_path, monkeypatch
):
    draft = DraftStore(tmp_path / "draft.json")
    published, release, stop = threading.Event(), threading.Event(), threading.Event()
    real_replace, real_read = os.replace, draft._read
    observed = []

    def replace(*args):
        result = real_replace(*args)
        published.set()
        assert release.wait(3)
        return result

    def read():
        state = real_read()
        if published.is_set():
            observed.append(state.agent_profile.name)
        return state

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(
            worker.update_agent_profile(
                0, "Saved", [], lambda: None, deadline=monotonic() + 120, stop=stop
            )
        )
        try:
            await entered(published)
            assert not draft.lock.acquire(blocking=False)
            stop.set()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert worker.busy
            release.set()
            result = await task
            assert result["agent_profile"]["name"] == "Saved"
            assert result["after_revision"] == 1
            assert observed == ["Saved"]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await worker.shutdown()

    asyncio.run(exercise())
    assert real_read().audit_total == 1


def test_admitted_write_freezes_desired_skill_list_before_native_wait(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    started, release = threading.Event(), threading.Event()
    real_read = draft._read
    ids = ["policy-validation"]

    def read():
        started.set()
        assert release.wait(3)
        return real_read()

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(worker.update_agent_profile(0, "Approved", ids, lambda: None))
        try:
            await entered(started)
            ids.clear()
            release.set()
            result = await task
            assert result["agent_profile"]["skill_ids"] == ["policy-validation"]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await worker.shutdown()

    asyncio.run(exercise())
    assert real_read().agent_profile.skill_ids == ["policy-validation"]


def test_original_deadline_is_rechecked_after_identity_guard(tmp_path, monkeypatch):
    import aiddos.api.chat_tool_domain as domain

    draft = DraftStore(tmp_path / "draft.json")
    clock = [100.0]
    fired = []
    monkeypatch.setattr(domain, "monotonic", lambda: clock[0])

    def identity():
        fired.append(True)
        clock[0] = 120.0

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_TIMEOUT$"):
                await worker.update_agent_profile(0, "Expired", [], identity, deadline=120.0)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert fired == [True]
    assert not draft.path.exists()


@pytest.mark.parametrize("operation", ["ai_snapshot", "snapshot", "read", "prepare"])
def test_original_read_deadline_is_rechecked_after_blocked_native_io(
    tmp_path, monkeypatch, operation
):
    import aiddos.api.chat_tool_domain as domain

    draft = DraftStore(tmp_path / "draft.json")
    started, release = threading.Event(), threading.Event()
    clock = [100.0]
    real_read = draft._read
    monkeypatch.setattr(domain, "monotonic", lambda: clock[0])

    def read():
        started.set()
        assert release.wait(3)
        return real_read()

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        if operation == "read":
            work = worker.read_configuration({"kind": "agent_profile"}, "en", deadline=120.0)
        elif operation == "prepare":
            work = worker.prepare_update(0, "Name", [], deadline=120.0)
        else:
            work = getattr(worker, operation)(deadline=120.0)
        task = asyncio.create_task(work)
        try:
            await entered(started)
            clock[0] = 120.0
            release.set()
            with pytest.raises(DraftError, match="^CHAT_TIMEOUT$"):
                await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await worker.shutdown()

    asyncio.run(exercise())
    assert not draft.path.exists()
