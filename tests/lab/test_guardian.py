"""P0-B2 independent Guardian process contract; no lab traffic or adapter."""

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
HASHES = {"profile_sha256": "1" * 64, "authority_sha256": "2" * 64}


def process_state(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]


def identity(pid):
    return {
        "pid": pid,
        "start_ticks": Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def launch(
    tmp_path,
    target_code,
    *,
    deadline_ns=None,
    grace_ms=100,
    claim_update=None,
    spec_update=None,
    state_update=None,
    target_update=None,
    pipe_case=None,
    expect_ready=True,
    auto_release=True,
):
    wrapped = (
        "import os,signal; print('CREATED', flush=True); "
        "os.kill(os.getpid(), signal.SIGSTOP); " + target_code
    )
    target = subprocess.Popen(
        [sys.executable, "-c", wrapped],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert target.stdout is not None
    assert target.stdout.readline() == "CREATED\n"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and process_state(target.pid) != "T":
        time.sleep(0.01)
    assert process_state(target.pid) == "T"
    target_identity = identity(target.pid)
    if target_update:
        target_identity.update(target_update)
    claim = {
        "schema_version": 2,
        "kind": "BASELINE_SESSION_CLAIM",
        **HASHES,
        "budget": {
            "max_attempts": 1,
            "min_interval_ms": 1000,
            "concurrency": 1,
            "request_timeout_ms": 1000,
            "overall_timeout_ms": 5000,
            "retries": 0,
        },
    }
    if claim_update:
        claim.update(claim_update)
    write_json(tmp_path / "baseline-claim.json", claim)
    state_info = os.stat(tmp_path)
    state_identity = {"st_dev": state_info.st_dev, "st_ino": state_info.st_ino}
    if state_update:
        state_identity.update(state_update)
    spec = {
        "schema_version": 1,
        **HASHES,
        "state": state_identity,
        "target": target_identity,
        "deadline_monotonic_ns": deadline_ns or time.monotonic_ns() + 5_000_000_000,
        "term_grace_ms": grace_ms,
    }
    if spec_update:
        spec.update(spec_update)
    spec_path = tmp_path / "guardian-spec.json"
    write_json(spec_path, spec)
    spec_fd = os.open(spec_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    state_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    pidfd = os.pidfd_open(target.pid)
    control_read, control_write = os.pipe2(os.O_CLOEXEC)
    release_read, release_write = os.pipe2(os.O_CLOEXEC)
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
    guardian_ready = control_write if pipe_case == "ready_is_control_write" else ready_write
    inherited = tuple(
        dict.fromkeys((spec_fd, pidfd, control_read, release_read, guardian_ready, state_fd))
    )
    guardian = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ddospector.lab.guardian",
            "--spec-fd",
            str(spec_fd),
            "--target-pidfd",
            str(pidfd),
            "--control-fd",
            str(control_read),
            "--release-fd",
            str(release_read),
            "--ready-fd",
            str(guardian_ready),
            "--state-dir-fd",
            str(state_fd),
        ],
        cwd=ROOT,
        env={
            "PATH": os.defpath,
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        pass_fds=inherited,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(control_read)
    os.close(release_read)
    os.close(ready_write)
    try:
        assert select.select([ready_read], [], [], 5)[0]
        ready = os.read(ready_read, 6)
        assert ready == (b"READY\n" if expect_ready else b"")
    except BaseException:
        os.close(ready_read)
        os.close(control_write)
        os.close(release_write)
        for fd in (state_fd, spec_fd, pidfd):
            os.close(fd)
        if guardian.poll() is None:
            guardian.kill()
        guardian.communicate(timeout=5)
        if target.poll() is None:
            target.kill()
        target.communicate(timeout=5)
        raise
    os.close(ready_read)
    assert process_state(target.pid) == "T"
    if expect_ready and auto_release:
        assert os.write(release_write, b"GO\n") == 3
        os.close(release_write)
        release_write = None
        assert target.stdout.readline() == "ACTIVE\n"
    return SimpleNamespace(
        target=target,
        guardian=guardian,
        identity=target_identity,
        state=state_identity,
        control_write=control_write,
        release_write=release_write,
        fixed_fds=(state_fd, spec_fd, pidfd),
    )


def cleanup(item):
    if item.control_write is not None:
        os.close(item.control_write)
        item.control_write = None
    if item.release_write is not None:
        os.close(item.release_write)
        item.release_write = None
    for fd in item.fixed_fds:
        os.close(fd)
    if item.guardian.poll() is None:
        item.guardian.kill()
        item.guardian.communicate(timeout=5)
    if item.target.poll() is None:
        item.target.kill()
    item.target.communicate(timeout=5)


def guardian_result(item):
    stdout, stderr = item.guardian.communicate(timeout=5)
    assert item.guardian.returncode == 0, (stdout, stderr)


def guardian_refusal(item, code):
    stdout, stderr = item.guardian.communicate(timeout=5)
    assert item.guardian.returncode == 78, (stdout, stderr)
    assert stdout == "" and stderr == f"REFUSED: {code}\n"


def guardian_uncertain(item, code):
    stdout, stderr = item.guardian.communicate(timeout=5)
    assert item.guardian.returncode == 75, (stdout, stderr)
    assert stdout == "" and stderr == f"REFUSED: {code}\n"


def receipt(tmp_path):
    return json.loads((tmp_path / "guardian-receipt.json").read_text())


def same_process(value):
    try:
        start = Path(f"/proc/{value['pid']}/stat").read_text().rsplit(")", 1)[1].split()[19]
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return start == value["start_ticks"] and boot == value["boot_id"]
    except OSError:
        return False


def test_actual_launcher_death_triggers_independent_guardian_stop(tmp_path, record_property):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    metadata = tmp_path / "parent-death.json"
    probe = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tests/lab/guardian_parent_probe.py"),
            str(state),
            str(metadata),
        ],
        cwd=ROOT,
        env={
            "PATH": os.defpath,
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert probe.returncode == 0, (probe.stdout, probe.stderr)
    processes = json.loads(metadata.read_text())
    try:
        deadline = time.monotonic() + 5
        path = state / "guardian-receipt.json"
        while time.monotonic() < deadline:
            if path.exists() and not same_process(processes["guardian"]):
                break
            time.sleep(0.01)
        assert path.exists()
        assert not same_process(processes["guardian"])
        assert not same_process(processes["target"])
        value = json.loads(path.read_text())
        assert value["trigger"] == "CONTROL_LOST"
        assert value["signals"] == ["SIGTERM", "SIGKILL"]
        assert value["stopped"] is True and value["cleanup_uncertain"] is False
    finally:
        for name in ("guardian", "target"):
            if same_process(processes[name]):
                os.kill(processes[name]["pid"], signal.SIGKILL)
        record_property("owned_processes", json.dumps(processes, sort_keys=True))


def test_ready_keeps_target_stopped_until_guardian_receives_release(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        auto_release=False,
    )
    try:
        assert process_state(item.target.pid) == "T"
        assert select.select([item.target.stdout], [], [], 0.05)[0] == []
        assert os.write(item.release_write, b"GO\n") == 3
        os.close(item.release_write)
        item.release_write = None
        assert item.target.stdout.readline() == "ACTIVE\n"
        os.close(item.control_write)
        item.control_write = None
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGTERM
        assert receipt(tmp_path)["released"] is True
    finally:
        cleanup(item)


def test_control_loss_stops_term_ignoring_owned_target_and_records_receipt(tmp_path):
    item = launch(
        tmp_path,
        "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); "
        "print('ACTIVE', flush=True); time.sleep(30)",
    )
    try:
        os.close(item.control_write)
        item.control_write = None
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGKILL
        assert receipt(tmp_path) == {
            "schema_version": 1,
            "kind": "GUARDIAN_STOP_RECEIPT",
            **HASHES,
            "state": item.state,
            "target": item.identity,
            "trigger": "CONTROL_LOST",
            "signals": ["SIGTERM", "SIGKILL"],
            "released": True,
            "stopped": True,
            "cleanup_uncertain": False,
        }
        assert (tmp_path / "guardian-receipt.json").stat().st_mode & 0o777 == 0o600
    finally:
        cleanup(item)


def test_natural_target_exit_is_observed_without_a_signal_or_stop_claim(tmp_path):
    item = launch(tmp_path, "import time; print('ACTIVE', flush=True); time.sleep(0.05)")
    try:
        guardian_result(item)
        assert item.target.wait(timeout=5) == 0
        assert receipt(tmp_path) == {
            "schema_version": 1,
            "kind": "GUARDIAN_EXIT_RECEIPT",
            **HASHES,
            "state": item.state,
            "target": item.identity,
            "trigger": "TARGET_EXITED",
            "signals": [],
            "released": True,
            "stopped": True,
            "cleanup_uncertain": False,
        }
    finally:
        cleanup(item)


@pytest.mark.parametrize(
    "control,trigger",
    [(b"STOP\n", "STOP_REQUESTED"), (b"INVALID\n", "CONTROL_INVALID"), (None, "DEADLINE")],
)
def test_explicit_invalid_or_deadline_control_stops_the_target(tmp_path, control, trigger):
    deadline = time.monotonic_ns() + (100_000_000 if control is None else 5_000_000_000)
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        deadline_ns=deadline,
    )
    try:
        if control is not None:
            os.write(item.control_write, control)
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGTERM
        value = receipt(tmp_path)
        assert value["kind"] == "GUARDIAN_STOP_RECEIPT"
        assert value["trigger"] == trigger
        assert value["signals"] == ["SIGTERM"]
        assert value["stopped"] is True and value["cleanup_uncertain"] is False
    finally:
        cleanup(item)


def test_claim_mismatch_refuses_before_ready_without_signalling_target(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        claim_update={"authority_sha256": "3" * 64},
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_CLAIM")
        assert item.target.poll() is None
        assert not (tmp_path / "guardian-receipt.json").exists()
    finally:
        cleanup(item)


def test_state_identity_mismatch_refuses_before_ready_or_signal(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        state_update={"st_ino": 1},
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_STATE_DIRECTORY")
        assert item.target.poll() is None
        assert not (tmp_path / "guardian-receipt.json").exists()
    finally:
        cleanup(item)


def test_expired_deadline_refuses_before_ready_or_signal(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        deadline_ns=time.monotonic_ns() - 1,
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_SPEC")
        assert item.target.poll() is None
        assert not (tmp_path / "guardian-receipt.json").exists()
    finally:
        cleanup(item)


def test_pidfd_identity_mismatch_refuses_before_ready_or_signal(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        target_update={"start_ticks": "1"},
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_TARGET")
        assert item.target.poll() is None
        assert not (tmp_path / "guardian-receipt.json").exists()
    finally:
        cleanup(item)


def test_boolean_schema_version_is_not_accepted_as_integer_one(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        spec_update={"schema_version": True},
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_SPEC")
        assert process_state(item.target.pid) == "T"
    finally:
        cleanup(item)


def test_receipt_collision_never_prevents_stop_or_overwrites_evidence(tmp_path):
    item = launch(
        tmp_path,
        "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); "
        "print('ACTIVE', flush=True); time.sleep(30)",
    )
    retained = b"PRIVATE_RETAINED_RECEIPT\n"
    try:
        path = tmp_path / "guardian-receipt.json"
        path.write_bytes(retained)
        path.chmod(0o600)
        os.close(item.control_write)
        item.control_write = None
        guardian_uncertain(item, "RECEIPT_IO_ERROR")
        assert item.target.wait(timeout=5) == -signal.SIGKILL
        assert path.read_bytes() == retained
    finally:
        cleanup(item)


def test_same_pipe_cannot_supply_control_and_ready_directions(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        pipe_case="ready_is_control_write",
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_PIPE_BINDING")
        assert process_state(item.target.pid) == "T"
    finally:
        cleanup(item)


def test_invalid_claim_budget_refuses_before_ready(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        claim_update={
            "budget": {
                "max_attempts": 1,
                "min_interval_ms": 0,
                "concurrency": 1,
                "request_timeout_ms": 1000,
                "overall_timeout_ms": 5000,
                "retries": 0,
            }
        },
        expect_ready=False,
    )
    try:
        guardian_refusal(item, "INVALID_CLAIM")
        assert process_state(item.target.pid) == "T"
    finally:
        cleanup(item)


@pytest.mark.parametrize(
    "raw",
    [b"[" * 1200 + b"]" * 1200, '{"schema_version":1}'.encode("utf-16")],
)
def test_non_contract_json_is_sanitized_without_traceback(tmp_path, raw):
    spec = tmp_path / "invalid.json"
    spec.write_bytes(raw)
    spec.chmod(0o600)
    fd = os.open(spec, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ddospector.lab.guardian",
                "--spec-fd",
                str(fd),
                "--target-pidfd",
                str(fd),
                "--control-fd",
                str(fd),
                "--release-fd",
                str(fd),
                "--ready-fd",
                str(fd),
                "--state-dir-fd",
                str(fd),
            ],
            cwd=ROOT,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT / "src")},
            pass_fds=(fd,),
            capture_output=True,
            text=True,
            timeout=5,
        )
    finally:
        os.close(fd)
    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr in {"REFUSED: INVALID_DOCUMENT\n", "REFUSED: INVALID_SPEC\n"}
    assert "Traceback" not in result.stderr and str(ROOT) not in result.stderr


@pytest.mark.parametrize(
    "parts,trigger",
    [((b"ST", b"OP\n"), "STOP_REQUESTED"), ((b"STOP\nX",), "CONTROL_INVALID")],
)
def test_control_stream_framing_is_bounded_and_deterministic(tmp_path, parts, trigger):
    item = launch(tmp_path, "import time; print('ACTIVE', flush=True); time.sleep(30)")
    try:
        for part in parts:
            os.write(item.control_write, part)
            time.sleep(0.01)
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGTERM
        assert receipt(tmp_path)["trigger"] == trigger
    finally:
        cleanup(item)


def test_invalid_release_frame_stops_paused_target_without_releasing_it(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        auto_release=False,
    )
    try:
        os.write(item.release_write, b"GO\nX")
        os.close(item.release_write)
        item.release_write = None
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGKILL
        value = receipt(tmp_path)
        assert value["trigger"] == "RELEASE_INVALID"
        assert value["released"] is False
        assert value["signals"] == ["SIGTERM", "SIGKILL"]
    finally:
        cleanup(item)


def test_partial_control_frame_blocks_release_and_stops_paused_target(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        deadline_ns=time.monotonic_ns() + 500_000_000,
        auto_release=False,
    )
    try:
        os.write(item.control_write, b"ST")
        time.sleep(0.02)
        os.write(item.release_write, b"GO\n")
        os.close(item.release_write)
        item.release_write = None
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGKILL
        assert item.target.stdout.read() == ""
        value = receipt(tmp_path)
        assert value["trigger"] == "CONTROL_INVALID"
        assert value["released"] is False
    finally:
        cleanup(item)


def test_release_revalidation_failure_stops_target_and_records_failure(tmp_path):
    item = launch(
        tmp_path,
        "import time; print('ACTIVE', flush=True); time.sleep(30)",
        auto_release=False,
    )
    try:
        os.kill(item.target.pid, signal.SIGCONT)
        assert item.target.stdout.readline() == "ACTIVE\n"
        os.write(item.release_write, b"GO\n")
        os.close(item.release_write)
        item.release_write = None
        guardian_result(item)
        assert item.target.wait(timeout=5) == -signal.SIGTERM
        value = receipt(tmp_path)
        assert value["trigger"] == "RELEASE_FAILED"
        assert value["released"] is False
        assert value["signals"] == ["SIGTERM"]
    finally:
        cleanup(item)
