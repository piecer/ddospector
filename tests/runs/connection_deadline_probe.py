"""Actual monotonic helper-return boundary; never a replacement clock or driver."""

import hashlib
import json
import os
import select
import signal
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import s02_harness as h  # noqa: E402


def identity(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {
        "pid": pid,
        "start_ticks": fields[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "state": fields[0],
    }


def same_process(actual, expected):
    return all(actual[key] == expected[key] for key in ("pid", "start_ticks", "boot_id"))


def main():
    output, expected_sha, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    args = sys.argv[4:]
    assert mode in {"origin-only", "control", "late-parameters", "control-cap", "late-cap"}
    source = Path(h.__file__)
    assert source == ROOT / "tools/s02_harness.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_sha
    assert Path(sys.prefix) == ROOT / ".venv"
    assert Path(psycopg.__file__).is_relative_to(Path(sys.prefix))
    assert output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "inputs")
    row = {
        "source": str(source),
        "source_sha256": expected_sha,
        "helper": str(Path(__file__).resolve()),
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "interpreter": sys.executable,
        "prefix": sys.prefix,
        "cwd": str(Path.cwd()),
        "TMPDIR": os.environ["TMPDIR"],
        "HOME": os.environ["HOME"],
        "output": str(output),
        "driver_path": psycopg.__file__,
        "driver_version": psycopg.__version__,
        "libpq": psycopg.pq.version(),
        "identity": identity(os.getpid()),
        "parent": identity(os.getppid()),
        "mode": mode,
        "parameters": [],
        "connects": [],
        "connections": [],
        "sql": [],
        "clock": "unmodified-time.monotonic_ns",
    }
    if mode == "origin-only":
        output.write_text(json.dumps(row, indent=2) + "\n")
        return 0
    sys.argv = [h.__file__, *args]
    deadline = int(args[args.index("--i0-deadline-ns") + 1])
    row["original_deadline"] = deadline
    original_parameters = h.connection_parameters
    original_connect = psycopg.connect
    original_execute = psycopg.Connection.execute
    saved = []
    paused = False
    read_fd = write_fd = None

    def parameters(*a, **kwargs):
        nonlocal paused, read_fd, write_fd
        entered = time.monotonic_ns()
        value = original_parameters(*a, **kwargs)
        caller = sys._getframe(1).f_code
        event = {
            "entered_ns": entered,
            "caller": caller.co_name,
            "caller_file": caller.co_filename,
            "returned_production_mapping": True,
            "mapping_sha256": hashlib.sha256(
                json.dumps(value, sort_keys=True).encode()
            ).hexdigest(),
        }
        row["parameters"].append(event)
        target_boundary = (
            mode == "late-parameters" and len(row["parameters"]) == 1
        ) or (mode == "late-cap" and caller is h._pg_probe.__code__)
        if target_boundary:
            assert not paused
            assert caller.co_filename == h.__file__
            assert caller.co_name == ("_pg_probe" if mode == "late-cap" else "connect")
            assert entered < deadline
            read_fd, write_fd = os.pipe()
            parent = identity(os.getppid())
            assert same_process(parent, row["parent"])
            paused = True
            os.kill(parent["pid"], signal.SIGSTOP)
            # An unresolved helper-return barrier, not a sleep/race assertion.
            target = deadline + 5_000_000
            while time.monotonic_ns() < target:
                assert not select.select(
                    [read_fd], [], [], max(0, (target - time.monotonic_ns()) / 1e9)
                )[0]
            event["parent_state_after_barrier"] = identity(parent["pid"])["state"]
            assert event["parent_state_after_barrier"] == "T"
            event["delay_fired"] = True
        event["return_ns"] = time.monotonic_ns()
        return value

    def connect(*a, **kwargs):
        entered = time.monotonic_ns()
        event = {
            "entry_ns": entered,
            "after_original_D": entered >= deadline,
            "user": kwargs["user"],
            "host": kwargs["host"],
            "returned_real_connection": False,
        }
        row["connects"].append(event)
        try:
            connection = original_connect(*a, **kwargs)
        except psycopg.OperationalError as error:
            event["native_refusal"] = type(error).__name__
            event["role_cap_refusal"] = (
                'too many connections for role "aiddos_s02"' in str(error)
            )
            raise
        saved.append(connection)
        event["returned_real_connection"] = True
        event["server_major"] = connection.info.server_version // 10000
        return connection

    def execute(connection, *a, **kwargs):
        entered = time.monotonic_ns()
        row["sql"].append({"entry_ns": entered, "after_original_D": entered >= deadline})
        return original_execute(connection, *a, **kwargs)

    h.connection_parameters = parameters
    psycopg.connect = connect
    psycopg.Connection.execute = execute
    try:
        code = h.main()
        row["actual_main_exit"] = code
        return code
    finally:
        try:
            row["connections"] = [{"closed_before_rescue": c.closed} for c in saved]
            row["saved_at_ns"] = time.monotonic_ns()
            output.write_text(json.dumps(row, indent=2) + "\n")
        finally:
            # Resume even if evidence publication or probe-FD retirement fails.
            try:
                if read_fd is not None:
                    os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)
            finally:
                if paused:
                    current = identity(row["parent"]["pid"])
                    assert same_process(current, row["parent"])
                    os.kill(current["pid"], signal.SIGCONT)


if __name__ == "__main__":
    sys.exit(main())
