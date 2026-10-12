"""Process-rooted API custody. Response completion is not resource retirement."""

import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical

_ROOT = None


class Operation:
    def __init__(self, owner, deadline):
        self.owner = owner
        self.deadline = deadline
        self.revoked = False
        self.commit_issued = False
        self.response = asyncio.get_running_loop().create_future()
        self.coordinator = None
        self.source_future = None
        self.source_waiter = None
        self.driver_task = None
        self.connect_task = None
        self.connection = None
        self.transaction = None
        self.close_attempted = False
        self.cleanup_pending = False
        self.cancel_sent = False
        self.disposal = []
        self.primary = None

    def error(self):
        return DraftError("RUN_COMMIT_UNCERTAIN" if self.commit_issued else "RUN_DB_UNAVAILABLE")

    def checkpoint(self):
        if self.revoked or time.monotonic() >= self.deadline:
            self.revoked = True
            raise self.error()

    def revoke(self):
        self.revoked = True
        if self.driver_task is not None and not self.driver_task.done() and not self.cancel_sent:
            self.cancel_sent = True
            self.driver_task.cancel()

    async def call(self, factory, *, connect=False, commit=False):
        self.checkpoint()
        if commit:
            self.commit_issued = True
        task = asyncio.create_task(factory())
        if connect:
            assert self.connect_task is None
            self.connect_task = task
        else:
            self.driver_task = task
        done, _ = await asyncio.wait(
            {task}, timeout=min(2.0, max(0, self.deadline - time.monotonic()))
        )
        if not done:
            self.revoke()
            raise self.error()
        value = task.result()
        if connect:
            self.connection = value
        self.checkpoint()
        return value

    async def capture(self, peer, request):
        from .source import capture

        self.checkpoint()
        assert self.source_future is None
        self.source_future = self.owner.executor.submit(capture, peer, request)
        self.source_waiter = asyncio.wrap_future(self.source_future)
        done, _ = await asyncio.wait(
            {self.source_waiter}, timeout=max(0, self.deadline - time.monotonic())
        )
        self.checkpoint()
        if not done:
            self.revoke()
            raise self.error()
        return self.source_waiter.result()

    async def execute(self, sql, args=None):
        async def query():
            cursor = await self.connection.execute(sql, args)
            return await cursor.fetchall() if cursor.description else []

        return await self.call(query)

    async def retire(self):
        # This coordinator itself remains rooted during every delayed finalizer.
        if self.source_waiter is not None:
            try:
                await asyncio.shield(self.source_waiter)
            except BaseException:
                self.disposal.append("SOURCE_SETTLED_ERROR")
        if self.connect_task is not None:
            try:
                self.connection = await asyncio.shield(self.connect_task)
            except BaseException:
                self.disposal.append("CONNECT_SETTLED_ERROR")
        if self.driver_task is not None:
            try:
                await asyncio.shield(self.driver_task)
            except BaseException:
                self.disposal.append("DRIVER_SETTLED_ERROR")
        if self.connection is not None:
            self.cleanup_pending = True
            if self.transaction is not None:
                tx, self.transaction = self.transaction, None
                try:
                    await tx.__aexit__(DraftError, self.error(), None)
                except BaseException:
                    self.disposal.append("ROLLBACK_ERROR")
            if not self.close_attempted:
                self.close_attempted = True
                try:
                    await self.connection.close()
                except BaseException:
                    self.disposal.append("CLOSE_ERROR")
            self.cleanup_pending = False

    def settled(self):
        return (
            (self.source_future is None or self.source_future.done())
            and all(task is None or task.done() for task in (self.connect_task, self.driver_task))
            and (self.connection is None or self.connection.closed is True)
        )

    async def run(self, work):
        try:
            value = await work(self)
            self.checkpoint()
            if not self.response.done():
                self.response.set_result((value, None))
        except BaseException as exc:
            self.primary = exc
            pg = sys.modules.get("psycopg")
            if pg is not None and isinstance(exc, pg.Error):
                sqlstate = exc.sqlstate
                if sqlstate in {"55P03", "40P01", "40001"}:
                    exc = DraftError("RUN_BUSY")
                elif sqlstate == "57014" or not self.commit_issued:
                    exc = DraftError("RUN_DB_UNAVAILABLE")
                else:
                    exc = DraftError("RUN_COMMIT_UNCERTAIN")
            if not self.response.done():
                self.response.set_result((None, exc))
        finally:
            await self.retire()
            if self.settled():
                self.owner.operations.discard(self)


class Manager:
    def __init__(self):
        self.operations = set()
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="s02-source")
        self.drain_result = None

    async def perform(self, deadline, work, disconnected=None):
        if self.closed:
            raise DraftError("RUN_DB_UNAVAILABLE")
        if len(self.operations) >= 4:
            raise DraftError("RUN_BUSY")
        operation = Operation(self, deadline)
        self.operations.add(operation)
        operation.coordinator = asyncio.create_task(operation.run(work))
        watch = asyncio.create_task(disconnected()) if disconnected else None
        try:
            waiters = {operation.response}
            if watch:
                waiters.add(watch)
            done, _ = await asyncio.wait(
                waiters,
                timeout=max(0, deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if watch in done or operation.response not in done:
                operation.revoke()
                raise operation.error()
            value, error = operation.response.result()
            if error is not None:
                raise error
            operation.checkpoint()
            return value
        except BaseException:
            operation.revoke()
            raise
        finally:
            if watch is not None:
                watch.cancel()
                with suppress(asyncio.CancelledError):
                    await watch

    async def shutdown(self):
        if self.drain_result is not None:
            if self.drain_result["outcome"] != "CLEAN":
                raise RuntimeError("S02_DRAIN_INCOMPLETE")
            return
        self.closed = True
        for operation in self.operations:
            operation.revoke()
        tasks = {op.coordinator for op in self.operations}
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)
        owners = list(self.operations)
        self.drain_result = {
            "schema_version": 1,
            "kind": "s02_api_drain",
            "outcome": "INCOMPLETE" if owners else "CLEAN",
            "retained_operations": len(owners),
            "source_pending": sum(
                op.source_future is not None and not op.source_future.done() for op in owners
            ),
            "db_pending": sum(
                op.cleanup_pending
                or any(
                    task is not None and not task.done()
                    for task in (op.connect_task, op.driver_task)
                )
                for op in owners
            ),
            "disposal_unconfirmed": sum(
                op.coordinator.done() and not op.settled() for op in owners
            ),
        }
        self.executor.shutdown(wait=False, cancel_futures=True)
        # Open a private descriptor with O_NONBLOCK: never change stderr's shared flags.
        try:
            fd = os.open("/proc/self/fd/2", os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, canonical(self.drain_result) + b"\n")
            finally:
                os.close(fd)
        except OSError:
            pass
        if owners:
            raise RuntimeError("S02_DRAIN_INCOMPLETE")


def manager():
    global _ROOT
    if _ROOT is None:
        _ROOT = Manager()
    return _ROOT


@asynccontextmanager
async def lifespan(app):
    yield
    if _ROOT is not None:
        await _ROOT.shutdown()
