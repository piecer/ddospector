"""Residual I0 boundaries: natural kernel faults vs synthetic close/read faults."""

import importlib.util
import json
import os
import signal
import socket
import sys
from pathlib import Path

import psycopg
import pytest
from supervised_probe import launch
from test_harness import ModelDocker

from tools import s02_harness as h


def receipt(path, name, data):
    (path / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")


def test_natural_child_mapping_acquisition_revokes_all_routes(tmp_path, monkeypatch):
    """Migrated G03: old mmap seam eliminated; retained identity open errno24."""
    spec = importlib.util.spec_from_file_location(
        "boundary_fixture", Path(__file__).with_name("conftest.py")
    )
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    entries = []
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: entries.append("driver"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a: entries.append("socket"))
    guards = fixture_module.no_unowned_execution.__wrapped__(monkeypatch)
    fixture = fixture_module.owned_pg.__wrapped__(tmp_path, guards)
    owner = next(fixture)
    try:
        params = h.connection_parameters(owner.socket)

        def module():
            psycopg.connect(**params)

        def cls():
            psycopg.Connection.connect(**params)

        def unix():
            with socket.socket(socket.AF_UNIX) as wire:
                wire.connect(str(owner.socket / ".s.PGSQL.5432"))

        routes = {"module": module, "class": cls, "socket": unix}
        for invoke in routes.values():
            invoke()
        assert entries == ["driver", "driver", "socket"]
        with (
            monkeypatch.context() as patch,
            launch(
                patch,
                owner,
                {"fault": "emfile", "synthetic": False, "class": "native-EMFILE"},
                tmp_path,
            ) as (results, children),
            pytest.raises(h.Blocked, match="PG_PROBE_FAILED"),
        ):
            owner.probe("write")
        kernel = json.loads((tmp_path / "child-origin.json").read_text())
        assert kernel["fired"] == ["retained-identity-open"] and kernel["errno"] == 24
        assert kernel["synthetic_exception"] is False
        assert results[0].code == 78 and not results[0].stdout
        assert "identity_of" in results[0].stderr
        for invoke in routes.values():
            with pytest.raises(AssertionError):
                invoke()
        assert entries == ["driver", "driver", "socket"]
        with pytest.raises(h.Blocked):
            owner.probe("write")
        raw = h.run_child(
            [sys.executable, h.__file__, "--pg-child", str(owner.directory), "--action", "write"],
            owner.socket.parent,
            10,
            lambda _: None,
        )
        assert raw.code == 78 and not raw.stdout
        assert children[0].returncode == 78
        assert all(s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr))
        receipt(
            tmp_path,
            "natural-authority",
            {
                "kernel": kernel,
                "owner_denied": owner.work_failed,
                "routes": entries,
                "failure_stderr": results[0].stderr,
                "retry_exit": raw.code,
                "before_rescue_reaped": children[0].returncode,
            },
        )
    finally:
        with pytest.raises(StopIteration):
            next(fixture)
    assert owner.state == "CLEAN"


def test_mapping_close_failure_revokes_next_borrower(tmp_path, monkeypatch):
    """Migrated G04: real child outer stream release, not obsolete mmap."""
    with h.Harness(tmp_path, backend=ModelDocker()) as owner:
        with (
            monkeypatch.context() as patch,
            launch(patch, owner, {"fault": "outer-close"}, tmp_path) as (results, children),
            pytest.raises(h.Blocked, match="PG_PROBE_FAILED"),
        ):
            owner.probe("read")
        origin = json.loads((tmp_path / "child-origin.json").read_text())
        assert origin["fired"].count("outer-close-after-release") == 1
        assert origin["outer_closed"] is True
        assert results[0].code == 78 and not results[0].stdout
        assert '"blocked": "OSError"' in results[0].stderr
        assert children[0].returncode == 78
        with pytest.raises(h.Blocked):
            owner.probe("write")
        with pytest.raises(h.Blocked):
            h.borrowed_socket(owner.directory)
        receipt(
            tmp_path,
            "outer-finalizer",
            {
                "origin": origin,
                "real_result": vars(results[0]),
                "revoked": owner.work_failed,
                "pipes_closed_before_rescue": [
                    s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr)
                ],
            },
        )
    assert owner.state == "CLEAN"


def test_ambiguous_pipe_close_attempt_is_not_repeated(tmp_path, monkeypatch):
    native_popen = h.subprocess.Popen
    primary = OSError("PIPE_CLOSE_RELEASED_STATUS_UNCONFIRMED")
    children, replacements, fired = [], [], []

    class Stream:
        def __init__(self, stream):
            self.stream = stream
            self.calls = 0

        @property
        def closed(self):
            # The injected finalizer cannot confirm disposal to the caller.
            return False

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.calls += 1
            if self.calls == 1:
                descriptor = self.stream.fileno()
                self.stream.close()
                replacement = os.open(tmp_path / "replacement", os.O_CREAT | os.O_RDWR, 0o600)
                if replacement != descriptor:
                    os.dup2(replacement, descriptor)
                    os.close(replacement)
                    replacement = descriptor
                replacements.append(replacement)
            fired.append("ambiguous-close")
            raise primary

    def spawn(*args, **kwargs):
        child = native_popen(*args, **kwargs)
        stream = Stream(child.stdout)
        child.stdout = stream
        children.append((child, stream))
        return child

    monkeypatch.setattr(h.subprocess, "Popen", spawn)
    notices = []
    with pytest.raises(OSError) as caught:
        h.run_child([sys.executable, "-c", "pass"], tmp_path, 2, notices.append)
    child, stream = children[0]
    try:
        assert len(replacements) == 1
        os.fstat(replacements[0])
        data = {
            "fired": fired,
            "notices": notices,
            "close_attempts": stream.calls,
            "primary_identity": caught.value is primary,
            "real_pipe_closed": stream.stream.closed,
            "replacement_open_before_rescue": True,
            "wait_status": child.returncode,
            "pid_absent": not Path(f"/proc/{child.pid}").exists(),
            "stderr_closed": child.stderr.closed,
            "synthetic_ambiguous_status": True,
        }
        receipt(tmp_path, "ambiguous-before-rescue", data)
        assert caught.value is primary
        assert stream.calls == 1
        assert data["wait_status"] == 0 and data["pid_absent"] and data["stderr_closed"]
    finally:
        for descriptor in replacements:
            os.close(descriptor)


@pytest.mark.parametrize("wait_failure", [False, True])
def test_pipe_read_failure_retires_exact_child_before_rescue(tmp_path, monkeypatch, wait_failure):
    primary = OSError("PRIMARY_OBSERVER")
    secondary = OSError("SYNTHETIC_CAPTURED_PIPE_READ")
    native_popen, native_read, native_kill = h.subprocess.Popen, os.read, os.killpg
    children, notices, fired, waits = [], [], [], []

    def spawn(*args, **kwargs):
        child = native_popen(*args, **kwargs)
        children.append(child)
        waits.append(child.wait)
        if wait_failure:
            def failed_wait(*args, **kwargs):
                fired.append("wait-refused")
                raise OSError("SYNTHETIC_WAIT_REFUSAL")
            child.wait = failed_wait
        return child

    def read(fd, *args):
        if (
            children
            and fd in (children[0].stdout.fileno(), children[0].stderr.fileno())
            and "pipe-read" not in fired
        ):
            fired.append("pipe-read")
            raise secondary
        return native_read(fd, *args)

    def kill(pid, sig):
        assert sig == signal.SIGKILL and pid == children[0].pid
        native_kill(pid, sig)
        fired.append("kill")

    def observe(row):
        notices.append(row)
        fired.append("observer")
        raise primary

    with monkeypatch.context() as patch:
        patch.setattr(h.subprocess, "Popen", spawn)
        patch.setattr(h.os, "read", read)
        patch.setattr(h.os, "killpg", kill)
        with pytest.raises(OSError) as caught:
            h.run_child(
                [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 1, observe
            )
    child = children[0]
    proc = Path(f"/proc/{child.pid}/stat")
    before = {
        "fired": fired,
        "notices": notices,
        "synthetic_pipe_read_error": True,
        "primary_identity": caught.value is primary,
        "type": type(caught.value).__name__,
        "message": str(caught.value),
        "wait_status": child.returncode,
        "pid_absent": not proc.exists(),
        "pipes_closed": [child.stdout.closed, child.stderr.closed],
    }
    receipt(tmp_path, "before-rescue", before)
    # Preserve the failure disposition before exact verifier-only cleanup on RED.
    try:
        expected_faults = ["observer", "kill", "pipe-read"]
        assert fired == expected_faults + (["wait-refused"] if wait_failure else [])
        assert caught.value is primary and str(caught.value) == "PRIMARY_OBSERVER"
        if wait_failure:
            # An actual wait refusal is unresolved custody, never a clean drain.
            assert before["wait_status"] is None and not before["pid_absent"]
        else:
            assert before["wait_status"] == -9 and before["pid_absent"]
        assert before["pipes_closed"] == [True, True]
    finally:
        child.wait = waits[0]
        if proc.exists():
            assert proc.read_text().rsplit(")", 1)[1].split()[19] == notices[0]["start_ticks"]
        rescued = child.returncode is None or not all(before["pipes_closed"])
        child.wait(timeout=3)
        for stream in (child.stdout, child.stderr):
            if not stream.closed:
                stream.close()
        receipt(
            tmp_path,
            "after-rescue",
            {
                "rescue_used": rescued,
                "wait_status": child.returncode,
                "pid_absent": not proc.exists(),
                "pipes_closed": [child.stdout.closed, child.stderr.closed],
            },
        )
