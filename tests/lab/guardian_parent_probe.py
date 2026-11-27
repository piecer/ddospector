"""Fresh launcher that dies after arming an independent Guardian."""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HASHES = {"profile_sha256": "1" * 64, "authority_sha256": "2" * 64}


def identity(pid):
    return {
        "pid": pid,
        "start_ticks": Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def main():
    state, metadata = map(Path, sys.argv[1:])
    target = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,signal,time; print('CREATED', flush=True); "
            "os.kill(os.getpid(), signal.SIGSTOP); "
            "signal.signal(signal.SIGTERM, lambda *_: None); "
            "print('ACTIVE', flush=True); time.sleep(30)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    assert target.stdout is not None and target.stdout.readline() == "CREATED\n"
    deadline = time.monotonic() + 5
    state_value = None
    while time.monotonic() < deadline:
        state_value = Path(f"/proc/{target.pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        if state_value == "T":
            break
        time.sleep(0.01)
    assert state_value == "T"
    target_identity = identity(target.pid)
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
    write_json(state / "baseline-claim.json", claim)
    info = os.stat(state)
    spec = {
        "schema_version": 1,
        **HASHES,
        "state": {"st_dev": info.st_dev, "st_ino": info.st_ino},
        "target": target_identity,
        "deadline_monotonic_ns": time.monotonic_ns() + 5_000_000_000,
        "term_grace_ms": 100,
    }
    spec_path = state / "guardian-spec.json"
    write_json(spec_path, spec)
    spec_fd = os.open(spec_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    pidfd = os.pidfd_open(target.pid)
    control_read, control_write = os.pipe2(os.O_CLOEXEC)
    release_read, release_write = os.pipe2(os.O_CLOEXEC)
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
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
            str(ready_write),
            "--state-dir-fd",
            str(state_fd),
        ],
        cwd=ROOT,
        env={
            "PATH": os.defpath,
            "HOME": str(state.parent),
            "TMPDIR": str(state.parent),
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        pass_fds=(spec_fd, pidfd, control_read, release_read, ready_write, state_fd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    os.close(control_read)
    os.close(release_read)
    os.close(ready_write)
    assert select.select([ready_read], [], [], 5)[0]
    assert os.read(ready_read, 6) == b"READY\n"
    os.close(ready_read)
    assert os.write(release_write, b"GO\n") == 3
    os.close(release_write)
    assert target.stdout.readline() == "ACTIVE\n"
    write_json(
        metadata,
        {
            "launcher": identity(os.getpid()),
            "guardian": identity(guardian.pid),
            "target": target_identity,
        },
    )
    os._exit(0)


if __name__ == "__main__":
    main()
