"""Isolated real Operation/FD/flock; only close adapter and caller schedule injected."""
import asyncio
import errno
import fcntl
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

from aiddos.evidence import worker
from aiddos.runs import lifetime


def main(mode, directory):
    assert mode in {"normal", "cancel-normal", "close-failure", "cancel-close-failure"}
    directory.chmod(0o700)
    socket = directory / "s"
    socket.mkdir()
    socket.chmod(0o777)
    read_fd, write_fd = os.pipe()
    seen, events = [], []
    outer = None
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    outside = {sig: signal.getsignal(sig) for sig in signals}

    def lock_held():
        fd = os.open(socket, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(fd)

    def fd_open():
        try:
            os.fstat(read_fd)
            return True
        except OSError as error:
            assert error.errno == errno.EBADF
            return False

    def snapshot():
        op = seen[0]
        return {"pid": os.getpid(), "mode": mode, "events": list(events),
                "coordinator_done": op.coordinator.done(), "settled": op.settled(),
                "owner_operations": len(op.owner.operations), "disposal": list(op.disposal),
                "fd_open": fd_open(), "lock_held": lock_held(),
                "origins": {mod.__name__: {"path": mod.__file__,
                    "sha256": hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()}
                    for mod in (worker, lifetime)}}

    def after_coordinator():
        # Scheduled by the real close adapter, after Operation.run has retired.
        receipt = snapshot()
        receipt["cancel_requested"] = mode.startswith("cancel-")
        (directory / "coordinator-done.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if receipt["cancel_requested"]:
            outer.cancel("retirement-test")

    class CloseAdapter:
        closed = False

        async def close(self):
            events.append("close-entered")
            asyncio.get_running_loop().call_soon(after_coordinator)
            if mode.endswith("close-failure"):
                events.append("close-raised")
                raise OSError("injected close adapter failure, not a PostgreSQL outage")
            os.close(read_fd)
            os.close(write_fd)
            self.closed = True
            events.append("close-completed")

    connection = CloseAdapter()

    async def connect():
        return connection

    async def work(op, sock, evidence_id):
        seen.append(op)
        await op.call(connect, connect=True)
        return "ANALYZED", {"isolated": True}

    worker.evaluate = work

    async def scenario():
        nonlocal outer
        outer = asyncio.current_task()
        inside = {sig: signal.getsignal(sig) for sig in signals}
        with worker.ownership(str(socket)) as identity:
            try:
                result = await worker.run("isolated", str(socket), identity)
                state, cancel_args = "RETURNED", []
            except asyncio.CancelledError as error:
                result, state, cancel_args = None, "CANCELLED_RETURNED", list(error.args)
        receipt = snapshot()
        receipt.update(state=state, result=result, cancel_args=cancel_args,
                       signals_restored_inside=all(signal.getsignal(s) == h
                                                   for s, h in inside.items()))
        # RED candidate may return with actual FDs open; observe before test cleanup.
        if not connection.closed:
            os.close(read_fd)
            os.close(write_fd)
        return receipt

    receipt = asyncio.run(scenario())
    receipt["signals_restored_outside"] = all(signal.getsignal(s) == h
                                             for s, h in outside.items())
    (directory / "returned.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
