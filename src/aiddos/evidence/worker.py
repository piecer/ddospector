"""One selected evidence evaluation, no queue, daemon, retry, or executor."""
import argparse
import asyncio
import fcntl
import os
import signal
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import canonical
from aiddos.runs.config import parameters
from aiddos.runs.contracts import identifier
from aiddos.runs.lifetime import Operation
from aiddos.startup import startup_setting

from .repository import evaluate


@contextmanager
def ownership(socket):
    path = Path(socket)
    if path.resolve() != path:
        raise DraftError("RUN_DB_UNAVAILABLE")
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        before = os.fstat(parent)
        if before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o700:
            raise DraftError("RUN_DB_UNAVAILABLE")
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        captured = os.fstat(fd)
        if stat.S_IMODE(captured.st_mode) != 0o777:
            raise DraftError("RUN_DB_UNAVAILABLE")
        # Same inode and flock domain as the existing selected/daemon Run workers.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def check_identity():
            current_parent = path.parent.stat(follow_symlinks=False)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (current_parent.st_dev, current_parent.st_ino, current_parent.st_mode,
                current_parent.st_uid) != (before.st_dev, before.st_ino, before.st_mode,
                                           before.st_uid) or (
                current.st_dev, current.st_ino, current.st_mode, current.st_uid
            ) != (captured.st_dev, captured.st_ino, captured.st_mode, captured.st_uid):
                raise DraftError("RUN_DB_UNAVAILABLE")
        check_identity()
        yield check_identity
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


async def run(evidence_id, socket, check_identity):
    # Reuse the guarded Operation directly. No Manager/new pool/queue is needed:
    # parsing is bounded synchronous work with deadline/signal checkpoints.
    owner = SimpleNamespace(operations=set())
    op = Operation(owner, time.monotonic() + 5)
    owner.operations.add(op)
    original_checkpoint = op.checkpoint

    def checkpoint():
        original_checkpoint()
        check_identity()

    op.checkpoint = checkpoint
    previous = {}

    def stopping(signum, frame):
        op.revoke()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[sig] = signal.signal(sig, stopping)
    task = asyncio.create_task(op.run(lambda operation: evaluate(operation, socket, evidence_id)))
    op.coordinator = task
    try:
        done, _ = await asyncio.wait({task}, timeout=6)
        if not done:
            op.revoke()
            done, _ = await asyncio.wait({task}, timeout=1)
        # Never release the flock while driver/retirement work can still run.
        if not done or not op.settled():
            os._exit(75)
        task.result()
        value, error = op.response.result()
        if error is not None:
            raise error
        checkpoint()
        return value
    finally:
        # Caller cancellation is revocation, not permission to abandon retirement.
        if not task.done():
            op.revoke()
            end = time.monotonic() + 1
            while not task.done() and time.monotonic() < end:
                try:
                    await asyncio.wait({task}, timeout=max(0, end - time.monotonic()))
                except asyncio.CancelledError:
                    continue
        if not task.done() or not op.settled():
            os._exit(75)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def selected_id(value):
    try:
        return identifier(value)
    except DraftError:
        raise argparse.ArgumentTypeError(
            "expected an unchanged lowercase UUIDv4 evidence ID") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-id", type=selected_id, required=True)
    args = parser.parse_args()
    admitted = False
    try:
        socket = parameters(startup_setting("RUN_DB_SOCKET"))["host"]
        with ownership(socket) as check_identity:
            admitted = True
            status, report = asyncio.run(run(args.evidence_id, socket, check_identity))
            print(canonical({"schema_version": 1, "status": status, "report": report}).decode(),
                  flush=True)
        return 0
    except Exception as error:
        code = error.code if isinstance(error, DraftError) else "EVALUATION_REFUSED"
        print(canonical({"schema_version": 1, "code": code}).decode(), file=sys.stderr)
        return 75 if admitted else 78


if __name__ == "__main__":
    raise SystemExit(main())
