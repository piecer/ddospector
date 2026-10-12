"""Invocation-owned PostgreSQL prerequisite harness; never an application migration.

Unknown custody is terminal for this object. Journals and private directories are
retained, including after CLEAN. There is deliberately no adopt/retry/rescue CLI.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import UUID

IMAGE = "postgres:16.6-alpine3.21"
PROCESS_ARGV = ContextVar("i0_owned_process_argv", default=None)
IMAGE_ID = "sha256:1d04b9ba1d4996401f2552b51beda8187f175c0645c091e4781134fc9c9a3eef"
PG_COMMAND = (
    "postgres",
    "-c",
    "listen_addresses=",
    "-c",
    "unix_socket_directories=/socket",
    "-c",
    "unix_socket_permissions=0777",
    "-c",
    "fsync=on",
    "-c",
    "full_page_writes=on",
    "-c",
    "synchronous_commit=on",
)
# The cached official entrypoint clears PGHOST in docker_process_sql. Override
# ONLY that helper with an explicit owned socket. No arbitrary command is accepted.
PG_INIT = r"""source /usr/local/bin/docker-entrypoint.sh
docker_setup_env
docker_create_db_directories
exec gosu postgres bash -ec '
source /usr/local/bin/docker-entrypoint.sh
docker_process_sql() {
    psql --host=/socket --port=5432 -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
        --dbname "${POSTGRES_DB:-postgres}" --no-password --no-psqlrc "$@"
}
_main "$@"
' -- "$@"
"""
CONTAINER_COMMAND = ("-ec", PG_INIT, "--", *PG_COMMAND)
CONTAINER_FORMAT = (
    '{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"Created":{{json .Created}},"Labels":{{json .Config.Labels}},'
    '"NetworkMode":{{json .HostConfig.NetworkMode}},'
    '"PortBindings":{{json .HostConfig.PortBindings}},'
    '"Memory":{{json .HostConfig.Memory}},"PidsLimit":{{json .HostConfig.PidsLimit}},'
    '"NanoCpus":{{json .HostConfig.NanoCpus}},"LogConfig":{{json .HostConfig.LogConfig}},'
    '"Entrypoint":{{json (index .Config "Entrypoint")}},'
    '"Cmd":{{json (index .Config "Cmd")}},"Status":{{json .State.Status}},'
    '"Mounts":{{json .Mounts}}}'
)
VOLUME_FORMAT = '{"Name":{{json .Name}},"CreatedAt":{{json .CreatedAt}}}'


class Blocked(RuntimeError):
    """Custody/prerequisite refusal; retained evidence requires recovery."""


@contextmanager
def close_once(resource):
    """Never retry a close that may have released its underlying descriptor."""
    try:
        yield resource
    except BaseException as primary:
        try:
            resource.close()
        except BaseException:
            primary.add_note("I0_CLOSE_SECONDARY")
        raise
    else:
        resource.close()


GRANT = struct.Struct("!8sIQ16sIQ32s32sQ32sBQ")
CONTROL = struct.Struct("!QBQ32sIQ16sBBiBBH")
ACTIONS = {"setup": 1, "write": 2, "read": 3}
WARNING = b'WARNING: password file "/dev/null" is not a plain file\n'
UINT64 = (1 << 64) - 1


@dataclass(slots=True)
class Attempt:
    number: int
    action: int = 0
    deadline: int = 0
    digest: bytes = bytes(32)
    pid: int = 0
    start: int = 0
    boot: bytes = bytes(16)
    phase: int = 0
    exit_known: int = 0
    code: int = 0
    closed: int = 0
    unknown: int = 0
    failure: int = 0

    def packed(self):
        return CONTROL.pack(
            self.number,
            self.action,
            self.deadline,
            self.digest,
            self.pid,
            self.start,
            self.boot,
            self.phase,
            self.exit_known,
            self.code,
            self.closed,
            self.unknown,
            self.failure,
        )


def remaining_ns(deadline):
    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise Blocked("PG_PROBE_FAILED")
    return remaining / 1_000_000_000


def source_digest():
    with close_once(Path(__file__).open("rb")) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity_of(pid):
    with close_once(Path(f"/proc/{pid}/stat").open()) as stream:
        fields = stream.read().rsplit(")", 1)[1].split()
    if fields[0] in {"Z", "X"}:
        raise Blocked("ENDPOINT_OWNER_NOT_LIVE")
    with close_once(Path("/proc/sys/kernel/random/boot_id").open()) as stream:
        boot = stream.read().strip()
    return {"pid": pid, "start_ticks": fields[19], "boot_id": boot}


def custody_digest(owner):
    data = {
        "directory": str(owner.directory),
        "owner_process": owner.owner_process,
        "source_sha256": owner.source_sha256,
        "name": owner.name,
        "labels": owner.labels,
        "socket": str(owner.socket),
        "cid": owner.cid,
        "created": owner.created,
        "volume": owner.volume,
        "receipt": owner.receipt,
    }
    return hashlib.sha256(
        json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).digest()


def process_identity():
    return {
        "pid": os.getpid(),
        "start_ticks": Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def child_environment(directory):
    """Fixed allowlist; never copy/read ambient PG, credentials or loader values."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(directory),
        "TMPDIR": str(directory),
        "DOCKER_CONFIG": str(directory / "docker-config"),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


class CapturedPipe:
    """One close attempt shared by communicate and the owner's finalizer.

    Attempted is not closed: retain the stream's actual disposition, but never
    repeat an ambiguous close (its numeric FD may already belong to a caller).
    """

    def __init__(self, stream):
        self.stream = stream
        self.close_attempted = False

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def close(self):
        if not self.close_attempted:
            self.close_attempted = True
            self.stream.close()


def run_child(argv, directory, timeout, observe, *, _grant=None):
    """Owned process group; timeout remains failure even if child then exits zero."""
    if _grant is not None:
        return run_granted(argv, directory, timeout, observe, _grant)
    process = None
    authority = None
    timed_out = False
    retiring = False

    def retire():
        nonlocal retiring
        retiring = True
        failure = None
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except BaseException as error:
            failure = error
        # Even a kill-after-effect reporting error must not skip the reap.
        try:
            output = process.communicate(timeout=2)
        except BaseException as primary:
            # A captured-pipe read can fail BEFORE communicate reaches wait.
            # Reap this exact Popen independently; a kill/attempt is not proof.
            try:
                if process.returncode is None:
                    process.wait(timeout=2)
            except BaseException:
                primary.add_note("I0_WAIT_UNCONFIRMED")
            if failure is None:
                raise
            failure.add_note("I0_REAP_SECONDARY")
            raise failure from None
        if failure is not None:
            raise failure
        return output

    try:
        authority = PROCESS_ARGV.set(tuple(argv))
        process = subprocess.Popen(
            argv,
            env=child_environment(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        process.stdout = CapturedPipe(process.stdout)
        process.stderr = CapturedPipe(process.stderr)
        identity = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        observe(
            {"event": "child_started", "pid": process.pid, "start_ticks": identity, "argv": argv}
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as primary:
            timed_out = True
            try:
                stdout, stderr = retire()
            except BaseException:
                primary.add_note("I0_TIMEOUT_RETIREMENT_SECONDARY")
                raise primary from None
        observe(
            {
                "event": "child_reaped",
                "pid": process.pid,
                "start_ticks": identity,
                "reaped": process.poll() is not None,
                "code": process.returncode,
                "timed_out": timed_out,
            }
        )
        return Result(process.returncode, stdout, stderr, timed_out)
    finally:
        primary = sys.exception()
        secondary = None
        if process is not None and not retiring and process.poll() is None:
            try:
                retire()
            except BaseException as error:
                secondary = error
        # poll() may reap a child that exited before an observer failed. It
        # does not close our captured pipes; retire both even if one reports
        # an error, without retrying an already attempted stream close.
        # Pipe ownership is independent of wait status. A failed wait leaves
        # child custody unconfirmed, but must not strand both captured streams.
        for stream in () if process is None else (process.stdout, process.stderr):
            if not stream.closed:
                try:
                    stream.close()
                except BaseException as error:
                    if secondary is None:
                        secondary = error
                    else:
                        secondary.add_note("I0_PIPE_CLOSE_SECONDARY")
        if authority is not None:
            try:
                PROCESS_ARGV.reset(authority)
            except BaseException as error:
                secondary = secondary or error
        if secondary is not None:
            if primary is None:
                raise secondary
            primary.add_note("I0_PROCESS_RETIREMENT_SECONDARY")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Blocked("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def closed_json(raw, limit):
    if len(raw) > limit or not raw.startswith(b"{") or not raw.endswith(b"}\n"):
        raise Blocked("CHILD_JSON_FRAMING")
    try:
        text = raw.decode("utf-8")
        value, end = json.JSONDecoder(object_pairs_hook=unique_object).raw_decode(text)
    except (ValueError, UnicodeError, RecursionError):
        raise Blocked("CHILD_JSON_REFUSED") from None
    if end != len(text) - 1:
        raise Blocked("CHILD_JSON_TRAILING")
    return value


def diagnostic(raw):
    """Exact W* + optional J; no rewriting of accepted native bytes."""
    if len(raw) > 4096:
        raise Blocked("CHILD_DIAGNOSTIC_LIMIT")
    offset = 0
    while raw.startswith(WARNING, offset):
        offset += len(WARNING)
    if offset == len(raw):
        return False
    value = closed_json(raw[offset:], 4096)
    if type(value) is not dict or value.keys() != {"blocked", "site"}:
        raise Blocked("CHILD_DIAGNOSTIC_KEYS")
    name, sites = value["blocked"], value["site"]
    if (
        type(name) is not str
        or not 1 <= len(name) <= 64
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
        or type(sites) is not list
        or len(sites) > 16
    ):
        raise Blocked("CHILD_DIAGNOSTIC_SHAPE")
    for site in sites:
        if (
            type(site) is not list
            or len(site) != 2
            or type(site[0]) is not str
            or not 1 <= len(site[0]) <= 64
            or not site[0].isascii()
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|<[A-Za-z_][A-Za-z0-9_]*>", site[0]) is None
            or type(site[1]) is not int
            or not 1 <= site[1] <= 0xFFFFFFFF
        ):
            raise Blocked("CHILD_DIAGNOSTIC_SITE")
    return True


def same_shape(value, expected):
    if type(value) is not type(expected):
        return False
    if type(expected) is list:
        return len(value) == len(expected) and all(
            same_shape(a, b) for a, b in zip(value, expected, strict=True)
        )
    return value == expected


def validate_proof(proof, action):
    expected = {
        "server_major": 16,
        "durability": ["on"] * 3,
        "identity": ["aiddos_s02", "aiddos_s02", None],
        "owner": ["aiddos_s02_owner", False, False, False, False],
        "socket_settings": ["", "/socket", "0777"],
        "connection_cap_enforced": True if action == "write" else None,
        "runtime": [False, False, False, False, 8],
        "ddl_denied": True,
        "value": None if action == "setup" else "i0-probe-not-application",
        "af_unix": True,
        "app_schema_absent": True,
    }
    if type(proof) is not dict or proof.keys() != expected.keys() | {
        "driver",
        "module",
        "interpreter",
        "prefix",
    }:
        raise Blocked("PROOF_KEYS_REFUSED")
    for key, value in expected.items():
        if not same_shape(proof[key], value):
            raise Blocked("PROOF_INVARIANT_REFUSED")
    for key in ("module", "interpreter", "prefix"):
        value = proof[key]
        if (
            type(value) is not str
            or not 1 <= len(value) <= 4096
            or not value.startswith("/")
            or len(value.encode("utf-8")) > 4096
        ):
            raise Blocked("PROOF_PROVENANCE_REFUSED")
    driver = proof["driver"]
    if (
        type(driver) is not str
        or not 1 <= len(driver) <= 256
        or not driver.isascii()
        or not driver.isprintable()
    ):
        raise Blocked("PROOF_DRIVER_REFUSED")
    return proof


def encode_proof(envelope, action):
    validate_proof(envelope["proof"], action)
    encoded = (json.dumps(envelope, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > 81920:
        raise Blocked("PROOF_LIMIT")
    return encoded


def decode_proof(raw, digest, action):
    if len(raw) > 81920:
        raise Blocked("PROOF_LIMIT")
    envelope = closed_json(raw, 81920)
    if (
        type(envelope) is not dict
        or envelope.keys() != {"grant_sha256", "proof"}
        or envelope["grant_sha256"] != digest
    ):
        raise Blocked("PROOF_BINDING_REFUSED")
    if encode_proof(envelope, action) != raw:
        raise Blocked("PROOF_ENCODING_REFUSED")
    return envelope["proof"]


def run_granted(argv, directory, timeout, observe, grant_owner):
    """The private owner retains the exact process through every fallible tail."""
    owner, attempt = grant_owner
    if owner.attempt is not attempt or owner.work_state != "PENDING":
        raise Blocked("GRANT_OWNER_REFUSED")
    process = None
    token = None
    timed_out = False
    stdout, stderr = b"", b""
    failure_code = 1
    try:
        try:
            remaining_ns(attempt.deadline)
            action = next((name for name, code in ACTIONS.items() if code == attempt.action), None)
            expected = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--pg-child",
                str(owner.directory),
                "--action",
                action,
                "--i0-attempt",
                str(attempt.number),
                "--i0-deadline-ns",
                str(attempt.deadline),
            ]
            if (
                action is None
                or argv != expected
                or directory != owner.socket.parent
                or identity_of(os.getpid()) != owner.owner_process
                or source_digest() != owner.source_sha256
            ):
                raise Blocked("GRANT_LAUNCH_REFUSED")
            environment = child_environment(directory)
            token = PROCESS_ARGV.set(tuple(argv))
            remaining_ns(attempt.deadline)
            failure_code = 2
            process = subprocess.Popen(
                argv,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                close_fds=True,
                start_new_session=True,
            )
            failure_code = 3
            attempt.pid = process.pid
            attempt.phase = 1
            process.stdin = CapturedPipe(process.stdin)
            process.stdout = CapturedPipe(process.stdout)
            process.stderr = CapturedPipe(process.stderr)
            child = identity_of(process.pid)
            attempt.start = int(child["start_ticks"])
            attempt.boot = UUID(child["boot_id"]).bytes
            if identity_of(os.getpid()) != owner.owner_process:
                raise Blocked("ORIGINAL_OWNER_REFUSED")
            if source_digest() != owner.source_sha256:
                raise Blocked("SOURCE_REFUSED")
            failure_code = 9
            observe(
                {
                    "event": "child_started",
                    "pid": process.pid,
                    "start_ticks": child["start_ticks"],
                    "boot_id": child["boot_id"],
                    "argv": argv,
                    "pipe_capacities": [
                        fcntl.fcntl(stream.fileno(), fcntl.F_GETPIPE_SZ)
                        for stream in (process.stdin, process.stdout, process.stderr)
                    ],
                }
            )
            failure_code = 4
            frame = GRANT.pack(
                b"I0GRNT1\0",
                owner.owner_process["pid"],
                int(owner.owner_process["start_ticks"]),
                UUID(owner.owner_process["boot_id"]).bytes,
                process.pid,
                attempt.start,
                bytes.fromhex(owner.source_sha256),
                custody_digest(owner),
                attempt.number,
                secrets.token_bytes(32),
                attempt.action,
                attempt.deadline,
            )
            attempt.digest = hashlib.sha256(frame).digest()
            remaining_ns(attempt.deadline)
            failure_code = 6
            try:
                stdout, stderr = granted_transport(process, frame, attempt)
                process.wait(timeout=remaining_ns(attempt.deadline))
            except (subprocess.TimeoutExpired, TimeoutError):
                timed_out = True
                owner.revoke_work(code=10)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    # A child can already have exited at its own original D.
                    timed_out = True
                process.wait(timeout=2)
            attempt.phase = 3
            failure_code = 9
            observe(
                {
                    "event": "child_reaped",
                    "pid": process.pid,
                    "start_ticks": child["start_ticks"],
                    "boot_id": child["boot_id"],
                    "reaped": process.returncode is not None,
                    "code": process.returncode,
                    "timed_out": timed_out,
                }
            )
        except BaseException as primary:
            owner.revoke_work(primary, code=failure_code)
            raise
        finally:
            primary = sys.exception()
            secondary = None
            if process is not None:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except BaseException as error:
                        secondary = error
                    try:
                        process.wait(timeout=2)
                    except BaseException as error:
                        secondary = secondary or error
                attempt.exit_known = int(process.returncode is not None)
                if attempt.exit_known:
                    attempt.code = process.returncode
                for bit, stream in enumerate((process.stdin, process.stdout, process.stderr)):
                    try:
                        if not stream.closed:
                            stream.close()
                    except BaseException as error:
                        secondary = secondary or error
                    if stream.closed:
                        attempt.closed |= 1 << bit
                    else:
                        attempt.unknown |= 1 << bit
                if not attempt.exit_known or attempt.unknown:
                    owner.disposal_unconfirmed = True
                    secondary = secondary or Blocked("CHILD_DISPOSAL_UNCONFIRMED")
            if token is not None:
                try:
                    PROCESS_ARGV.reset(token)
                except BaseException as error:
                    secondary = secondary or error
            if secondary is not None:
                owner.revoke_work(
                    primary or secondary, code=11 if owner.disposal_unconfirmed else 7
                )
                if primary is None:
                    raise secondary
                primary.add_note("I0_PROCESS_RETIREMENT_SECONDARY")
        failure_code = 8
        diagnostic(stderr)
        result = Result(
            process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8"), timed_out
        )
        if not timed_out:
            remaining_ns(attempt.deadline)
        return result
    except BaseException as primary:
        owner.revoke_work(primary, code=failure_code)
        raise


def granted_transport(process, frame, attempt):
    buffers = [bytearray(), bytearray()]
    streams = [process.stdout, process.stderr]
    limits = [81920, 4096]
    readers = {stream.fileno(): index for index, stream in enumerate(streams)}
    input_fd = process.stdin.fileno()
    offset = 0
    for fd in (*readers, input_fd):
        os.set_blocking(fd, False)
    while readers or not process.stdin.closed:
        delay = (attempt.deadline - time.monotonic_ns()) / 1_000_000_000
        if delay <= 0:
            raise TimeoutError("PG_PROBE_FAILED")
        readable, writable, _ = select.select(
            list(readers),
            [] if process.stdin.closed else [input_fd],
            [],
            delay,
        )
        if time.monotonic_ns() >= attempt.deadline:
            raise TimeoutError("PG_PROBE_FAILED")
        if writable:
            offset += os.write(input_fd, memoryview(frame)[offset:])
            if offset == len(frame):
                process.stdin.close()
                attempt.phase = 2
        for fd in readable:
            index = readers[fd]
            remaining = limits[index] - len(buffers[index])
            chunk = os.read(fd, min(4096, remaining + 1))
            if len(chunk) > remaining:
                raise Blocked("CHILD_OUTPUT_LIMIT")
            if chunk:
                buffers[index].extend(chunk)
            else:
                del readers[fd]
    return bytes(buffers[0]), bytes(buffers[1])


class Docker:
    def __init__(self, directory, observe):
        self.directory = directory
        self.observe = observe
        self.executable = shutil.which("docker", path="/usr/bin:/bin")
        if not self.executable:
            raise Blocked("DOCKER_MISSING")

    def call(self, *args, timeout=10):
        return run_child(
            [self.executable, "--host", "unix:///var/run/docker.sock", *args],
            self.directory,
            timeout,
            self.observe,
        )


def admit(observed):
    """Validate the prerequisite snapshot before resource acquisition."""
    path = observed.get("socket", "")
    if (
        observed.get("image_id") != IMAGE_ID
        or observed.get("free_bytes", 0) < 1024**3
        or observed.get("daemon_free_bytes", 0) < 1024**3
        or observed.get("docker_ready") is not True
        or not path.startswith("/")
        or len(path.encode("utf-8")) > 80
        or any(c.isspace() or c in ",\x00" for c in path)
    ):
        raise Blocked("PREREQUISITE_REFUSED")


def work_operation(method):
    bootstrap = method.__name__ == "bootstrap"

    @wraps(method)
    def guarded(self, *args, **kwargs):
        self.check_work()
        failure_code = 1
        try:
            self.work_state = "PENDING"
            deadline = (
                time.monotonic_ns() + int(kwargs.get("timeout", 10) * 1_000_000_000)
                if method.__name__ == "probe"
                else 0
            )
            self._reserve(deadline)
            if (
                identity_of(os.getpid()) != self.owner_process
                or source_digest() != self.source_sha256
            ):
                raise Blocked("ORIGINAL_OWNER_BINDING_REFUSED")
            failure_code = 6
            result = method(self, *args, **kwargs)
            failure_code = 7
            self._settle()
            if self.attempt.deadline:
                remaining_ns(self.attempt.deadline)
            self.attempt = None
            if bootstrap:
                self.ready = True
            self.work_state = "ELIGIBLE"
            return result
        except BaseException as primary:
            self.revoke_work(primary, code=failure_code)
            try:
                self.note("work_revoked", primary=type(primary).__name__)
            except BaseException:
                primary.add_note("I0_WORK_JOURNAL_UNCONFIRMED")
            raise

    return guarded


class Harness:
    """One create transaction and one cleanup attempt, addressed by immutable ID."""

    def __init__(self, evidence_root, *, backend=None):
        self.work_state = "REVOKED"
        self.work_failed = False
        self.attempt = None
        self.sequence = 0
        self.disposal_unconfirmed = False
        self.state = "NEW"
        self.cleanup_deadline = None
        self.name = "aiddos-i0-" + secrets.token_hex(16)
        self.labels = {
            "aiddos.i0.invocation": secrets.token_hex(16),
            "aiddos.i0.owner": secrets.token_hex(32),
        }
        self.directory = Path(evidence_root).resolve() / self.name
        self.directory.mkdir(parents=True, mode=0o700)
        self.journal = self.directory / "journal.jsonl"
        self.cidfile = self.directory / "container.cid"
        self.socket = Path(tempfile.mkdtemp(prefix="i0-")) / "s"
        self.socket.mkdir(mode=0o777)
        self.socket.chmod(0o777)
        self.cid = None
        self.volume = None
        self.receipt = None
        self.ready = False

        self.backend = (
            backend
            if backend is not None
            else Docker(self.directory, lambda event: self.note(**event))
        )
        try:
            self.owner_process = process_identity()
            self.source_sha256 = source_digest()
            self.note(
                "initialized",
                name=self.name,
                labels=self.labels,
                socket=str(self.socket),
                owner_process=self.owner_process,
                backend_kind="docker" if isinstance(self.backend, Docker) else "model",
                source_sha256=self.source_sha256,
            )
        except BaseException as primary:
            self.revoke_work(primary)
            raise

    def check_work(self):
        if (
            self.work_failed
            or getattr(self, "work_state", None) != "ELIGIBLE"
            or self.cleanup_deadline is not None
            or self.state != "OWNED"
        ):
            raise Blocked("WORK_REVOKED_EXPLICIT_RECOVERY_REQUIRED")

    def revoke_work(self, primary=None, *, code=6):
        self.work_state = "REVOKED"
        self.work_failed = True
        if self.attempt is not None:
            self.attempt.phase = 6 if self.disposal_unconfirmed else 5
            if not self.attempt.failure:
                self.attempt.failure = code

    def _reserve(self, deadline=0):
        if self.sequence >= UINT64:
            raise Blocked("ATTEMPT_SEQUENCE_EXHAUSTED")
        self.sequence += 1
        self.attempt = Attempt(self.sequence, deadline=deadline)

    def _settle(self):
        if self.work_state != "PENDING" or self.work_failed or self.disposal_unconfirmed:
            raise Blocked("WORK_REVOKED_EXPLICIT_RECOVERY_REQUIRED")
        if self.attempt.deadline:
            remaining_ns(self.attempt.deadline)
        self.attempt.phase = 4

    def note(self, event, **data):
        try:
            self._append_note(event, **data)
        except BaseException as primary:
            self.revoke_work(primary, code=9)
            raise

    def _append_note(self, event, **data):
        record = {"event": event, "at_ns": time.time_ns(), **data}
        stream = self.journal.open("a", encoding="utf-8")
        try:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException as primary:
            try:
                stream.close()
            except BaseException:
                primary.add_note("I0_STREAM_CLOSE_SECONDARY")
            raise
        else:
            stream.close()
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        except BaseException as primary:
            try:
                os.close(descriptor)
            except BaseException:
                primary.add_note("I0_DIRECTORY_CLOSE_SECONDARY")
            raise
        else:
            os.close(descriptor)

    def remaining(self, maximum):
        if self.cleanup_deadline is None:
            return maximum
        remaining = self.cleanup_deadline - time.monotonic()
        if remaining <= 0:
            raise Blocked("CLEANUP_DEADLINE")
        return min(maximum, remaining)

    def call(self, *args, timeout=10):
        result = self.backend.call(*args, timeout=self.remaining(timeout))
        self.note("docker_result", args=args, **asdict(result))
        if result.code or result.timed_out:
            raise Blocked("DOCKER_COMMAND_UNCONFIRMED")
        return result.stdout

    def metadata(self):
        return json.loads(self.call("container", "inspect", self.cid, "--format", CONTAINER_FORMAT))

    def volume_metadata(self):
        return json.loads(
            self.call("volume", "inspect", self.volume["Name"], "--format", VOLUME_FORMAT)
        )

    def attachments(self):
        return self.call(
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            "volume=" + self.volume["Name"],
            "--format",
            "{{.ID}}",
        ).split()

    def create(self):
        if self.state != "NEW":
            raise Blocked("NO_REPEATED_CREATION")
        try:
            ready = bool(self.call("version", "--format", "{{json .Server.Version}}"))
            image = json.loads(self.call("image", "inspect", IMAGE, "--format", "{{json .Id}}"))
            daemon_root = json.loads(self.call("info", "--format", "{{json .DockerRootDir}}"))
            observed = {
                "docker_ready": ready,
                "image_id": image,
                "daemon_free_bytes": shutil.disk_usage(daemon_root).free,
                "daemon_root": daemon_root,
                "free_bytes": shutil.disk_usage(self.socket).free,
                "socket": str(self.socket),
            }
            self.note("preflight", **observed)
            admit(observed)
            if self.call(
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                "name=^/" + self.name + "$",
                "--format",
                "{{.ID}}",
            ).strip():
                self.state = "COLLISION"
                raise Blocked("NAME_COLLISION")
            args = ["create", "--pull=never", "--name", self.name, "--cidfile", str(self.cidfile)]
            for key, value in self.labels.items():
                args += ["--label", key + "=" + value]
            args += [
                "--network",
                "none",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--cpus",
                "2",
                "--log-driver",
                "json-file",
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=2",
                "--mount",
                f"type=bind,src={self.socket},dst=/socket",
                "--mount",
                "type=volume,dst=/var/lib/postgresql/data",
                "--env",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "--entrypoint",
                "/bin/bash",
                IMAGE,
                *CONTAINER_COMMAND,
            ]
            self.state = "PENDING"
            pending_second = int(time.time())
            self.note("create_pending", args=args, pending_second=pending_second)
            result = self.backend.call(*args, timeout=20)
            # Persist returned immutable ID/status BEFORE any metadata lookup.
            self.note("create_result", **asdict(result))
            self.receipt = asdict(result)
            cid = result.stdout.strip()
            if (
                result.code
                or result.timed_out
                or not re.fullmatch(r"[0-9a-f]{64}", cid)
                or not self.cidfile.is_file()
                or self.cidfile.read_text().strip() != cid
            ):
                raise Blocked("CREATE_CUSTODY_UNCONFIRMED")
            self.cid = cid
            metadata = self.metadata()
            self.created = metadata.get("Created")
            mounts = metadata.get("Mounts", [])
            volumes = [m for m in mounts if m.get("Type") == "volume"]
            if len(volumes) != 1 or not re.fullmatch(r"[0-9a-f]{64}", volumes[0].get("Name", "")):
                raise Blocked("VOLUME_CUSTODY_UNCONFIRMED")
            self.volume = {"Name": volumes[0]["Name"]}
            self.volume = self.volume_metadata()
            self.note("volume_observed", volume=self.volume, mounts=mounts)
            for value in (self.created, self.volume["CreatedAt"]):
                stamp = datetime.fromisoformat(value)
                if stamp.tzinfo is None or not pending_second <= stamp.timestamp() <= time.time():
                    raise Blocked("RESOURCE_FRESHNESS_UNCONFIRMED")
            self.validate(metadata)
            if self.attachments() != [self.cid]:
                raise Blocked("VOLUME_ATTACHMENT_MISMATCH")
            self.note("registered", cid=self.cid, volume=self.volume, metadata=metadata)
            self.state = "OWNED"
            self.work_state = "ELIGIBLE"
            return self
        except BaseException as primary:
            self.block("create", primary)
            raise

    def validate(self, metadata):
        if (
            metadata.get("Id") != self.cid
            or metadata.get("Name") != "/" + self.name
            or not self.created
            or metadata.get("Created") != self.created
            or metadata.get("Labels") != self.labels
            or metadata.get("Image") != IMAGE_ID
        ):
            raise Blocked("IDENTITY_MISMATCH")
        expected = {
            "NetworkMode": "none",
            "Memory": 512 * 1024**2,
            "PidsLimit": 128,
            "NanoCpus": 2_000_000_000,
            "Cmd": list(CONTAINER_COMMAND),
            "Entrypoint": ["/bin/bash"],
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "2"}},
        }
        if any(metadata.get(k) != v for k, v in expected.items()) or metadata.get("PortBindings"):
            raise Blocked("ISOLATION_MISMATCH")
        mounts = metadata.get("Mounts", [])
        binds = [m for m in mounts if m.get("Type") == "bind"]
        volumes = [m for m in mounts if m.get("Type") == "volume"]
        if (
            len(mounts) != 2
            or len(binds) != 1
            or len(volumes) != 1
            or binds[0].get("Source") != str(self.socket)
            or binds[0].get("Destination") != "/socket"
            or binds[0].get("RW") is not True
            or volumes[0].get("Name") != self.volume["Name"]
            or volumes[0].get("Destination") != "/var/lib/postgresql/data"
            or volumes[0].get("RW") is not True
            or not self.volume.get("CreatedAt")
        ):
            raise Blocked("MOUNT_MISMATCH")

    def revalidate(self):
        try:
            self._check_custody()
        except BaseException as primary:
            self.block("revalidation", primary)
            raise

    def block(self, phase, primary):
        self.revoke_work(primary, code=5)
        if self.state != "COLLISION":
            self.state = "BLOCKED"
        try:
            self.note("blocked", phase=phase, state=self.state)
        except BaseException:
            primary.add_note("I0_BLOCK_JOURNAL_UNCONFIRMED")

    def _check_custody(self):
        if self.state != "OWNED" or not self.receipt:
            raise Blocked("CUSTODY_UNCONFIRMED")
        events = [json.loads(line) for line in self.journal.read_text().splitlines()]
        receipts = [
            {k: event[k] for k in self.receipt}
            for event in events
            if event["event"] == "create_result"
        ]
        if (
            receipts != [self.receipt]
            or self.receipt["code"] != 0
            or self.receipt["timed_out"]
            or self.receipt["stdout"].strip() != self.cid
            or self.cidfile.read_text().strip() != self.cid
        ):
            raise Blocked("CREATE_RECEIPT_MISMATCH")
        self.validate(self.metadata())
        if self.volume_metadata() != self.volume or self.attachments() != [self.cid]:
            raise Blocked("VOLUME_CUSTODY_MISMATCH")
        self.note("revalidated", cid=self.cid, volume=self.volume)

    def __enter__(self):
        return self.create()

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        except BaseException as secondary:
            if exc is None:
                raise
            try:
                self.note(
                    "cleanup_secondary",
                    primary=type(exc).__name__,
                    secondary=type(secondary).__name__,
                )
            except BaseException:
                exc.add_note("I0_CLEANUP_JOURNAL_UNCONFIRMED")
        return False

    @work_operation
    def bootstrap(self):
        """Start and validate once; database/roles only, no application schema."""
        if self.ready:
            raise Blocked("NO_REPEATED_BOOTSTRAP")
        self.revalidate()
        self.call("start", self.cid)
        deadline = time.monotonic() + 15
        while self.call("exec", self.cid, "/bin/cat", "/proc/1/comm").strip() != "postgres":
            if time.monotonic() >= deadline:
                raise Blocked("PG_STARTUP_DEADLINE")
            time.sleep(0.1)
        self._probe("setup", timeout=25)
        self.note("ready", cid=self.cid, volume=self.volume)

    @work_operation
    def probe(self, action, *, timeout=10):
        return self._probe(action, timeout=timeout)

    def _probe(self, action, *, timeout=10):
        attempt = self.attempt
        if not attempt.deadline:
            attempt.deadline = time.monotonic_ns() + int(timeout * 1_000_000_000)
        if action not in {"setup", "write", "read"}:
            raise Blocked("PROBE_ACTION_REFUSED")
        attempt.action = ACTIONS[action]
        self.revalidate()
        remaining_ns(attempt.deadline)
        result = run_child(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--pg-child",
                str(self.directory),
                "--action",
                action,
                "--i0-attempt",
                str(attempt.number),
                "--i0-deadline-ns",
                str(attempt.deadline),
            ],
            self.socket.parent,
            timeout,
            lambda event: self.note(**event),
            _grant=(self, attempt),
        )
        # Reject untrusted bytes before journal publication, including failed-child output.
        try:
            error_diagnostic = diagnostic(result.stderr.encode("utf-8"))
        except (Blocked, UnicodeError):
            self.revoke_work()
            raise Blocked("PG_PROBE_FAILED") from None
        if result.code or result.timed_out or error_diagnostic:
            self.revoke_work()
        self.note(
            "pg_child_exit",
            action=action,
            code=result.code,
            timed_out=result.timed_out,
            diagnostic=result.stderr,
        )
        if result.code or result.timed_out or error_diagnostic:
            raise Blocked("PG_PROBE_FAILED")
        if len(result.stdout) > 81920:
            raise Blocked("PROOF_LIMIT")
        try:
            proof = decode_proof(result.stdout.encode("utf-8"), attempt.digest.hex(), action)
        except BaseException as primary:
            self.revoke_work(primary, code=8)
            raise
        self.note("pg_proof", action=action, proof=proof)
        return proof

    @work_operation
    def restart(self):
        self.attempt.action = 4
        self.revalidate()
        self.call("stop", "--timeout", "2", self.cid, timeout=5)
        self.revalidate()
        self.call("start", self.cid)
        self.note("restarted", cid=self.cid, volume=self.volume)

    @work_operation
    def _admit_connection(self, action, connector, *args, **kwargs):
        self.attempt.action = action
        if action not in {5, 6, 7} or not self.ready:
            raise Blocked("LOCAL_ADMISSION_REFUSED")
        self.revalidate()
        return connector(*args, **kwargs)

    def close(self):
        self.revoke_work()
        if self.state in {"NEW", "CLEAN", "COLLISION"}:
            return
        if self.state != "OWNED":
            raise Blocked("CLEANUP_CUSTODY_UNCONFIRMED")
        if self.disposal_unconfirmed:
            raise Blocked("CHILD_DISPOSAL_UNCONFIRMED")
        self.cleanup_deadline = time.monotonic() + 30
        try:
            self.revalidate()
            self.call("stop", "--timeout", "2", self.cid, timeout=5)
            self.revalidate()
            self.call("rm", self.cid)
            absent = self.call(
                "ps", "-a", "--no-trunc", "--filter", "id=" + self.cid, "--format", "{{.ID}}"
            )
            if absent.strip():
                raise Blocked("CONTAINER_ABSENCE_UNCONFIRMED")
            self.note("container_absent", cid=self.cid)
            if self.volume_metadata() != self.volume or self.attachments():
                raise Blocked("VOLUME_CUSTODY_MISMATCH")
            self.call("volume", "rm", self.volume["Name"])
            result = self.backend.call(
                "volume",
                "inspect",
                self.volume["Name"],
                "--format",
                VOLUME_FORMAT,
                timeout=self.remaining(10),
            )
            self.note("volume_absence_readback", **asdict(result), volume=self.volume)
            expected = f"Error response from daemon: get {self.volume['Name']}: no such volume"
            if (
                result.code != 1
                or result.stdout.strip()
                or result.timed_out
                or result.stderr.strip() != expected
            ):
                raise Blocked("VOLUME_ABSENCE_UNCONFIRMED")
            self.state = "CLEAN"
            self.note("clean", cid=self.cid, volume=self.volume)
        except BaseException as primary:
            self.block("cleanup", primary)
            raise


class CustodyInspector:
    """Read-only resource inspector, with no original-owner work capability."""

    call = Harness.call
    metadata = Harness.metadata
    volume_metadata = Harness.volume_metadata
    attachments = Harness.attachments
    validate = Harness.validate
    _check_custody = Harness._check_custody
    _append_note = Harness._append_note

    def note(self, event, **data):
        self._append_note(event, **data)

    def remaining(self, maximum):
        return min(maximum, remaining_ns(self.deadline))


def borrowed_socket(directory, *, _attempt=None):
    if _attempt is None:
        raise Blocked("ENDPOINT_HANDOFF_REFUSED")
    _attempt.checkpoint()
    if Path(directory).resolve() != _attempt.directory or not _attempt.consumed:
        raise Blocked("ENDPOINT_HANDOFF_REFUSED")
    inspector = _borrowed_socket(_attempt.directory, _attempt.deadline)
    if custody_digest(inspector) != _attempt.custody:
        raise Blocked("CUSTODY_COMMITMENT_REFUSED")
    inspector._check_custody()
    _attempt.checkpoint()
    return inspector.socket


def _borrowed_socket(directory, deadline):
    with close_once((directory / "journal.jsonl").open()) as stream:
        events = [json.loads(line) for line in stream.read().splitlines()]
    first = events[0]
    registered = [event for event in events if event["event"] == "registered"]
    receipts = [event for event in events if event["event"] == "create_result"]
    if (
        len(registered) != 1
        or len(receipts) != 1
        or any(
            event["event"] in {"blocked", "clean", "container_absent", "work_revoked"}
            for event in events
        )
        or first["source_sha256"] != source_digest()
    ):
        raise Blocked("ENDPOINT_HANDOFF_REFUSED")
    identity = first["owner_process"]
    try:
        process = Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(")", 1)[1].split()
        alive = (
            process[0] not in {"Z", "X"}
            and process[19] == identity["start_ticks"]
            and Path("/proc/sys/kernel/random/boot_id").read_text().strip() == identity["boot_id"]
        )
    except OSError:
        alive = False
    if not alive:
        raise Blocked("ENDPOINT_OWNER_NOT_LIVE")
    registered, receipt = registered[0], receipts[0]
    owner = CustodyInspector()
    owner.owner_process = first["owner_process"]
    owner.source_sha256 = first["source_sha256"]
    owner.deadline = deadline
    owner.directory = directory
    owner.journal = directory / "journal.jsonl"
    owner.cidfile = directory / "container.cid"
    owner.socket = Path(first["socket"])
    owner.name = first["name"]
    owner.labels = first["labels"]
    owner.cid = registered["cid"]
    owner.created = registered["metadata"]["Created"]
    owner.volume = registered["volume"]
    owner.receipt = {key: receipt[key] for key in ("code", "stdout", "stderr", "timed_out")}
    owner.state = "OWNED"
    owner.cleanup_deadline = None

    owner.backend = Docker(directory, lambda event: owner.note(**event))

    if (
        owner.socket.is_symlink()
        or owner.socket.parent.is_symlink()
        or stat.S_IMODE(owner.socket.parent.stat().st_mode) != 0o700
        or stat.S_IMODE(owner.socket.stat().st_mode) != 0o777
        or owner.socket.parent.stat().st_uid != os.getuid()
    ):
        raise Blocked("SOCKET_CUSTODY_REFUSED")
    remaining_ns(deadline)
    return owner


def connection_parameters(endpoint, *, user="aiddos_s02", database="aiddos_s02"):
    """No ambient libpq configuration or fallback credentials, including test callers."""
    if any(key.startswith("PG") for key in os.environ):
        raise Blocked("AMBIENT_PG_REFUSED")
    if user not in {"postgres", "aiddos_s02_owner", "aiddos_s02"} or database not in {
        "postgres",
        "aiddos_s02",
    }:
        raise Blocked("ROLE_REFUSED")
    return {
        "host": str(endpoint),
        "port": 5432,
        "dbname": database,
        "user": user,
        "passfile": "/dev/null",
        "client_encoding": "UTF8",
        "sslmode": "disable",
        "gssencmode": "disable",
        "connect_timeout": 2,
        "options": "-c statement_timeout=2000 -c lock_timeout=500 "
        "-c idle_in_transaction_session_timeout=2000 -c synchronous_commit=on",
    }


class ChildAttempt:
    """A consumed grant covers the entire one action, not a returned pathname."""

    def __init__(self, directory, action, number, deadline, frame):
        self.directory = Path(directory).resolve(strict=True)
        self.deadline = deadline
        self.action = action
        self.consumed = False
        fields = GRANT.unpack(frame)
        (
            magic,
            pid,
            start,
            boot,
            child,
            child_start,
            source,
            custody,
            sequence,
            nonce,
            code,
            limit,
        ) = fields
        self.owner_process = {
            "pid": pid,
            "start_ticks": str(start),
            "boot_id": str(UUID(bytes=boot)),
        }
        self.source = source
        self.custody = custody
        self.digest = hashlib.sha256(frame).hexdigest()
        identity = identity_of(os.getpid())
        if (
            magic != b"I0GRNT1\0"
            or child != os.getpid()
            or child_start != int(identity["start_ticks"])
            or UUID(identity["boot_id"]).bytes != boot
            or sequence != number
            or code != ACTIONS[action]
            or limit != deadline
        ):
            raise Blocked("GRANT_BINDING_REFUSED")
        self.checkpoint()

    def checkpoint(self):
        remaining_ns(self.deadline)
        if (
            os.getppid() != self.owner_process["pid"]
            or identity_of(os.getppid()) != self.owner_process
            or bytes.fromhex(source_digest()) != self.source
        ):
            raise Blocked("GRANT_IDENTITY_REFUSED")
        inspector = _borrowed_socket(self.directory, self.deadline)
        if (
            inspector.owner_process != self.owner_process
            or custody_digest(inspector) != self.custody
        ):
            raise Blocked("CUSTODY_COMMITMENT_REFUSED")
        remaining_ns(self.deadline)


def read_grant(number, deadline):
    if not stat.S_ISFIFO(os.fstat(0).st_mode):
        raise Blocked("GRANT_PIPE_REQUIRED")
    buffer = bytearray()
    os.set_blocking(0, False)
    while True:
        readable, _, _ = select.select([0], [], [], remaining_ns(deadline))
        remaining_ns(deadline)
        if readable:
            chunk = os.read(0, 162 - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > GRANT.size:
                raise Blocked("GRANT_SIZE_REFUSED")
    if len(buffer) != GRANT.size:
        raise Blocked("GRANT_SIZE_REFUSED")
    return bytes(buffer)


def canonical_uint64(value):
    if (
        not isinstance(value, str)
        or len(value) > 20
        or re.fullmatch(r"[1-9][0-9]*", value) is None
        or int(value) > UINT64
    ):
        raise Blocked("GRANT_ARGV_REFUSED")
    return int(value)


def pg_probe(directory, action, *, _attempt=None):
    if _attempt is None or _attempt.consumed or _attempt.action != action:
        raise Blocked("GRANT_REQUIRED")
    _attempt.consumed = True
    proof = _pg_probe(directory, action, _attempt)
    _attempt.checkpoint()
    return {"grant_sha256": _attempt.digest, "proof": proof}


def _pg_probe(directory, action, attempt):
    import psycopg

    endpoint = borrowed_socket(directory, _attempt=attempt)

    @contextmanager
    def connect(user="aiddos_s02", database="aiddos_s02"):
        deadline = time.monotonic() + 8
        while True:
            attempt.checkpoint()
            try:
                parameters = connection_parameters(endpoint, user=user, database=database)
                remaining_ns(attempt.deadline)
                connection = psycopg.connect(**parameters, autocommit=True)
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise Blocked("PG_READINESS_DEADLINE") from None
                remaining_ns(attempt.deadline)
                time.sleep(min(0.1, remaining_ns(attempt.deadline)))
            else:
                break
        with close_once(connection):
            attempt.checkpoint()
            yield connection
            attempt.checkpoint()
        attempt.checkpoint()

    def execute(connection, sql):
        attempt.checkpoint()
        result = connection.execute(sql)
        attempt.checkpoint()
        return result

    if action == "setup":
        with connect("postgres", "postgres") as admin:
            execute(
                admin,
                "CREATE ROLE aiddos_s02_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS",
            )
            execute(
                admin,
                "CREATE ROLE aiddos_s02 LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8",
            )
            execute(admin, "CREATE DATABASE aiddos_s02 OWNER aiddos_s02_owner")
            execute(admin, "REVOKE ALL ON DATABASE aiddos_s02 FROM PUBLIC")
            execute(admin, "GRANT CONNECT ON DATABASE aiddos_s02 TO aiddos_s02")
        with connect("aiddos_s02_owner") as owner:
            execute(owner, "REVOKE ALL ON SCHEMA public FROM PUBLIC")
    if action == "write":
        with connect("aiddos_s02_owner") as owner:
            execute(owner, "CREATE SCHEMA i0_harness_probe")
            execute(owner, "CREATE TABLE i0_harness_probe.marker (value text PRIMARY KEY)")
            execute(
                owner, "INSERT INTO i0_harness_probe.marker VALUES ('i0-probe-not-application')"
            )
            execute(owner, "GRANT USAGE ON SCHEMA i0_harness_probe TO aiddos_s02")
            execute(owner, "GRANT SELECT ON i0_harness_probe.marker TO aiddos_s02")
    with connect() as runtime:
        with socket.fromfd(runtime.fileno(), socket.AF_UNIX, socket.SOCK_STREAM) as wire:
            domain = wire.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN)
            peer = wire.getpeername()
        # getpeername reports the server's container-namespace bind name, not
        # the host bind-mount alias used in the explicit libpq host parameter.
        if domain != socket.AF_UNIX or peer != "/socket/.s.PGSQL.5432":
            raise Blocked("AF_UNIX_PEER_MISMATCH")
        identity = list(
            execute(
                runtime, "SELECT current_database(), current_user, inet_server_addr()"
            ).fetchone()
        )
        durability = [
            execute(runtime, "SHOW " + setting).fetchone()[0]
            for setting in ("fsync", "full_page_writes", "synchronous_commit")
        ]
        roles = list(
            execute(
                runtime,
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit "
                "FROM pg_roles WHERE rolname=current_user",
            ).fetchone()
        )
        major = runtime.info.server_version // 10000
        owner_flags = list(
            execute(
                runtime,
                "SELECT r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication "
                "FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba "
                "WHERE d.datname=current_database()",
            ).fetchone()
        )
        # Socket location is a restricted GUC: verify via the private admin
        # without granting pg_read_all_settings (or superuser) to runtime.
        with connect("postgres", "postgres") as admin:
            socket_settings = [
                execute(admin, "SHOW " + setting).fetchone()[0]
                for setting in (
                    "listen_addresses",
                    "unix_socket_directories",
                    "unix_socket_permissions",
                )
            ]
        if owner_flags != ["aiddos_s02_owner", False, False, False, False] or socket_settings != [
            "",
            "/socket",
            "0777",
        ]:
            raise Blocked("PG_OWNER_OR_SOCKET_REFUSED")
        if (
            major != 16
            or durability != ["on"] * 3
            or identity != ["aiddos_s02", "aiddos_s02", None]
            or roles != [False, False, False, False, 8]
        ):
            raise Blocked("PG_SETTINGS_REFUSED")
        denied = []
        for sql in (
            "CREATE SCHEMA i0_forbidden",
            "CREATE TABLE public.i0_forbidden (n int)",
            "CREATE TEMP TABLE i0_forbidden (n int)",
        ):
            try:
                execute(runtime, sql)
            except psycopg.errors.InsufficientPrivilege:
                denied.append(True)
            else:
                raise Blocked("RUNTIME_DDL_ALLOWED")
        if (
            execute(
                runtime, "SELECT count(*) FROM pg_namespace WHERE nspname='aiddos_runs_v1'"
            ).fetchone()[0]
            != 0
        ):
            raise Blocked("UNEXPECTED_APPLICATION_SCHEMA")
        value = (
            None
            if action == "setup"
            else execute(runtime, "SELECT value FROM i0_harness_probe.marker").fetchone()[0]
        )
        capped = None
        if action == "write":
            with ExitStack() as connections:
                for _ in range(7):
                    connections.enter_context(connect())
                attempt.checkpoint()
                try:
                    parameters = connection_parameters(endpoint)
                    remaining_ns(attempt.deadline)
                    extra = psycopg.connect(**parameters, autocommit=True)
                except psycopg.OperationalError as error:
                    # libpq startup failures arrive as OperationalError, not a
                    # result-bearing SQLSTATE subclass. Do not accept arbitrary
                    # connection failure as proof of the role cap; never log text.
                    if 'too many connections for role "aiddos_s02"' not in str(error):
                        raise
                    capped = True
                else:
                    with close_once(extra):
                        attempt.checkpoint()
                    raise Blocked("RUNTIME_CONNECTION_CAP_NOT_ENFORCED")
        return {
            "server_major": major,
            "durability": durability,
            "identity": identity,
            "owner": owner_flags,
            "socket_settings": socket_settings,
            "connection_cap_enforced": capped,
            "runtime": roles,
            "ddl_denied": len(denied) == 3,
            "value": value,
            "af_unix": True,
            "driver": psycopg.__version__,
            "module": psycopg.__file__,
            "interpreter": sys.executable,
            "prefix": sys.prefix,
            "app_schema_absent": True,
        }


class ProbeFailure(RuntimeError):
    """Fixed exercise failure, never an application job result."""


class Interrupted(RuntimeError):
    """Signal request observed at a safe owner checkpoint."""


def exercise(evidence_root, mode):
    received = []

    def receive(signum, frame):
        if not received:
            received.append(signum)

    previous = {
        sig: signal.signal(sig, receive) for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    }
    owner = None

    def checkpoint():
        if received:
            owner.note("interrupted", signal=received[0])
            raise Interrupted()

    try:
        owner = Harness(evidence_root)
        with owner:
            checkpoint()
            owner.bootstrap()
            checkpoint()
            before = owner.probe("write")
            checkpoint()
            if mode == "fail":
                owner.note("injected_failure", primary="I0_EXPECTED_FAILURE")
                raise ProbeFailure("I0_EXPECTED_FAILURE")
            if mode == "wait":
                owner.note("signal_ready")
                deadline = time.monotonic() + 15
                while not received and time.monotonic() < deadline:
                    time.sleep(0.02)
                checkpoint()
                raise Blocked("SIGNAL_EXERCISE_DEADLINE")
            owner.restart()
            checkpoint()
            after = owner.probe("read")
            if before["value"] != after["value"]:
                raise Blocked("RESTART_DATA_MISMATCH")
            checkpoint()
    except Interrupted:
        print(json.dumps({"primary": "SIGNAL", "signal": received[0], "cleanup": owner.state}))
        return 128 + received[0]
    except ProbeFailure:
        print(json.dumps({"primary": "I0_EXPECTED_FAILURE", "cleanup": owner.state}))
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "primary": type(error).__name__,
                    "cleanup": owner.state if owner else "NOT_CREATED",
                }
            )
        )
        return 78
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(
        json.dumps(
            {
                "outcome": "I0_EXERCISED",
                "cleanup": owner.state,
                "journal": str(owner.journal),
                "stage_acceptance": "OPEN",
            }
        )
    )
    return 128 + received[0] if received else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pg-child", type=Path)
    group.add_argument("--evidence", type=Path)
    parser.add_argument("--action", choices=("setup", "write", "read"), default="read")
    parser.add_argument("--i0-attempt")
    parser.add_argument("--i0-deadline-ns")
    parser.add_argument("--mode", choices=("smoke", "fail", "wait"), default="smoke")
    args = parser.parse_args()
    if args.evidence:
        return exercise(args.evidence, args.mode)
    try:
        number = canonical_uint64(args.i0_attempt)
        deadline = canonical_uint64(args.i0_deadline_ns)
        with close_once(sys.stdin.buffer):
            frame = read_grant(number, deadline)
            attempt = ChildAttempt(args.pg_child, args.action, number, deadline, frame)
            proof = pg_probe(args.pg_child, args.action, _attempt=attempt)
        encoded = encode_proof(proof, args.action).decode("utf-8")
        attempt.checkpoint()
        sys.stdout.write(encoded)
        sys.stdout.flush()
        attempt.checkpoint()
        return 0
    except Exception as error:
        # Validate finite metadata BEFORE encoding. No truncation or driver text.
        try:
            name = type(error).__name__
            if len(name) > 64:
                return 78
            sites = []
            trace = error.__traceback__
            while trace is not None:
                function = trace.tb_frame.f_code.co_name
                if len(sites) == 16 or len(function) > 64:
                    return 78
                sites.append([function, trace.tb_lineno])
                trace = trace.tb_next
            encoded = json.dumps({"blocked": name, "site": sites}) + "\n"
            diagnostic(encoded.encode("utf-8"))
            data = encoded.encode("utf-8")
            offset = 0
            while offset < len(data):
                written = os.write(2, memoryview(data)[offset:])
                if written <= 0:
                    return 78
                offset += written
        except Exception:
            # Publication failure cannot produce success or a raw traceback.
            return 78
        return 78


if __name__ == "__main__":
    sys.exit(main())
