"""Product-path test adapters. Synthetic output is never real SQL evidence."""

import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import s02_harness as h  # noqa: E402


def proof(action="read"):
    return {
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
        "driver": "synthetic-transport-fixture",
        "module": str(Path(__file__)),
        "interpreter": sys.executable,
        "prefix": sys.prefix,
        "app_schema_absent": True,
    }


@contextmanager
def launch(patch, owner, config, path):
    """Rebind only the executing child launcher; retain its REAL Result."""
    config_path = path / "probe-config.json"
    config_path.write_text(json.dumps(config))
    native_popen, native_run = h.subprocess.Popen, h.run_child
    results, children = [], []

    def spawn(argv, *args, **kwargs):
        if "--pg-child" not in argv:
            return native_popen(argv, *args, **kwargs)
        assert owner.work_state == "PENDING"
        substituted = [argv[0], str(Path(__file__).resolve()), str(config_path), *argv[2:]]
        token = h.PROCESS_ARGV.set(tuple(substituted))
        try:
            child = native_popen(substituted, *args, **kwargs)
        finally:
            h.PROCESS_ARGV.reset(token)
        children.append(child)
        return child

    def run(*args, **kwargs):
        result = native_run(*args, **kwargs)
        if kwargs.get("_grant") is not None:
            results.append(result)
        return result

    patch.setattr(h.subprocess, "Popen", spawn)
    patch.setattr(h, "run_child", run)
    yield results, children


def main():
    config_path = Path(sys.argv[1])
    config = json.loads(config_path.read_text())
    sys.argv = [h.__file__, *sys.argv[2:]]
    origin = {
        "source": h.__file__,
        "source_sha256": hashlib.sha256(Path(h.__file__).read_bytes()).hexdigest(),
        "python": sys.executable,
        "prefix": sys.prefix,
        "identity": h.process_identity(),
        "evidence_class": config.get("class", "synthetic-output-real-transport"),
        "fired": [],
    }
    if config.get("synthetic", True):

        def synthetic(directory, action, attempt):
            origin["fired"].append("synthetic-proof")
            return config.get("proof", proof(action))

        h._pg_probe = synthetic
    if config.get("fault") == "emfile":
        import resource

        original_identity = h.identity_of

        def exhausted_identity(pid):
            old = resource.getrlimit(resource.RLIMIT_NOFILE)
            held = []
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, old[1]))
            try:
                while True:
                    try:
                        held.append(os.open("/dev/null", os.O_RDONLY))
                    except OSError as error:
                        assert error.errno == 24
                        break
                try:
                    return original_identity(pid)
                except OSError as error:
                    origin["fired"].append("retained-identity-open")
                    origin["errno"] = error.errno
                    origin["synthetic_exception"] = False
                    raise
            finally:
                for fd in held:
                    os.close(fd)
                resource.setrlimit(resource.RLIMIT_NOFILE, old)

        h.identity_of = exhausted_identity
    if config.get("fault") == "outer-close":
        stream = sys.stdin

        class Outer:
            @property
            def buffer(self):
                return self

            def __getattr__(self, name):
                return getattr(stream, name)

            def close(self):
                stream.close()
                origin["fired"].append("outer-close-after-release")
                origin["outer_closed"] = stream.closed
                raise OSError("SYNTHETIC_OUTER_CLOSE_AFTER_RELEASE")

        sys.stdin = Outer()
    if config.get("fault") == "post-connect-expiry":
        import types

        import psycopg

        native_connect = psycopg.connect
        native_execute = psycopg.Connection.execute
        expired = False
        limit = int(sys.argv[sys.argv.index("--i0-deadline-ns") + 1])

        def connect(*args, **kwargs):
            nonlocal expired
            connection = native_connect(*args, **kwargs)
            origin["fired"].append("real-connect-return")
            expired = True
            h.time = types.SimpleNamespace(
                monotonic_ns=lambda: limit + 1,
                monotonic=h.time.monotonic,
                time=h.time.time,
                time_ns=h.time.time_ns,
                sleep=h.time.sleep,
            )
            return connection

        def execute(connection, *args, **kwargs):
            if expired:
                origin["late_sql_entries"] = origin.get("late_sql_entries", 0) + 1
            return native_execute(connection, *args, **kwargs)

        origin["late_sql_entries"] = 0
        psycopg.connect = connect
        psycopg.Connection.execute = execute
    if config.get("fault") in {"deep-error", "long-error-name"}:

        def failure(directory, action, attempt):
            origin["fired"].append(config["fault"])

            def recursive(depth):
                if depth:
                    return recursive(depth - 1)
                raise RuntimeError("PRIVATE_DRIVER_TEXT")

            if config["fault"] == "deep-error":
                recursive(20)
            raise type("E" * 65, (Exception,), {})("PRIVATE_DRIVER_TEXT")

        h._pg_probe = failure
    if config.get("fault") == "grant-read":
        native_read = os.read

        def read(fd, length):
            if fd == 0:
                origin["fired"].append("grant-read")
                raise OSError("PRIVATE_INPUT_READ_ERROR")
            return native_read(fd, length)

        h.os.read = read
    if config.get("fault") == "encode":

        def encode(*_args):
            origin["fired"].append("encode")
            raise MemoryError("PRIVATE_ENCODING_ERROR")

        h.encode_proof = encode
    if "stdout_size" in config:
        h.encode_proof = lambda *_: b"x" * config["stdout_size"]
    original_probe = h.pg_probe

    def emit(*args, **kwargs):
        if config.get("fault") == "parent-death":
            import select
            import signal

            parent = os.getppid()
            pidfd = os.pidfd_open(parent)
            try:
                kwargs["_attempt"].checkpoint()
                origin["fired"].append("verified-GO-before-parent-death")
                os.kill(parent, signal.SIGUSR1)
                assert select.select([pidfd], [], [], 2)[0]
                origin["fired"].append("parent-death-observed")
                kwargs["_attempt"].checkpoint()
            finally:
                os.close(pidfd)
        if config.get("fault") == "post-grant-barrier":
            import signal
            import time

            attempt = kwargs["_attempt"]
            attempt.checkpoint()
            origin["fired"].append("verified-grant-before-PG")
            origin["original_deadline"] = attempt.deadline
            origin["barrier_ns"] = time.monotonic_ns()
            config_path.with_name("barrier.json").write_text(json.dumps(origin))
            signal.pause()
            raise AssertionError("BARRIER_MUST_BE_KILLED")
        result = original_probe(*args, **kwargs)
        if config.get("fault") == "consume-twice":
            origin["fired"].append("consume-twice")
            original_probe(*args, **kwargs)
        data = bytes.fromhex(config.get("stderr_hex", ""))
        fragment = config.get("fragment", len(data) or 1)
        for offset in range(0, len(data), fragment):
            os.write(2, data[offset : offset + fragment])
        origin["fired"].append("output-emitted")
        return result

    h.pg_probe = emit
    try:
        code = h.main()
        code = config.get("exit", code) if code == 0 else code
        origin["exit"] = code
        return code
    finally:
        config_path.with_name("child-origin.json").write_text(json.dumps(origin, indent=2) + "\n")


def parent_death_supervisor(directory, phase):
    """Dedicated Linux subreaper; no foreign process or database is touched."""
    import ctypes
    import signal

    import pytest

    sys.path.insert(0, str(ROOT / "tests/runs"))
    from test_harness import ModelDocker

    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
    pid = os.fork()
    if pid == 0:
        signal.signal(signal.SIGUSR1, lambda *_: os._exit(73))
        owner = h.Harness(directory, backend=ModelDocker()).create()
        original = owner.note

        def note(event, **data):
            original(event, **data)
            if event == "child_started":
                (directory / "grandchild.json").write_text(json.dumps(data))
                if phase == "before-GO":
                    os._exit(73)

        owner.note = note
        with (
            pytest.MonkeyPatch.context() as patch,
            launch(
                patch,
                owner,
                {"fault": "parent-death" if phase == "after-GO" else "none"},
                directory,
            ),
        ):
            owner.probe("read")
        os._exit(99)
    parent_identity = h.identity_of(pid)
    waited, status = os.waitpid(pid, 0)
    assert waited == pid and os.waitstatus_to_exitcode(status) == 73
    child = json.loads((directory / "grandchild.json").read_text())
    # The subreaper inherited this exact descendant; wait without PID adoption.
    waited, status = os.waitpid(child["pid"], 0)
    assert waited == child["pid"]
    code = os.waitstatus_to_exitcode(status)
    origin = json.loads((directory / "child-origin.json").read_text())
    assert code == 78 and "synthetic-proof" not in origin["fired"]
    if phase == "after-GO":
        assert origin["fired"] == ["verified-GO-before-parent-death", "parent-death-observed"]
    else:
        assert not origin["fired"]
    row = {
        "phase": phase,
        "parent": parent_identity,
        "parent_exit": 73,
        "child": child,
        "child_exit": code,
        "origin": origin,
        "parent_absent": not Path(f"/proc/{pid}").exists(),
        "child_absent": not Path(f"/proc/{child['pid']}").exists(),
        "real_database": False,
        "rollback_claim": False,
    }
    (directory / "parent-death.json").write_text(json.dumps(row, indent=2))
    assert row["parent_absent"] and row["child_absent"]
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "--parent-death-supervisor":
        sys.exit(parent_death_supervisor(Path(sys.argv[2]), sys.argv[3]))
    sys.exit(main())
