"""Deterministic native barriers: no HTTP or SQLite impersonation."""

import asyncio
import threading

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.store import DraftStore


async def entered(event):
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def retired(worker):
    async with asyncio.timeout(2):
        while worker.busy:
            await asyncio.sleep(0.001)


def test_read_cancellation_holds_capacity_and_metadata_refuses_without_queue(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    started, release = threading.Event(), threading.Event()
    real_read = draft._read
    threads = []

    def read():
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(3)
        return real_read()

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        assert worker._executor is None
        task = asyncio.create_task(worker.ai_snapshot())
        try:
            await entered(started)

            assert threads[0] != threading.get_ident()
            assert not draft.lock.acquire(blocking=False)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert worker.busy
            for operation in (
                worker.ai_snapshot,
                worker.snapshot,
                lambda: worker.prepare_update(0, "Name", []),
                lambda: worker.read_configuration({"kind": "agent_profile"}, "en"),
            ):
                async with asyncio.timeout(0.2):
                    with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                        await operation()
            assert len(threads) == 1  # no replacement submitted or queued
        finally:
            release.set()
            await retired(worker)
            assert (await worker.ai_snapshot())["revision"] == 0
            await worker.shutdown()
        assert not worker.busy
        assert len(threads) == 2 and threads[0] == threads[1]
        assert all(not t.is_alive() for t in worker._executor._threads)

    asyncio.run(exercise())
    assert not draft.path.exists()


def test_shutdown_keeps_ownership_until_native_retirement_and_never_reopens(tmp_path, monkeypatch):
    draft = DraftStore(tmp_path / "draft.json")
    started, release = threading.Event(), threading.Event()
    real_read = draft._read

    def read():
        started.set()
        assert release.wait(3)
        return real_read()

    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        task = asyncio.create_task(worker.snapshot())
        await entered(started)
        close = asyncio.create_task(worker.shutdown())
        try:
            await asyncio.sleep(0)
            close.cancel()
            await asyncio.sleep(0)
            assert worker.busy
            async with asyncio.timeout(0.2):
                with pytest.raises(DraftError, match="^CHAT_BUSY$"):
                    await worker.ai_snapshot()
            assert not close.done()
        finally:
            release.set()
            await asyncio.gather(task, close, return_exceptions=True)
            await worker.shutdown()
        assert not worker.busy
        with pytest.raises(DraftError, match="^CHAT_BUSY$"):
            await worker.ai_snapshot()
        assert all(not t.is_alive() for t in worker._executor._threads)

    asyncio.run(exercise())
