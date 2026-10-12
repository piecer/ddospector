"""Single-owner driver custody and single-attempt exact disposal."""

import asyncio
import os
from contextlib import suppress

from aiddos.api.scenarios import canonical


class Stopping(Exception):
    """Signal revocation; only cleanup remains authorized."""


class ConnectionOwner:
    def __init__(self, stop_wait=None):
        self.connection = None
        self.transaction = None
        self.pending = None
        self.commit_issued = False
        self.closed = False
        self.stop_wait = stop_wait
        self.disposal = None
        self.rollback_status = "NOT_NEEDED"
        self.close_status = "NOT_ACQUIRED"
        self.phase = "CONNECT"
        self.affected = None
        self.compute = None

    def checkpoint(self):
        if self.closed:
            raise RuntimeError("WORKER_RETIRED")
        if self.stop_wait is not None and self.stop_wait.done():
            raise Stopping()

    async def call(self, factory, *, commit=False):
        self.checkpoint()
        self.commit_issued = commit
        self.pending = asyncio.create_task(factory())
        waiting = {self.pending}
        if self.stop_wait is not None:
            waiting.add(self.stop_wait)
        done, _ = await asyncio.wait(waiting, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        if self.stop_wait in done:
            raise Stopping()
        if self.pending not in done:
            raise TimeoutError()
        value = self.pending.result()
        self.pending = None
        self.commit_issued = False
        return value

    async def acquire(self, pg, kwargs):
        async def connect():
            # Install custody inside the acquisition task, including late returns.
            self.connection = await pg.AsyncConnection.connect(**kwargs, autocommit=True)

        await self.call(connect)

    async def execute(self, sql, args=None):
        async def query():
            async with self.connection.cursor() as cursor:
                await cursor.execute(sql, args)
                return await cursor.fetchall() if cursor.description else []

        return await self.call(query)

    async def rollback(self):
        if self.transaction is not None:
            transaction, self.transaction = self.transaction, None
            self.rollback_status = "PENDING"
            try:
                await transaction.__aexit__(RuntimeError, RuntimeError("ABANDONED"), None)
            except BaseException:
                self.rollback_status = "FAILED"
                raise
            else:
                self.rollback_status = "OK"

    async def _dispose(self):
        self.closed = True
        if self.pending is not None:
            if not self.pending.done():
                self.pending.cancel()
            with suppress(BaseException):
                await self.pending
        with suppress(BaseException):
            await self.rollback()
        if self.connection is None:
            return True
        self.close_status = "PENDING"
        failed = False
        try:
            await self.connection.close()
        except BaseException:
            failed = True
        proved = self.connection.closed is True
        self.close_status = (
            ("FAILED_CLOSED" if proved else "FAILED_UNCONFIRMED")
            if failed
            else ("CLOSED" if proved else "FAILED_UNCONFIRMED")
        )
        return proved

    async def dispose(self):
        if self.disposal is None:
            self.disposal = asyncio.create_task(self._dispose())
        return await asyncio.shield(self.disposal)


def classify(error, owner):
    sqlstate = getattr(error, "sqlstate", None)
    known = {
        "55P03": "LOCK_NOT_AVAILABLE",
        "40P01": "DEADLOCK_DETECTED",
        "40001": "SERIALIZATION_FAILURE",
        "57014": "QUERY_CANCELED",
    }
    if sqlstate in known:
        return known[sqlstate]
    if owner.commit_issued and sqlstate is None:
        return "COMMIT_UNCERTAIN"
    if isinstance(error, TimeoutError):
        return "CLIENT_TIMEOUT"
    if getattr(error, "code", None) == "RUN_STATE_CORRUPT":
        return "REPOSITORY_CORRUPT"
    if getattr(error, "code", None) in {
        "RUN_DB_NOT_READY",
        "RUN_DB_NOT_CONFIGURED",
        "RUN_DB_UNAVAILABLE",
    } or sqlstate in {"42P01", "42703"}:
        return "CONFIG_REFUSED"
    if type(error).__module__.startswith("psycopg") and (
        sqlstate is None or sqlstate.startswith("08") or sqlstate == "57P01"
    ):
        return "CONNECTION_FAILURE"
    return "REPOSITORY_UNEXPECTED"


def diagnostic(owner, primary, work, outcome):
    value = {
        "schema_version": 1,
        "kind": "worker_repository_failure",
        "phase": owner.phase,
        "primary": primary,
        "rollback": owner.rollback_status,
        "close": owner.close_status,
        "work": "QUIESCENT" if work else "PENDING",
        "outcome": outcome,
    }
    raw = canonical(value) + b"\n"
    assert len(raw) <= 512
    try:
        blocking = os.get_blocking(2)
        try:
            os.set_blocking(2, False)
            os.write(2, raw)
        finally:
            os.set_blocking(2, blocking)
    except OSError:
        pass
