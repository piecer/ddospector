"""Correction regressions: real retirement is distinct from model custody."""

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest
from test_harness import ModelDocker

from tools import s02_harness as h


def supervised_result(owner, action, *, failure=False, timeout=10):
    """Migration adapter retaining the REAL supervisor Result and observations."""
    original = h.run_child
    results, notices = [], []

    def run(argv, directory, limit, observe, **kwargs):
        def observed(event):
            if kwargs.get("_grant") is not None:
                notices.append(event)
            observe(event)

        result = original(argv, directory, limit, observed, **kwargs)
        if kwargs.get("_grant") is not None:
            results.append(result)
        return result

    h.run_child = run
    try:
        if failure:
            with pytest.raises(h.Blocked, match="PG_PROBE_FAILED"):
                owner.probe(action, timeout=timeout)
        else:
            owner.probe(action, timeout=timeout)
    finally:
        h.run_child = original
    assert len(results) == 1
    return results[0], notices


def record(path, name, data):
    (path / (name + ".json")).write_text(json.dumps(data, indent=2) + "\n")


def test_directory_primary_survives_single_close_after_fd_reuse(tmp_path, monkeypatch):
    owner = h.Harness(tmp_path, backend=object())
    primary = OSError("PRIMARY_DIRECTORY_FSYNC")
    secondary = OSError("SECONDARY_CLOSE_AFTER_RELEASE")
    fsync, close = os.fsync, os.close
    fired, reused = [], []

    def fail_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            fired.append("directory-fsync")
            raise primary
        return fsync(fd)

    def close_then_raise(fd):
        assert stat.S_ISDIR(os.fstat(fd).st_mode)
        close(fd)
        replacement = os.open(tmp_path / "replacement", os.O_CREAT | os.O_RDWR, 0o600)
        assert replacement == fd
        reused.append(replacement)
        fired.append("directory-close-released-reused")
        raise secondary

    with monkeypatch.context() as patch:
        patch.setattr(h.os, "fsync", fail_fsync)
        patch.setattr(h.os, "close", close_then_raise)
        with pytest.raises(OSError) as caught:
            owner.note("probe")
    try:
        assert len(reused) == 1
        os.fstat(reused[0])  # Still owned by the verifier, never blindly reclosed.
        record(
            tmp_path,
            "directory-primary",
            {
                "fired": fired,
                "primary_identity": caught.value is primary,
                "caught_type": type(caught.value).__name__,
                "message": str(caught.value),
                "original_fd_retired": True,
                "replacement_open_before_rescue": True,
            },
        )
        assert fired == ["directory-fsync", "directory-close-released-reused"]
        assert caught.value is primary
        assert str(caught.value) == "PRIMARY_DIRECTORY_FSYNC"
        assert caught.value.__notes__
    finally:
        close(reused[0])


@pytest.mark.parametrize("phase", ["write", "flush", "fsync", "close-only"])
def test_journal_stream_primary_and_single_close(tmp_path, monkeypatch, phase):
    owner = h.Harness(tmp_path, backend=object())
    primary, secondary = OSError("PRIMARY_" + phase), OSError("SECONDARY_STREAM_CLOSE")
    original_open, original_fsync = Path.open, os.fsync
    fired, streams = [], []

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def write(self, value):
            if phase == "write":
                fired.append("write")
                raise primary
            return self.stream.write(value)

        def flush(self):
            if phase == "flush":
                fired.append("flush")
                raise primary
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

        def close(self):
            fired.append("close-after-release")
            self.stream.close()
            raise primary if phase == "close-only" else secondary

    def open_stream(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == owner.journal:
            streams.append(stream)
            return Stream(stream)
        return stream

    def fsync(fd):
        if phase == "fsync" and stat.S_ISREG(os.fstat(fd).st_mode):
            fired.append("fsync")
            raise primary
        return original_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_stream)
        patch.setattr(h.os, "fsync", fsync)
        with pytest.raises(OSError) as caught:
            owner.note("stream-test")
    assert len(streams) == 1 and streams[0].closed
    assert fired == ([phase] if phase != "close-only" else []) + ["close-after-release"]
    record(
        tmp_path,
        "stream",
        {
            "phase": phase,
            "fired": fired,
            "primary_identity": caught.value is primary,
            "stream_closed_before_rescue": True,
        },
    )
    assert caught.value is primary
    assert str(caught.value) == "PRIMARY_" + phase


def test_directory_close_only_failure_is_not_success(tmp_path, monkeypatch):
    owner = h.Harness(tmp_path, backend=object())
    original = os.close
    primary, descriptors = OSError("CLOSE_ONLY"), []

    def close(fd):
        original(fd)
        descriptors.append(fd)
        raise primary

    with monkeypatch.context() as patch:
        patch.setattr(h.os, "close", close)
        with pytest.raises(OSError) as caught:
            owner.note("close-only")
    assert caught.value is primary and len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    record(tmp_path, "directory-close-only", {"fired": True, "fd_retired": True})


@pytest.mark.parametrize("phase", ["observer", "communicate"])
@pytest.mark.parametrize("secondary_phase", ["reap-report", "kill-report"])
def test_process_primary_survives_retirement(tmp_path, monkeypatch, phase, secondary_phase):
    primary, secondary = OSError("PRIMARY_" + phase), OSError("SECONDARY_" + secondary_phase)
    popen, killpg = h.subprocess.Popen, os.killpg
    children, fired, notices = [], [], []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        communicate = child.communicate

        def communicate_fault(*args, **kwargs):
            if phase == "communicate" and "primary" not in fired:
                fired.append("primary")
                raise primary
            result = communicate(*args, **kwargs)
            if secondary_phase == "reap-report":
                fired.append("reap-report")
                raise secondary
            return result

        child.communicate = communicate_fault
        return child

    def observe(event):
        notices.append(event)
        if phase == "observer":
            fired.append("primary")
            raise primary

    def kill(pid, sig):
        killpg(pid, sig)
        if secondary_phase == "kill-report":
            fired.append("kill-report")
            raise secondary

    with monkeypatch.context() as patch:
        patch.setattr(h.subprocess, "Popen", spawn)
        patch.setattr(h.os, "killpg", kill)
        with pytest.raises(OSError) as caught:
            h.run_child([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 1, observe)
    child = children[0]
    # poll reaps only if needed: distinguish that verifier rescue from mechanism retirement.
    mechanism_reaped = child.returncode is not None
    pipes_closed = child.stdout.closed and child.stderr.closed
    absent_before_rescue = not Path(f"/proc/{child.pid}").exists()
    record(
        tmp_path,
        "process-primary",
        {
            "fired": fired,
            "notices": notices,
            "pid": child.pid,
            "primary_identity": caught.value is primary,
            "message": str(caught.value),
            "mechanism_reaped": mechanism_reaped,
            "pipes_closed": pipes_closed,
            "pid_absent_before_rescue": absent_before_rescue,
        },
    )
    try:
        assert fired == ["primary", secondary_phase]
        assert mechanism_reaped and absent_before_rescue and pipes_closed
        assert caught.value is primary
        assert str(caught.value) == "PRIMARY_" + phase
        assert caught.value.__notes__
    finally:
        if not mechanism_reaped:
            child.communicate = type(child).communicate.__get__(child)
            child.communicate(timeout=3)


def test_process_cleanup_only_report_still_fails(tmp_path, monkeypatch):
    popen = h.subprocess.Popen
    primary, children, fired = OSError("REAP_ONLY"), [], []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        communicate = child.communicate

        def report(*args, **kwargs):
            result = communicate(*args, **kwargs)
            if child.returncode is not None:
                fired.append("reaped")
                raise primary
            return result

        child.communicate = report
        return child

    monkeypatch.setattr(h.subprocess, "Popen", spawn)
    notices = []
    with pytest.raises(OSError) as caught:
        h.run_child([sys.executable, "-c", "pass"], tmp_path, 2, notices.append)
    child = children[0]
    assert caught.value is primary and fired == ["reaped"]
    assert child.returncode == 0 and not Path(f"/proc/{child.pid}").exists()
    assert child.stdout.closed and child.stderr.closed
    record(
        tmp_path,
        "process-cleanup-only",
        {
            "fired": fired,
            "notices": notices,
            "reaped": True,
            "pid_absent": True,
            "primary_identity": True,
        },
    )


@pytest.mark.parametrize("route", ["module", "class", "socket"])
@pytest.mark.parametrize("transition", ["close", "failure", "custody", "child_failure"])
def test_fixture_checks_live_owner_before_io(tmp_path, monkeypatch, route, transition):
    spec = importlib.util.spec_from_file_location(
        "recovery_fixture", Path(__file__).with_name("conftest.py")
    )
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    entries = []

    def driver(*args, **kwargs):
        entries.append("driver")
        return None  # Boundary spy only: no libpq/foreign socket I/O.

    def socket_boundary(*args):
        entries.append("socket")
        return None

    model = ModelDocker()
    original = h.Harness

    class ModeledOwner(original):
        def __init__(self, path):
            super().__init__(path, backend=model)

        def bootstrap(self):
            self.revalidate()
            self.ready = True

    with monkeypatch.context() as patch:
        if transition == "custody":
            patch.setattr(h, "Harness", ModeledOwner)
        patch.setattr(psycopg, "connect", driver)
        patch.setattr(socket.socket, "connect", socket_boundary)
        guards = fixture_module.no_unowned_execution.__wrapped__(patch)
        fixture = fixture_module.owned_pg.__wrapped__(tmp_path, guards)
        owner = next(fixture)
        params = h.connection_parameters(owner.socket)

        def invoke():
            if route == "socket":
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.connect(str(owner.socket / ".s.PGSQL.5432"))
            elif route == "module":
                psycopg.connect(**params)
            else:
                psycopg.Connection.connect(**params)

        try:
            invoke()
            assert entries == ["socket" if route == "socket" else "driver"]
            if transition == "close":
                owner.close()
                assert owner.state == "CLEAN"
            elif transition == "failure":
                with pytest.raises(h.Blocked, match="PROBE_ACTION_REFUSED"):
                    owner.probe("invalid")
                assert owner.work_failed
            elif transition == "child_failure":
                notices = []
                failed, notices = supervised_result(owner, "read", failure=True)
                assert failed.code == 78 and not failed.timed_out
                assert '"blocked": "UndefinedTable"' in failed.stderr
                record(
                    tmp_path,
                    "child-failure",
                    {"code": failed.code, "stderr": failed.stderr, "notices": notices},
                )
            else:
                model.metadata["Name"] = "/model-custody-lost"
                with pytest.raises(h.Blocked, match="IDENTITY_MISMATCH"):
                    owner.revalidate()
                model.metadata["Name"] = "/" + owner.name
                assert owner.state == "BLOCKED"
            outcome = "ADMITTED"
            try:
                invoke()
            except AssertionError:
                outcome = "REFUSED_BEFORE_IO"
            record(
                tmp_path,
                "fixture-liveness",
                {
                    "route": route,
                    "transition": transition,
                    "entries": entries,
                    "outcome": outcome,
                    "state": owner.state,
                    "journal": str(owner.journal),
                    "world": "model" if transition == "custody" else "real-owned-pg",
                    "spy_no_io": True,
                    "transition_fired": True,
                },
            )
            assert outcome == "REFUSED_BEFORE_IO"
            assert len(entries) == 1
        finally:
            if transition == "custody":
                with pytest.raises(h.Blocked, match="CLEANUP_CUSTODY_UNCONFIRMED"):
                    next(fixture)
                assert model.container_present and model.volume_present
            else:
                with pytest.raises(StopIteration):
                    next(fixture)
                assert owner.state == "CLEAN"


@pytest.mark.parametrize("failed", [False, True])
def test_shipped_pg_child_respects_failed_owner(tmp_path, failed):
    with h.Harness(tmp_path) as owner:
        owner.bootstrap()
        if failed:
            # Explicit G01 migration: 0.001 expiry during prep must not fabricate a child.
            with pytest.raises(h.Blocked, match="PG_PROBE_FAILED"):
                owner.probe("read", timeout=0.001)
            assert owner.work_failed
            owner.revalidate()
            with pytest.raises(h.Blocked, match="WORK_REVOKED"):
                owner.probe("write")
            raw = h.run_child(
                [
                    sys.executable,
                    h.__file__,
                    "--pg-child",
                    str(owner.directory),
                    "--action",
                    "write",
                ],
                owner.socket.parent,
                10,
                lambda _: None,
            )
            assert raw.code == 78 and not raw.stdout
            record(tmp_path, "pg-child", {"failed": True, "raw": vars(raw), "revoked": True})
        else:
            result, notices = supervised_result(owner, "write")
            assert result.code == 0 and not result.timed_out
            proof = json.loads(result.stdout)["proof"]
            assert proof["value"] == "i0-probe-not-application"
            assert proof["af_unix"] and proof["connection_cap_enforced"]
            assert not Path(f"/proc/{notices[0]['pid']}").exists()
            record(
                tmp_path, "pg-child", {"failed": False, "result": vars(result), "notices": notices}
            )
    assert owner.state == "CLEAN"


@pytest.mark.parametrize("failure", ["work", "custody", "journal"])
def test_unpublished_failure_cannot_revive_historical_handoff(tmp_path, monkeypatch, failure):
    model = ModelDocker()
    owner = h.Harness(tmp_path, backend=model).create()
    original_note = owner.note
    fired = []
    primary = OSError("PRIMARY_JOURNAL_FAILURE")

    def note(event, **data):
        if event in {"work_revoked", "blocked"}:
            fired.append(event)
            raise OSError("FAILURE_FENCE_PUBLICATION_FAILED")
        if failure == "journal" and event == "pg_child_exit":
            fired.append(event)
            raise primary
        return original_note(event, **data)

    with monkeypatch.context() as patch:
        # This is a bounded custody model. No synthetic ID reaches real Docker.
        patch.setattr(h, "Docker", lambda *args: model)
        owner.ready = True
        assert owner._admit_connection(5, lambda: owner.socket) == owner.socket
        patch.setattr(owner, "note", note)
        if failure == "work":
            with pytest.raises(h.Blocked, match="PROBE_ACTION_REFUSED"):
                owner.probe("invalid")
        elif failure == "custody":
            model.metadata["Name"] = "/model-lost-custody"
            with pytest.raises(h.Blocked, match="IDENTITY_MISMATCH"):
                owner.revalidate()
            model.metadata["Name"] = "/" + owner.name
        else:
            from supervised_probe import proof
            def modeled_result(*args, **kwargs):
                attempt = kwargs["_grant"][1]
                attempt.exit_known, attempt.closed = 1, 7
                return h.Result(0, h.encode_proof({
                    "grant_sha256": attempt.digest.hex(), "proof": proof(),
                }, "read").decode(), "")
            patch.setattr(h, "run_child", modeled_result)
            with pytest.raises(OSError) as caught:
                owner.probe("read")
            assert caught.value is primary
        assert fired
        events = [json.loads(line) for line in owner.journal.read_text().splitlines()]
        assert not any(e["event"] in {"work_revoked", "blocked"} for e in events)
        outcome = "ADMITTED"
        try:
            h.borrowed_socket(owner.directory)
        except h.Blocked:
            outcome = "REFUSED"
        record(
            tmp_path,
            "unpublished-failure",
            {
                "failure": failure,
                "fired": fired,
                "outcome": outcome,
                "journal": str(owner.journal),
                "model_only": True,
                "failure_event_absent": True,
                "state": owner.state,
            },
        )
    # The original owner's cleanup capability is distinct from new-work authority.
    if failure != "custody":
        owner.close()
        assert owner.state == "CLEAN"
    else:
        with pytest.raises(h.Blocked):
            owner.close()
        assert model.container_present and model.volume_present
    assert outcome == "REFUSED"


def test_direct_failed_pg_child_revokes_next_child_and_owner(tmp_path):
    with h.Harness(tmp_path) as owner:
        owner.bootstrap()
        failed, notices = supervised_result(owner, "read", failure=True)
        assert failed.code == 78 and '"blocked": "UndefinedTable"' in failed.stderr
        assert h.WARNING.decode() in failed.stderr
        with pytest.raises(h.Blocked, match="WORK_REVOKED"):
            owner.probe("write")
        retry = h.run_child(
            [sys.executable, h.__file__, "--pg-child", str(owner.directory), "--action", "write"],
            owner.socket.parent,
            10,
            notices.append,
        )
        record(
            tmp_path,
            "direct-failure",
            {
                "first_exit": failed.code,
                "first_stderr": failed.stderr,
                "retry_exit": retry.code,
                "retry_stderr": retry.stderr,
                "retry_stdout": retry.stdout,
                "notices": notices,
            },
        )
        assert retry.code == 78 and not retry.stdout
        assert json.loads(retry.stderr)["blocked"] == "Blocked"
    assert owner.state == "CLEAN"


def test_real_timeout_primary_survives_reap_report(tmp_path, monkeypatch):
    popen = h.subprocess.Popen
    children, originals, fired, notices = [], [], [], []
    secondary = OSError("SECONDARY_TIMEOUT_REAP")

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        communicate = child.communicate

        def communicate_fault(*args, **kwargs):
            try:
                communicate(*args, **kwargs)
            except subprocess.TimeoutExpired as error:
                originals.append(error)
                fired.append("actual-timeout")
                raise
            fired.append("reap-report")
            raise secondary

        child.communicate = communicate_fault
        return child

    monkeypatch.setattr(h.subprocess, "Popen", spawn)
    caught = None
    try:
        h.run_child(
            [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.01, notices.append
        )
    except BaseException as error:
        caught = error
    child = children[0]
    assert child.returncode == -9 and not Path(f"/proc/{child.pid}").exists()
    assert child.stdout.closed and child.stderr.closed
    assert fired == ["actual-timeout", "reap-report"] and len(originals) == 1
    record(
        tmp_path,
        "timeout-primary",
        {
            "fired": fired,
            "notices": notices,
            "primary_identity": caught is originals[0],
            "reaped": True,
            "pid_absent": True,
        },
    )
    assert caught is originals[0]
    assert type(caught) is subprocess.TimeoutExpired


def test_work_fence_is_bounded_and_retires_owned_descriptors(tmp_path, monkeypatch):
    # Old mmap representation is eliminated; bounded live control has no persistent fence.
    model = ModelDocker()
    owner = h.Harness(tmp_path, backend=model).create()
    owner.ready = True
    assert not (owner.directory / "work.fence").exists()
    for number in range(1, 131):

        def admitted(number=number):
            assert owner.work_state == "PENDING"
            assert owner.attempt.number == number
            assert len(owner.attempt.packed()) == 87
            return owner.socket

        assert owner._admit_connection(5, admitted) == owner.socket
        assert owner.sequence == number and owner.attempt is None
    owner.close()
    assert owner.state == "CLEAN"
    with pytest.raises(h.Blocked):
        h.borrowed_socket(owner.directory)
    record(
        tmp_path,
        "control-retirement",
        {
            "logical_control_bound": 87,
            "no_retained_slot": owner.attempt is None,
            "successes": owner.sequence,
            "cleanup": owner.state,
        },
    )


def test_historical_success_cannot_replace_live_owner(tmp_path):
    # Child leaves only a modeled resource: never intentionally orphan a real PG.
    source = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); "
        "from test_harness import ModelDocker; from tools import s02_harness as h; "
        "o=h.Harness(Path(sys.argv[1]), backend=ModelDocker()).create(); "
        "print(o.directory)"
    )
    notices = []
    short = Path(tempfile.mkdtemp(prefix="i0r-"))
    child = h.run_child([sys.executable, "-c", source, str(tmp_path)], short, 5, notices.append)
    assert child.code == 0 and not child.timed_out
    directory = Path(child.stdout.strip())
    assert not (directory / "work.fence").exists()
    assert not Path(f"/proc/{notices[0]['pid']}").exists()
    with pytest.raises(h.Blocked, match="ENDPOINT_HANDOFF_REFUSED"):
        h.borrowed_socket(directory)
    assert not (directory / "work.fence").exists()
    record(
        tmp_path,
        "historical-owner",
        {
            "notices": notices,
            "model_only": True,
            "historical_success_preserved": True,
            "owner_absent_before_admission": True,
        },
    )


def test_observer_failure_after_exit_reaps_and_closes_pipes(tmp_path, monkeypatch):
    popen = h.subprocess.Popen
    primary = OSError("OBSERVER_AFTER_CHILD_EXIT")
    children, notices = [], []

    def spawn(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    def observe(event):
        notices.append(event)
        # Observe natural exit without consuming wait status; the mechanism must reap.
        os.waitid(os.P_PID, event["pid"], os.WEXITED | os.WNOWAIT)
        raise primary

    monkeypatch.setattr(h.subprocess, "Popen", spawn)
    with pytest.raises(OSError) as caught:
        h.run_child([sys.executable, "-c", "import time; time.sleep(.05)"], tmp_path, 1, observe)
    child = children[0]
    closed = child.stdout.closed and child.stderr.closed
    absent = not Path(f"/proc/{child.pid}").exists()
    record(
        tmp_path,
        "observer-exited",
        {
            "notices": notices,
            "primary_identity": caught.value is primary,
            "reaped": child.returncode == 0,
            "pid_absent_before_rescue": absent,
            "pipes_closed_before_rescue": closed,
        },
    )
    try:
        assert caught.value is primary and child.returncode == 0 and absent
        assert closed
    finally:
        if not child.stdout.closed:
            child.stdout.close()
        if not child.stderr.closed:
            child.stderr.close()
