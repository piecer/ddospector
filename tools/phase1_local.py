"""Human-supervised local OFFLINE workspace. Never delete retained operator data."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import signal
import socket
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import s02_harness as h  # noqa: E402
from tools.s02_web_probe import NativeChildren, durable, identity, ready  # noqa: E402


def check_location(path):
    """Require a short, literal, durable path, not an auto-pruned test directory."""
    transient = [
        Path("/tmp"),
        Path("/var/tmp"),
        Path(tempfile.gettempdir()).resolve(),
        Path.home() / ".hermes/cache",
    ]
    if (
        not path.is_absolute()
        or path.resolve() != path
        or len(str(path / "d/s").encode()) > 80
        or any(c.isspace() or c in ",\x00" for c in str(path))
        or any(path.is_relative_to(p) for p in transient)
    ):
        raise h.Blocked("DURABLE_SHORT_LITERAL_WORKSPACE_REQUIRED")
    if path.exists() and (
        path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700
    ):
        raise h.Blocked("PRIVATE_WORKSPACE_REQUIRED")


def clean_environment(workspace):
    if any(k.startswith("PG") for k in os.environ):
        raise h.Blocked("AMBIENT_PG_REFUSED")
    return h.child_environment(workspace / "home") | {
        "TMPDIR": str(workspace / "tmp"),
    }


def new_workspace(path):
    path.mkdir(mode=0o700)
    for name in ("home", "tmp", "sessions"):
        (path / name).mkdir(mode=0o700)


def save_state(workspace, state):
    pending = workspace / "workspace.json.pending"
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(state, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, workspace / "workspace.json")
    fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def socket_identity(path):
    result = []
    for directory, mode in ((path.parent, 0o700), (path, 0o777)):
        value = directory.lstat()
        if not stat.S_ISDIR(value.st_mode) or stat.S_IMODE(value.st_mode) != mode:
            raise h.Blocked("SOCKET_CUSTODY_REFUSED")
        if directory == path.parent and value.st_uid != os.getuid():
            raise h.Blocked("SOCKET_CUSTODY_REFUSED")
        result.append([value.st_dev, value.st_ino])
    return result


def retained_pg(workspace, state):
    """Explicit retained receipt loading, NOT the original live-owner work grant.

    Only read/validate/start/stop custody is restored. Bootstrap/restart/recovery
    capabilities are never reconstructed. Unknown receipt/state remains untouched.
    """
    directory = workspace / "pg"
    events = [json.loads(line) for line in (directory / "journal.jsonl").read_text().splitlines()]
    first = events[0]
    receipts = [e for e in events if e["event"] == "create_result"]
    registrations = [e for e in events if e["event"] == "registered"]
    refused = {"blocked", "clean", "container_absent", "work_revoked"}
    if (
        len(receipts) != 1
        or len(registrations) != 1
        or any(e["event"] in refused for e in events)
        or not any(e["event"] == "ready" for e in events)
        or first["event"] != "initialized"
        or first["backend_kind"] != "docker"
        or first["source_sha256"] != h.source_digest()
        or state["helper_sha256"] != h.source_digest()
        or state["root"] != str(ROOT)
        or state["format"] != 1
    ):
        raise h.Blocked("ORIGINAL_CREATE_RECEIPT_REQUIRED")
    receipt, registered = receipts[0], registrations[0]
    cid = registered["cid"]
    if (
        receipt["code"] != 0
        or receipt["timed_out"] is not False
        or not re.fullmatch(r"[0-9a-f]{64}", cid)
        or receipt["stdout"].strip() != cid
        or (directory / "container.cid").read_text().strip() != cid
    ):
        raise h.Blocked("ORIGINAL_CREATE_RECEIPT_REQUIRED")
    endpoint = workspace / "d/s"
    if first["socket"] != str(endpoint) or socket_identity(endpoint) != state["socket_identity"]:
        raise h.Blocked("SOCKET_CUSTODY_REFUSED")
    owner = h.CustodyInspector()
    owner.directory = directory
    owner.journal = directory / "journal.jsonl"
    owner.cidfile = directory / "container.cid"
    owner.socket = endpoint
    owner.name, owner.labels = first["name"], first["labels"]
    owner.cid, owner.created = cid, registered["metadata"]["Created"]
    owner.volume = registered["volume"]
    owner.receipt = {k: receipt[k] for k in ("code", "stdout", "stderr", "timed_out")}
    owner.state = "OWNED"
    owner.deadline = time.monotonic_ns() + 30_000_000_000
    owner.backend = h.Docker(directory, lambda event: owner.note(**event))
    owner._check_custody()
    return owner


def reserve_port(port):
    if port in (5173, 5180):
        raise h.Blocked("ACTIVE_ENDPOINT_FORBIDDEN")
    listener = socket.socket()
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        return listener
    except BaseException:
        listener.close()
        raise


@contextmanager
def locked(path, *, exclusive, wait=False):
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        value = os.fstat(fd)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != os.getuid()
            or stat.S_IMODE(value.st_mode) != 0o600
        ):
            raise h.Blocked("PRIVATE_LOCK_REQUIRED")
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(fd, mode | (0 if wait else fcntl.LOCK_NB))
        yield fd
    finally:
        os.close(fd)


def stop_pg(owner):
    owner._check_custody()
    owner.call("stop", "--timeout", "10", owner.cid, timeout=15)
    owner._check_custody()
    if owner.metadata()["Status"] != "exited":
        raise h.Blocked("PG_STOP_UNCONFIRMED_DATA_RETAINED")


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    commands = command.add_subparsers(dest="command", required=True)
    for verb in ("create", "open", "worker", "evaluate"):
        sub = commands.add_parser(verb)
        sub.add_argument("--workspace", type=Path, required=True)
        if verb == "create":
            sub.add_argument("--evidence", action="store_true",
                             help="Install evidence storage in this fresh workspace only")
        if verb in {"worker", "evaluate"}:
            sub.add_argument("--run-id" if verb == "worker" else "--evidence-id", required=True)
        else:
            sub.add_argument("--web-port", type=int, choices=(5175, 5182), default=5175)
    return command


class PersistentPG(h.Harness):
    """Same create/bootstrap custody protocol, with an explicitly retained socket.

    Do not enter the disposable Harness context manager or call its close().
    The constructor differs only in placement; work grants remain original-owner-only.
    """

    def __init__(self, workspace):
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
        self.directory = workspace / "pg"
        self.directory.mkdir(mode=0o700)
        self.journal = self.directory / "journal.jsonl"
        self.cidfile = self.directory / "container.cid"
        (workspace / "d").mkdir(mode=0o700)
        self.socket = workspace / "d/s"
        self.socket.mkdir(mode=0o777)
        self.socket.chmod(0o777)
        self.cid = self.volume = self.receipt = None
        self.ready = False
        self.backend = h.Docker(self.directory, lambda event: self.note(**event))
        self.owner_process = h.process_identity()
        self.source_sha256 = h.source_digest()
        self.note(
            "initialized",
            name=self.name,
            labels=self.labels,
            socket=str(self.socket),
            owner_process=self.owner_process,
            backend_kind="docker",
            source_sha256=self.source_sha256,
        )


def launch_servers(workspace, output, native, reservation):
    endpoint = str(workspace / "d/s")
    with reserve_port(0) as listener:
        port = listener.getsockname()[1]
        inode = os.fstat(listener.fileno()).st_ino
        api = native.launch(
            "api",
            [
                str(ROOT / ".venv/bin/python"),
                "-m",
                "uvicorn",
                "ddospector.api.app:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
            ],
            {
                "DDOSPECTOR_RUN_DB_SOCKET": endpoint,
                "DDOSPECTOR_UI_STATE_PATH": str(workspace / "draft.json"),
            },
            pass_fds=(listener.fileno(),),
        )
    api_origin = f"http://127.0.0.1:{port}"
    ready(
        api_origin + "/api/v1/health",
        api,
        start=native.known[api.pid]["start_ticks"],
        announcement=(output / "api.stderr", "Application startup complete."),
        expected_inode=inode,
        receipt=output / "api-binding.json",
    )
    web_port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{web_port}"
    reservation.close()
    web = native.launch(
        "web",
        [
            "/usr/bin/node",
            str(ROOT / "web/node_modules/vite/bin/vite.js"),
            str(ROOT / "web"),
            "--host",
            "127.0.0.1",
            "--port",
            str(web_port),
            "--strictPort",
        ],
        {"VITE_API_PROXY_TARGET": api_origin},
    )
    ready(
        origin,
        web,
        start=native.known[web.pid]["start_ticks"],
        announcement=(output / "web.stdout", origin),
        receipt=output / "web-binding.json",
    )
    durable(
        output / "proxy.json",
        {"origin": origin, "api_origin": api_origin, "api_pid": api.pid, "web_pid": web.pid},
    )
    return [api, web], origin


def wait_database(owner):
    import psycopg

    deadline = time.monotonic() + 15
    while True:
        try:
            with psycopg.connect(**h.connection_parameters(owner.socket), autocommit=True) as db:
                db.execute("SELECT 1").fetchone()
            return
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)  # Startup readiness only, never worker/job retry.


def session_output(workspace, kind):
    output = workspace / "sessions" / (kind + "-" + secrets.token_hex(8))
    output.mkdir(mode=0o700)
    return output


def serve(args, stopping):
    workspace = args.workspace
    with locked(workspace / "session.lock", exclusive=True):
        state = json.loads((workspace / "workspace.json").read_text())
        expected = "NEW" if args.command == "create" else "STOPPED"
        if state["phase"] != expected:
            raise h.Blocked("EXPLICIT_CLEAN_STOP_REQUIRED_NO_AUTOMATIC_REPAIR")
        with reserve_port(args.web_port) as reservation:
            output = session_output(workspace, args.command)
            native = NativeChildren(output, clean_environment(workspace))
            failure = None
            initialized = False
            started = False
            owner = None
            try:
                if args.command == "open":
                    owner = retained_pg(workspace, state)
                    if owner.metadata()["Status"] != "exited":
                        raise h.Blocked("RETAINED_CONTAINER_NOT_STOPPED")
                state.update(phase="STARTING", supervisor=h.process_identity(), session=str(output))
                save_state(workspace, state)
                if args.command == "create":
                    owner = PersistentPG(workspace)
                    state.update(
                        socket_identity=socket_identity(owner.socket),
                        helper_sha256=h.source_digest(),
                    )
                    save_state(workspace, state)
                    owner.create()
                    owner.bootstrap()
                    started = True
                    migration = native.launch(
                        "migration",
                        [str(ROOT / ".venv/bin/python"), "-m", "ddospector.runs.migrate"],
                        {"DDOSPECTOR_RUN_DB_SOCKET": str(owner.socket)},
                    )
                    if migration.wait(timeout=15) != 0:
                        raise h.Blocked("MIGRATION_FAILED_DATA_RETAINED")
                    if getattr(args, "evidence", False):
                        evidence = native.launch(
                            "evidence-migration",
                            [str(ROOT / ".venv/bin/python"), "-m", "ddospector.evidence.migrate"],
                            {"DDOSPECTOR_RUN_DB_SOCKET": str(owner.socket)},
                        )
                        if evidence.wait(timeout=15) != 0:
                            raise h.Blocked("EVIDENCE_MIGRATION_FAILED_DATA_RETAINED")
                else:
                    owner.call("start", owner.cid)
                    started = True
                    wait_database(owner)
                children, origin = launch_servers(workspace, output, native, reservation)
                state.update(phase="RUNNING", origin=origin)
                save_state(workspace, state)
                initialized = True
                print(
                    json.dumps(
                        {
                            "phase": "RUNNING",
                            "workspace": str(workspace),
                            "origin": origin,
                            "session": str(output),
                            "worker": "explicit CLI only; no daemon",
                        }
                    ),
                    flush=True,
                )
                while not stopping():
                    native.discover()
                    if any(p.poll() is not None for p in children):
                        raise h.Blocked("SERVICE_EXITED_NO_RESTART_DATA_RETAINED")
                    time.sleep(0.1)
            except BaseException as error:
                failure = error
            finally:
                try:
                    state["phase"] = "STOPPING"
                    save_state(workspace, state)
                    # New wrappers see STOPPING; existing borrowers finish before PG stops.
                    with locked(workspace / "activity.lock", exclusive=True, wait=True):
                        native.retire_all()
                        if started:
                            stop_pg(retained_pg(workspace, state))
                    state["phase"] = "STOPPED" if initialized and failure is None else "BLOCKED"
                    save_state(workspace, state)
                except BaseException as cleanup:
                    if failure is not None:
                        failure.add_note("cleanup: " + repr(cleanup))
                    else:
                        failure = cleanup
                durable(
                    output / "lifecycle.json",
                    {
                        "phase": state["phase"],
                        "failure": repr(failure) if failure else None,
                        "data_preserved": True,
                        "container_removed": False,
                        "volume_removed": False,
                    },
                )
            if failure is not None:
                raise failure
            print("STOPPED: database, drafts and receipts retained; use explicit open.", flush=True)
            return 0


def worker(args, stopping):
    workspace = args.workspace
    evaluating = getattr(args, "command", "worker") == "evaluate"
    kind = "evaluate" if evaluating else "worker"
    selected = args.evidence_id if evaluating else args.run_id
    with locked(workspace / "activity.lock", exclusive=False):
        state = json.loads((workspace / "workspace.json").read_text())
        supervisor = state.get("supervisor", {})
        if (
            state["phase"] != "RUNNING"
            or supervisor.get("boot_id") != h.process_identity()["boot_id"]
            or identity(supervisor.get("pid", 0)) != supervisor.get("start_ticks")
        ):
            raise h.Blocked("LIVE_WORKSPACE_REQUIRED_NO_AUTOMATIC_REPAIR")
        owner = retained_pg(workspace, state)
        if owner.metadata()["Status"] != "running":
            raise h.Blocked("OWNED_DATABASE_NOT_RUNNING")
        output = session_output(workspace, kind)
        native = NativeChildren(output, clean_environment(workspace))
        try:
            child = native.launch(
                kind,
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "ddospector.evidence.evaluate" if evaluating else "ddospector.runs.worker",
                    "--evidence-id" if evaluating else "--run-id",
                    selected,
                ],
                {"DDOSPECTOR_RUN_DB_SOCKET": str(owner.socket)},
            )
            while child.poll() is None:
                if stopping():
                    return 130
                native.discover()
                time.sleep(0.05)
            code = child.wait()
            print(
                json.dumps(
                    {
                        "worker_exit": code,
                        "evidence_id" if evaluating else "run_id": selected,
                        "evidence": str(output),
                        "result": "inspect actual UI/API",
                    }
                ),
                flush=True,
            )
            return code
        finally:
            native.retire_all()


def main():
    args = parser().parse_args()
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        if args.command in {"worker", "evaluate"} and not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            args.run_id if args.command == "worker" else args.evidence_id
        ):
            raise h.Blocked("EXACT_LOWERCASE_UUID4_REQUIRED")
        check_location(args.workspace)
        environment = clean_environment(args.workspace)
        os.environ.clear()
        os.environ.update(environment)
        os.umask(0o077)
        if args.command == "create":
            new_workspace(args.workspace)
            for name in ("session.lock", "activity.lock"):
                (args.workspace / name).touch(mode=0o600, exist_ok=False)
            save_state(args.workspace, {"format": 1, "root": str(ROOT), "phase": "NEW"})
        return (
            worker(args, lambda: stopped)
            if args.command in {"worker", "evaluate"}
            else serve(args, lambda: stopped)
        )
    except Exception as error:
        print(f"REFUSED: {error!r}; retained data is never purged or repaired.", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
