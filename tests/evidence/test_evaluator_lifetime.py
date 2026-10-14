"""Evaluator admission and actual existing-operation retirement, no database mocks."""
import asyncio
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from aiddos.api.errors import DraftError
from aiddos.evidence import worker


def test_socket_inode_lock_shared_with_runs_and_no_adoption(tmp_path):
    tmp_path.chmod(0o700)
    socket = tmp_path / "s"
    socket.mkdir()
    socket.chmod(0o777)
    fd = os.open(socket, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError), worker.ownership(str(socket)):
            pytest.fail("admission while Run worker lock held")
    finally:
        os.close(fd)
    with worker.ownership(str(socket)) as check:
        check()
        socket.rename(tmp_path / "original")
        socket.mkdir()
        socket.chmod(0o777)
        with pytest.raises(DraftError):
            check()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["original", "s"]


@pytest.mark.parametrize("fault", ["symlink", "parent-mode", "socket-mode"])
def test_invalid_socket_identity_refused(tmp_path, fault):
    tmp_path.chmod(0o700)
    socket = tmp_path / "s"
    socket.mkdir()
    socket.chmod(0o777)
    if fault == "symlink":
        socket.rename(tmp_path / "target")
        socket.symlink_to(tmp_path / "target", target_is_directory=True)
    elif fault == "parent-mode":
        tmp_path.chmod(0o755)
    else:
        socket.chmod(0o700)
    with pytest.raises(DraftError), worker.ownership(str(socket)):
        pytest.fail("identity admitted")


@pytest.mark.parametrize("finish", ["normal", "exception", "revoked", "deadline", "signal"])
def test_operation_retires_before_return_and_restores_handlers(monkeypatch, finish):
    operations = []
    failure = OSError("unconverted I/O")
    previous = {sig: signal.getsignal(sig)
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    async def work(op, socket, evidence_id):
        operations.append(op)
        assert op.deadline > worker.time.monotonic()
        if finish == "exception":
            raise failure
        if finish == "revoked":
            op.revoke()
        elif finish == "deadline":
            op.deadline = worker.time.monotonic() - 1
        elif finish == "signal":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        op.checkpoint()
        return "ANALYZED", {"test": "no database access"}
    monkeypatch.setattr(worker, "evaluate", work)
    if finish == "normal":
        assert asyncio.run(worker.run("id", "unused", lambda: None))[0] == "ANALYZED"
    else:
        with pytest.raises(OSError if finish == "exception" else DraftError) as caught:
            asyncio.run(worker.run("id", "unused", lambda: None))
        if finish == "exception":
            assert caught.value is failure
    assert len(operations) == 1
    op = operations[0]
    assert op.coordinator.done() and op.settled() and not op.owner.operations
    assert all(signal.getsignal(sig) == handler for sig, handler in previous.items())


def test_caller_cancellation_waits_for_actual_retirement(monkeypatch):
    async def case():
        entered, release = asyncio.Event(), asyncio.Event()
        seen = []
        async def work(op, socket, evidence_id):
            seen.append(op)
            entered.set()
            await release.wait()
            op.checkpoint()
            pytest.fail("cancelled work reached publication")
        monkeypatch.setattr(worker, "evaluate", work)
        task = asyncio.create_task(worker.run("id", "unused", lambda: None))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        try:
            assert not task.done(), "caller cancellation released live operation"
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert seen[0].coordinator.done() and seen[0].settled()
        assert not seen[0].owner.operations
    asyncio.run(case())


def test_id_validation_precedes_any_admission(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "parameters", lambda value: calls.append(value))
    monkeypatch.setattr(worker.sys, "argv", ["evaluate", "--evidence-id", "BAD"])
    with pytest.raises(SystemExit) as caught:
        worker.main()
    assert caught.value.code == 2 and calls == []


@pytest.mark.parametrize("mode", ["normal", "cancel-normal", "close-failure",
                                 "cancel-close-failure"])
def test_isolated_close_retirement_owns_lock_until_retired_or_process_exit(
    tmp_path, mode, record_property,
):
    helper = Path(__file__).with_name("evaluator_retirement_child.py")
    root = Path(__file__).resolve().parents[2]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "PYTHONPATH": str(root / "src")}
    child = subprocess.run([sys.executable, str(helper), mode, str(tmp_path)],
                           cwd=root, env=env, capture_output=True, timeout=15)
    (tmp_path / "child-exit.json").write_text(json.dumps({
        "mode": mode, "exit": child.returncode, "stdout": child.stdout.decode(),
        "stderr": child.stderr.decode(),
    }, indent=2) + "\n")
    fault = json.loads((tmp_path / "coordinator-done.json").read_text())
    record_property("retirement_receipts", str(tmp_path))
    record_property("actual_child_exit", child.returncode)
    assert fault["coordinator_done"] and fault["lock_held"]
    assert fault["cancel_requested"] == mode.startswith("cancel-")
    assert not Path(f"/proc/{fault['pid']}").exists()
    for origin in fault["origins"].values():
        source = Path(origin["path"])
        assert source.is_relative_to(root)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == origin["sha256"]
    # OS process retirement releases the real directory flock, not a flag.
    with worker.ownership(str(tmp_path / "s")) as identity:
        identity()
    returned = tmp_path / "returned.json"
    if mode.endswith("close-failure"):
        assert fault["events"] == ["close-entered", "close-raised"]
        assert not fault["settled"] and fault["owner_operations"] == 1
        assert fault["disposal"] == ["CLOSE_ERROR"] and fault["fd_open"]
        assert child.returncode == 75, "unsettled disposal returned instead of process exit"
        assert not returned.exists(), "ownership released before actual retirement"
    else:
        assert child.returncode == 0, child.stderr.decode()
        assert fault["events"] == ["close-entered", "close-completed"]
        assert fault["settled"] and fault["owner_operations"] == 0
        assert fault["disposal"] == [] and not fault["fd_open"]
        result = json.loads(returned.read_text())
        assert result["settled"] and result["owner_operations"] == 0
        assert not result["fd_open"] and not result["lock_held"]
        assert result["signals_restored_inside"] and result["signals_restored_outside"]
        if mode == "cancel-normal":
            assert result["state"] == "CANCELLED_RETURNED"
            assert result["cancel_args"] == ["retirement-test"]
        else:
            assert result["state"] == "RETURNED"
            assert result["result"] == ["ANALYZED", {"isolated": True}]
