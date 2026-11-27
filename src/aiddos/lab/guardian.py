"""Independent local process-stop Guardian; no adapter, traffic, or discovery."""

import argparse
import fcntl
import json
import os
import re
import select
import signal
import stat
import sys
import time
from contextlib import suppress

MAX_DOCUMENT_BYTES = 4096
MAX_DEADLINE_NS = 300_000_000_000
_RECEIPT = "guardian-receipt.json"
_HASH = re.compile(r"[0-9a-f]{64}")
_BOOT = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_PIPE = re.compile(r"pipe:\[([0-9]+)\]")


class GuardianError(Exception):
    """Sanitized refusal or uncertain-stop result."""

    def __init__(self, code, exit_code=78):
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def _reject(*_args):
    raise ValueError()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if type(key) is not str or key in value:
            raise ValueError()
        value[key] = item
    return value


def _read_all(fd):
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise GuardianError("INVALID_DOCUMENT")
        os.lseek(fd, 0, os.SEEK_SET)
        value = bytearray()
        while len(value) <= MAX_DOCUMENT_BYTES:
            chunk = os.read(fd, MAX_DOCUMENT_BYTES + 1 - len(value))
            if not chunk:
                break
            value.extend(chunk)
        if len(value) > MAX_DOCUMENT_BYTES:
            raise GuardianError("DOCUMENT_TOO_LARGE")
        return bytes(value)
    except GuardianError:
        raise
    except OSError:
        raise GuardianError("INVALID_DOCUMENT") from None


def _decode(raw):
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_object,
            parse_float=_reject,
            parse_constant=_reject,
        )
    except (UnicodeError, ValueError, TypeError, RecursionError, json.JSONDecodeError):
        raise GuardianError("INVALID_DOCUMENT") from None


def _integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _spec(fd):
    value = _decode(_read_all(fd))
    if type(value) is not dict or set(value) != {
        "schema_version",
        "profile_sha256",
        "authority_sha256",
        "state",
        "target",
        "deadline_monotonic_ns",
        "term_grace_ms",
    }:
        raise GuardianError("INVALID_SPEC")
    target = value["target"]
    state = value["state"]
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["profile_sha256"]) is not str
        or _HASH.fullmatch(value["profile_sha256"]) is None
        or type(value["authority_sha256"]) is not str
        or _HASH.fullmatch(value["authority_sha256"]) is None
        or type(state) is not dict
        or set(state) != {"st_dev", "st_ino"}
        or not _integer(state["st_dev"], 0, 2**64 - 1)
        or not _integer(state["st_ino"], 1, 2**64 - 1)
        or type(target) is not dict
        or set(target) != {"pid", "start_ticks", "boot_id"}
        or not _integer(target["pid"], 1, 2**31 - 1)
        or type(target["start_ticks"]) is not str
        or re.fullmatch(r"[0-9]{1,32}", target["start_ticks"]) is None
        or type(target["boot_id"]) is not str
        or _BOOT.fullmatch(target["boot_id"]) is None
        or not _integer(value["deadline_monotonic_ns"], 0, 2**63 - 1)
        or not _integer(value["term_grace_ms"], 10, 1000)
    ):
        raise GuardianError("INVALID_SPEC")
    now = time.monotonic_ns()
    if not now < value["deadline_monotonic_ns"] <= now + MAX_DEADLINE_NS:
        raise GuardianError("INVALID_SPEC")
    return value


def _private_directory(fd, expected):
    try:
        value = os.fstat(fd)
    except OSError:
        raise GuardianError("INVALID_STATE_DIRECTORY") from None
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_mode & 0o077
        or (value.st_dev, value.st_ino) != (expected["st_dev"], expected["st_ino"])
    ):
        raise GuardianError("INVALID_STATE_DIRECTORY")


def _valid_budget(value):
    if type(value) is not dict or set(value) != {
        "max_attempts",
        "min_interval_ms",
        "concurrency",
        "request_timeout_ms",
        "overall_timeout_ms",
        "retries",
    }:
        return False
    checks = (
        ("max_attempts", 1, 3),
        ("min_interval_ms", 1000, 30000),
        ("concurrency", 1, 1),
        ("request_timeout_ms", 1, 3000),
        ("overall_timeout_ms", 1, 30000),
        ("retries", 0, 0),
    )
    return all(_integer(value[key], low, high) for key, low, high in checks) and (
        value["request_timeout_ms"] <= value["overall_timeout_ms"]
    )


def _claim(state_fd, spec):
    fd = None
    try:
        fd = os.open(
            "baseline-claim.json",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=state_fd,
        )
        value = _decode(_read_all(fd))
    except GuardianError:
        raise
    except OSError:
        raise GuardianError("INVALID_CLAIM") from None
    finally:
        if fd is not None:
            os.close(fd)
    if (
        type(value) is not dict
        or set(value)
        != {"schema_version", "kind", "profile_sha256", "authority_sha256", "budget"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 2
        or value["kind"] != "BASELINE_SESSION_CLAIM"
        or value["profile_sha256"] != spec["profile_sha256"]
        or value["authority_sha256"] != spec["authority_sha256"]
        or not _valid_budget(value["budget"])
    ):
        raise GuardianError("INVALID_CLAIM")


def _pipe(fd, access, code, *, nonblocking=False):
    try:
        info = os.fstat(fd)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        target = os.readlink(f"/proc/self/fd/{fd}")
        match = _PIPE.fullmatch(target)
        if (
            not stat.S_ISFIFO(info.st_mode)
            or flags & os.O_ACCMODE != access
            or match is None
        ):
            raise GuardianError(code)
        if nonblocking:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return match.group(1)
    except GuardianError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise GuardianError(code) from None


def _publish_ready(fd):
    try:
        if os.write(fd, b"READY\n") != 6:
            raise GuardianError("READY_IO_ERROR")
    except GuardianError:
        raise
    except OSError:
        raise GuardianError("READY_IO_ERROR") from None
    finally:
        with suppress(OSError):
            os.close(fd)


def _pidfd_pid(fd):
    try:
        with open(f"/proc/self/fdinfo/{fd}", encoding="ascii") as stream:
            fields = dict(
                line.rstrip("\n").split(":\t", 1)
                for line in stream
                if ":\t" in line
            )
        return int(fields["Pid"])
    except (OSError, UnicodeError, KeyError, TypeError, ValueError):
        raise GuardianError("INVALID_TARGET") from None


def _target(spec, pidfd):
    target = spec["target"]
    if _pidfd_pid(pidfd) != target["pid"]:
        raise GuardianError("INVALID_TARGET")
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as stream:
            boot = stream.read().strip()
        with open(f"/proc/{target['pid']}/stat", encoding="ascii") as stream:
            fields = stream.read().rsplit(")", 1)[1].split()
        state, start = fields[0], fields[19]
    except (OSError, UnicodeError, ValueError, IndexError):
        raise GuardianError("INVALID_TARGET") from None
    if (
        boot != target["boot_id"]
        or start != target["start_ticks"]
        or state not in {"T", "t"}
    ):
        raise GuardianError("INVALID_TARGET")


def _ready(fd, timeout_ms):
    poller = select.poll()
    poller.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return bool(poller.poll(timeout_ms))


def _timeout(deadline):
    remaining = max(0, deadline - time.monotonic_ns())
    return (remaining + 999_999) // 1_000_000


def _drain(fd, buffer, limit):
    closed = False
    while len(buffer) <= limit:
        try:
            chunk = os.read(fd, limit + 1 - len(buffer))
        except BlockingIOError:
            break
        except OSError:
            return buffer, True
        if not chunk:
            closed = True
            break
        buffer += chunk
        if b"\n" in buffer or len(buffer) > limit:
            break
    return buffer, closed


def _control_event(fd, buffer):
    buffer, closed = _drain(fd, buffer, 5)
    if buffer == b"STOP\n":
        return "STOP_REQUESTED", buffer
    if len(buffer) > 5 or b"\n" in buffer or (closed and buffer):
        return "CONTROL_INVALID", buffer
    if closed:
        return "CONTROL_LOST", buffer
    return None, buffer


def _release_event(fd, buffer):
    buffer, closed = _drain(fd, buffer, 3)
    if len(buffer) > 3 or b"\n" in buffer and buffer != b"GO\n":
        return "RELEASE_INVALID", buffer
    if closed:
        return ("RELEASED" if buffer == b"GO\n" else "RELEASE_LOST"), buffer
    return None, buffer


def _before_release(spec, pidfd, control_fd, release_fd):
    poller = select.poll()
    poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    poller.register(control_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    poller.register(release_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    control = release = b""
    while True:
        events = dict(poller.poll(_timeout(spec["deadline_monotonic_ns"])))
        if pidfd in events:
            return "TARGET_EXITED", False
        if time.monotonic_ns() >= spec["deadline_monotonic_ns"]:
            return "DEADLINE", False
        if control_fd in events:
            trigger, control = _control_event(control_fd, control)
            if trigger:
                return trigger, False
        if release_fd in events:
            trigger, release = _release_event(release_fd, release)
            if trigger and trigger != "RELEASED":
                return trigger, False
            if trigger == "RELEASED":
                if control:
                    return "CONTROL_INVALID", False
                immediate = dict(poller.poll(0))
                if pidfd in immediate:
                    return "TARGET_EXITED", False
                if time.monotonic_ns() >= spec["deadline_monotonic_ns"]:
                    return "DEADLINE", False
                if control_fd in immediate:
                    control_trigger, control = _control_event(control_fd, control)
                    if control_trigger:
                        return control_trigger, False
                try:
                    _target(spec, pidfd)
                    signal.pidfd_send_signal(pidfd, signal.SIGCONT)
                except ProcessLookupError:
                    return "TARGET_EXITED", False
                except GuardianError:
                    return ("TARGET_EXITED" if _ready(pidfd, 0) else "RELEASE_FAILED"), False
                except OSError:
                    return "RELEASE_FAILED", False
                return "RELEASED", True


def _trigger(spec, pidfd, control_fd):
    poller = select.poll()
    poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    poller.register(control_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
    control = b""
    while True:
        events = dict(poller.poll(_timeout(spec["deadline_monotonic_ns"])))
        if pidfd in events:
            return "TARGET_EXITED"
        if time.monotonic_ns() >= spec["deadline_monotonic_ns"]:
            return "DEADLINE"
        if control_fd in events:
            trigger, control = _control_event(control_fd, control)
            if trigger:
                return trigger


def _stop(pidfd, grace_ms):
    signals = []
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        signals.append("SIGTERM")
    except ProcessLookupError:
        return signals, True
    except OSError:
        return signals, False
    if _ready(pidfd, grace_ms):
        return signals, True
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        signals.append("SIGKILL")
    except ProcessLookupError:
        return signals, True
    except OSError:
        return signals, False
    return signals, _ready(pidfd, 1000)


def _write_receipt(state_fd, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise GuardianError("RECEIPT_IO_ERROR", 75)
    fd = None
    try:
        fd = os.open(
            _RECEIPT,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=state_fd,
        )
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                raise OSError()
            offset += count
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.fsync(state_fd)
    except OSError:
        raise GuardianError("RECEIPT_IO_ERROR", 75) from None
    finally:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)


def run(spec_fd, target_pidfd, control_fd, release_fd, ready_fd, state_dir_fd):
    spec = _spec(spec_fd)
    _private_directory(state_dir_fd, spec["state"])
    _claim(state_dir_fd, spec)
    control_pipe = _pipe(control_fd, os.O_RDONLY, "INVALID_CONTROL", nonblocking=True)
    release_pipe = _pipe(release_fd, os.O_RDONLY, "INVALID_RELEASE", nonblocking=True)
    ready_pipe = _pipe(ready_fd, os.O_WRONLY, "READY_IO_ERROR", nonblocking=True)
    if len({control_pipe, release_pipe, ready_pipe}) != 3:
        raise GuardianError("INVALID_PIPE_BINDING")
    _target(spec, target_pidfd)
    if time.monotonic_ns() >= spec["deadline_monotonic_ns"]:
        raise GuardianError("INVALID_SPEC")
    _publish_ready(ready_fd)
    trigger, released = _before_release(spec, target_pidfd, control_fd, release_fd)
    if trigger == "RELEASED":
        trigger = _trigger(spec, target_pidfd, control_fd)
    with suppress(OSError):
        os.close(release_fd)
    signals = []
    stopped = True
    if trigger != "TARGET_EXITED":
        signals, stopped = _stop(target_pidfd, spec["term_grace_ms"])
    receipt = {
        "schema_version": 1,
        "kind": (
            "GUARDIAN_EXIT_RECEIPT"
            if trigger == "TARGET_EXITED"
            else "GUARDIAN_STOP_RECEIPT"
        ),
        "profile_sha256": spec["profile_sha256"],
        "authority_sha256": spec["authority_sha256"],
        "state": spec["state"],
        "target": spec["target"],
        "trigger": trigger,
        "signals": signals,
        "released": released,
        "stopped": stopped,
        "cleanup_uncertain": not stopped,
    }
    _write_receipt(state_dir_fd, receipt)
    if not stopped:
        raise GuardianError("STOP_UNCERTAIN", 75)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ddospector.lab.guardian", allow_abbrev=False)
    parser.add_argument("--spec-fd", type=int, required=True)
    parser.add_argument("--target-pidfd", type=int, required=True)
    parser.add_argument("--control-fd", type=int, required=True)
    parser.add_argument("--release-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    parser.add_argument("--state-dir-fd", type=int, required=True)
    args = parser.parse_args(argv)
    if min(
        args.spec_fd,
        args.target_pidfd,
        args.control_fd,
        args.release_fd,
        args.ready_fd,
        args.state_dir_fd,
    ) < 0:
        print("REFUSED: INVALID_FD", file=sys.stderr)
        return 78
    try:
        return run(
            args.spec_fd,
            args.target_pidfd,
            args.control_fd,
            args.release_fd,
            args.ready_fd,
            args.state_dir_fd,
        )
    except GuardianError as failure:
        print(f"REFUSED: {failure.code}", file=sys.stderr)
        return failure.exit_code
    except Exception:
        print("REFUSED: INTERNAL_ERROR", file=sys.stderr)
        return 78
