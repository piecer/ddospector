"""Separate bounded OFFLINE coordinator; only this task performs SQL."""

import argparse
import asyncio
import fcntl
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from uuid import uuid4

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.startup import startup_setting

from . import offline, schema, transitions
from .config import driver, parameters
from .contracts import identifier
from .worker_connection import ConnectionOwner, Stopping, classify, diagnostic


class ControlRequested(Exception):
    """A control request needs actual work quiescence before publication."""


class PureFailure(Exception):
    def __init__(self, code):
        self.code = code


class Watchdog(Exception):
    """The computation has exhausted its frozen five-second allowance."""


async def run(*, run_id=None):
    stop = asyncio.Event()
    stop_at = None

    def stopping():
        nonlocal stop_at
        if stop_at is None:
            stop_at = time.monotonic()
        stop.set()

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping)
    stop_wait = asyncio.create_task(stop.wait())
    owner = ConnectionOwner(stop_wait)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="s02-offline")
    work = future = None
    owned = None
    work_stop = threading.Event()
    ready = False
    final_grace = None
    lock_fd = None

    def quiescent():
        return work is None or work.done()

    def consume_work():
        if future is not None and future.done():
            with suppress(BaseException):
                future.result()

    async def pause(seconds):
        await asyncio.wait({stop_wait}, timeout=seconds)
        if stop.is_set():
            raise Stopping()

    async def dispose(current, *, primary=None, outcome="EXIT75", deadline=None):
        # This one deadline covers original driver unwind, rollback, close and work.
        end = time.monotonic() + 1 if deadline is None else deadline
        work_stop.set()
        cleanup = asyncio.create_task(current.dispose())
        while time.monotonic() < end:
            if cleanup.done() and quiescent():
                break
            await asyncio.sleep(min(0.01, max(0, end - time.monotonic())))
        clean = cleanup.done() and not cleanup.cancelled() and cleanup.exception() is None
        clean = clean and cleanup.result() is True and quiescent()
        consume_work()
        if primary is not None:
            diagnostic(current, primary, quiescent(), outcome if clean else "EXIT75")
        if not clean:
            os._exit(75)

    async def acquire(current):
        current.phase = "CONNECT"
        await current.acquire(pg, kwargs)
        await schema.settings(current.execute)
        await schema.ready(current.execute)

    async def reconnect():
        nonlocal owner, work, future
        for index, delay in enumerate((0, 1, 2, 4, 8)):
            if delay:
                await pause(delay)
            owner = ConnectionOwner(stop_wait)
            owner.compute = compute
            work = future = None
            try:
                await acquire(owner)
            except Stopping:
                raise
            except Exception as error:
                primary = classify(error, owner)
                transient = primary in {"CONNECTION_FAILURE", "CLIENT_TIMEOUT"}
                retry = transient and index < 4
                await dispose(owner, primary=primary, outcome="RECONNECT" if retry else "EXIT75")
                if not retry:
                    return False
            else:
                await pause(1)
                return True
        return False

    async def compute(function, failure_code=None):
        nonlocal work, future
        owner.checkpoint()
        if time.monotonic() >= work_deadline:
            raise Watchdog()
        work = pool.submit(function)
        future = asyncio.wrap_future(work)
        while not future.done():
            remaining = work_deadline - time.monotonic()
            if remaining <= 0:
                raise Watchdog()
            done, _ = await asyncio.wait(
                {future, stop_wait}, timeout=min(2, remaining), return_when=asyncio.FIRST_COMPLETED
            )
            if stop_wait in done:
                raise Stopping()
            if time.monotonic() >= work_deadline:
                raise Watchdog()
            if not done:
                owner.phase = "HEARTBEAT"
                if await transitions.heartbeat(owner, owned) is False:
                    work_stop.set()
                    raise ControlRequested()
        owner.checkpoint()
        try:
            return future.result()
        except Exception as error:
            if failure_code is None:
                raise
            if isinstance(error, offline.ResultLimitExceeded):
                raise PureFailure("RESULT_LIMIT_EXCEEDED") from None
            code = failure_code if isinstance(error, ValueError) else "OFFLINE_PREPARATION_FAILED"
            raise PureFailure(code) from None

    async def settle_control(*, stale=False):
        nonlocal final_grace
        end = time.monotonic() + 1
        work_stop.set()
        rollback = asyncio.create_task(owner.rollback()) if stale else None
        while time.monotonic() < end:
            if quiescent() and (rollback is None or rollback.done()):
                break
            await asyncio.sleep(0.01)
        if not quiescent() or (rollback is not None and not rollback.done()):
            final_grace = end
            raise Watchdog()
        consume_work()
        if rollback is not None:
            rollback.result()

    owner.compute = compute
    try:
        kwargs = parameters(startup_setting("RUN_DB_SOCKET"))
        # Lock the existing directory inode: no lock-file creation, deletion or adoption.
        lock_fd = os.open(kwargs["host"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        lock_mode = fcntl.LOCK_SH if run_id is None else fcntl.LOCK_EX
        fcntl.flock(lock_fd, lock_mode | fcntl.LOCK_NB)
        pg = driver()
        await acquire(owner)
        ready = True
        print(
            canonical(
                {"status": "ready", "schema_version": 1, "worker_instance": str(uuid4())}
            ).decode(),
            flush=True,
        )
        reconcile_id = None
        while not stop.is_set():
            try:
                if reconcile_id is not None:
                    from .repository import begin, commit, lookup

                    owner.phase = "RECONCILE"
                    await begin(owner, read=True)
                    await lookup(owner, reconcile_id)
                    await commit(owner)
                    reconcile_id = None
                if run_id is None:
                    owner.phase = "RECOVERY"
                    await transitions.recover(owner)
                owner.phase = "CLAIM"
                owned = (
                    await transitions.claim(owner)
                    if run_id is None
                    else await transitions.claim(owner, run_id=run_id)
                )
                if owned is None:
                    if run_id is not None:
                        return 69
                    await pause(1)
                    continue
                owner.affected = owned["run_id"]
                work_stop.clear()
                work_deadline = time.monotonic() + 5
                try:
                    snapshot = await compute(
                        lambda owned=owned: offline.verify_claim(owned, stop=work_stop),
                        "SNAPSHOT_INVALID",
                    )
                    owner.phase = "PROGRESS"
                    if await transitions.publish(owner, owned, 1) is False:
                        if run_id is not None:
                            return 1
                        continue
                    result = await compute(
                        lambda snapshot=snapshot: offline.compile_manifest(
                            snapshot, stop=work_stop
                        ),
                        "OFFLINE_PREPARATION_FAILED",
                    )
                    if len(result) > 8192:
                        raise PureFailure("RESULT_LIMIT_EXCEEDED")
                    owner.phase = "PROGRESS"
                    if await transitions.publish(owner, owned, 2) is False:
                        if run_id is not None:
                            return 1
                        continue
                    owner.phase = "COMPLETE"
                    completed = await transitions.publish(owner, owned, 3, result)
                    if run_id is not None:
                        return 1 if completed is False else 0
                except PureFailure as error:
                    owner.phase = "FAILURE"
                    await transitions.publish(owner, owned, 0, failure=error.code)
                    if run_id is not None:
                        return 1
                except ControlRequested:
                    await settle_control()
                    owner.phase = "CANCEL_ACK"
                    await transitions.publish(owner, owned, 0)
                    if run_id is not None:
                        return 1
            except transitions.StaleClaim:
                owned = None
                await settle_control(stale=True)
                if run_id is not None:
                    return 75
                await pause(1)
            except (Stopping, Watchdog):
                raise
            except Exception as error:
                primary = classify(error, owner)
                if run_id is not None:
                    await dispose(owner, primary=primary)
                    return 75
                if primary == "COMMIT_UNCERTAIN":
                    reconcile_id = owner.affected
                owned = None
                transient = primary in {
                    "LOCK_NOT_AVAILABLE",
                    "DEADLOCK_DETECTED",
                    "SERIALIZATION_FAILURE",
                    "QUERY_CANCELED",
                    "CLIENT_TIMEOUT",
                    "CONNECTION_FAILURE",
                    "COMMIT_UNCERTAIN",
                }
                await dispose(
                    owner, primary=primary, outcome="RECONNECT" if transient else "EXIT75"
                )
                if not transient or not await reconnect():
                    return 75
        return 130 if run_id is not None else 0
    except Stopping:
        return 130 if run_id is not None else 0
    except Watchdog:
        return 75
    except Exception as error:
        primary = "CONFIG_REFUSED" if not ready else classify(error, owner)
        await dispose(owner, primary=primary, outcome="EXIT78" if not ready else "EXIT75")
        return 78 if not ready else 75
    finally:
        end = (
            final_grace
            if final_grace is not None
            else (stop_at + 1 if stop_at is not None else time.monotonic() + 1)
        )
        await dispose(owner, deadline=end)
        pool.shutdown(wait=False, cancel_futures=True)
        stop_wait.cancel()
        await asyncio.gather(stop_wait, return_exceptions=True)
        if lock_fd is not None:
            os.close(lock_fd)


def selected_id(value):
    try:
        return identifier(value)
    except DraftError:
        raise argparse.ArgumentTypeError("expected an unchanged lowercase UUIDv4 Run ID") from None


def main():
    parser = argparse.ArgumentParser(description="Bounded OFFLINE worker")
    parser.add_argument("--run-id", type=selected_id, help="supervise exactly one new queued Run")
    args = parser.parse_args()
    return asyncio.run(run(run_id=args.run_id))


if __name__ == "__main__":
    raise SystemExit(main())
