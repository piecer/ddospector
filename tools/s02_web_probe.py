"""I3-owned native API/PG/browser/worker exercise; no active services or shell.
Verifier-env instrumentation is explicit; not a whole-chain foreign-access certificate.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def durable(path, value):
    with path.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def identity(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ESRCH):
            return None
        raise


def owned_listener(pid, port, start, expected_inode=None):
    """Match only this still-owned PID's descriptors to its listening TCP inode."""
    if identity(pid) != start:
        return None
    inodes = set()
    try:
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                target = os.readlink(fd)
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ESRCH):
                    continue
                raise
            if target.startswith("socket:["):
                inodes.add(target[8:-1])
        for line in Path(f"/proc/{pid}/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[9] not in inodes:
                continue
            if fields[1] == f"0100007F:{port:04X}" and fields[3] == "0A":
                inode = fields[9]
                if expected_inode is not None and inode != str(expected_inode):
                    continue
                if identity(pid) == start:
                    return inode
    except OSError as error:
        if error.errno not in (errno.ENOENT, errno.ESRCH):
            raise
    return None


def ready(url, child, *, start=None, announcement=None, expected_inode=None, receipt=None):
    if start is None or announcement is None:
        raise RuntimeError("owned listener binding proof required")
    port = urllib.parse.urlsplit(url).port
    if port in (5173, 5180):
        raise RuntimeError("active endpoint forbidden")
    log, marker = announcement
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if child.poll() is not None or identity(child.pid) != start:
            raise RuntimeError("owned server exited before binding/readiness")
        # Do not inspect transitional exec credentials before the child's own marker.
        if marker not in log.read_text():
            time.sleep(0.05)
            continue
        inode = owned_listener(child.pid, port, start, expected_inode)
        if inode is None:
            time.sleep(0.05)
            continue
        # Bind success and kernel descriptor ownership precede the first HTTP byte.
        if receipt is not None:
            durable(
                receipt,
                {
                    "url": url,
                    "pid": child.pid,
                    "start": start,
                    "inode": inode,
                    "announcement": marker,
                    "proven_before_http": True,
                },
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("owned server binding/readiness deadline")


class NativeChildren:
    """Exclusive subreaper custody; pidfds, never numeric-PID killpg cleanup."""

    def __init__(self, output, env):
        if self.children(os.getpid()):
            raise RuntimeError("native supervisor requires an exclusive child subtree")
        if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
            raise RuntimeError("subreaper unavailable")
        self.output, self.env = output, env
        self.boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.processes, self.receipts = [], []
        self.pumps = {}
        self.known, self.handles, self.origins = {}, {}, {}
        self.signals, self.reaped, self.errors = [], [], []
        self.sent = set()
        self.clean = False
        self.closed = False

    @staticmethod
    def children(pid):
        try:
            return [int(x) for x in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ESRCH):
                return []
            raise

    def discover(self):
        todo = self.children(os.getpid()) + list(self.known)
        seen = set()
        while todo:
            pid = todo.pop()
            if pid in seen:
                continue
            seen.add(pid)
            start = identity(pid)
            if start is None:
                continue
            if pid in self.known:
                if self.known[pid]["start_ticks"] != start:
                    continue
            else:
                try:
                    fd = os.pidfd_open(pid, 0)
                except OSError as error:
                    if error.errno in (errno.ENOENT, errno.ESRCH):
                        continue
                    raise
                if identity(pid) != start:
                    os.close(fd)
                    continue
                self.handles[pid] = fd
                self.known[pid] = {"pid": pid, "start_ticks": start, "boot_id": self.boot}
            if pid not in self.origins:
                try:
                    item = {
                        "exe": str(Path(f"/proc/{pid}/exe").resolve(strict=True)),
                        "cwd": str(Path(f"/proc/{pid}/cwd").resolve(strict=True)),
                        "argv": Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")[:-1],
                    }
                    if identity(pid) == start:
                        self.origins[pid] = item
                except OSError as error:
                    if error.errno not in (errno.ENOENT, errno.ESRCH):
                        raise
            todo.extend(self.children(pid))

    def pump(self, pipe, destination):
        try:
            while data := os.read(pipe.fileno(), 65536):
                destination.write(data)
                destination.flush()
        except BaseException:
            self.errors.append(traceback.format_exc())
        finally:
            pipe.close()

    def launch(self, name, argv, extra=None, pass_fds=()):
        if self.closed:
            raise RuntimeError("native owner retired")
        stdout = (self.output / (name + ".stdout")).open("xb")
        stderr = (self.output / (name + ".stderr")).open("xb")
        environment = dict(self.env) | (extra or {})
        record = {
            "name": name,
            "argv": argv,
            "cwd": str(ROOT),
            "environment": environment,
            "shell": False,
            "pass_fds": list(pass_fds),
            "boot_id": self.boot,
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        try:
            p = subprocess.Popen(
                argv,
                cwd=ROOT,
                env=environment,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                pass_fds=pass_fds,
            )
        except BaseException:
            stdout.close()
            stderr.close()
            durable(
                self.output / (name + ".spawn-failure.json"),
                record
                | {
                    "traceback": traceback.format_exc(),
                    "stdout_closed": stdout.closed,
                    "stderr_closed": stderr.closed,
                },
            )
            raise
        # Install custody before fallible identity/provenance publication.
        self.processes.append((p, stdout, stderr, record))
        self.pumps[p.pid] = []
        for pipe, destination in ((p.stdout, stdout), (p.stderr, stderr)):
            thread = threading.Thread(target=self.pump, args=(pipe, destination), daemon=True)
            self.pumps[p.pid].append((thread, pipe))
            thread.start()
        record.update(pid=p.pid, start_ticks=identity(p.pid))
        self.discover()
        if p.pid not in self.known:
            raise RuntimeError("native launch identity unconfirmed")
        durable(self.output / (name + ".native-start.json"), record)
        return p

    def gone(self, pid):
        return bool(select.select([self.handles[pid]], [], [], 0)[0])

    def send(self, pid, sig):
        if (pid, sig) in self.sent or self.gone(pid):
            return
        try:
            signal.pidfd_send_signal(self.handles[pid], sig, None, 0)
            self.sent.add((pid, sig))
            self.signals.append({"identity": self.known[pid], "signal": int(sig), "via": "pidfd"})
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH):
                raise

    def reap(self):
        roots = set()
        for p, _, _, _ in self.processes:
            roots.add(p.pid)
            p.poll()
        for pid, item in self.known.items():
            if pid in roots or identity(pid) != item["start_ticks"]:
                continue
            try:
                got, status = os.waitpid(pid, os.WNOHANG)
                if got:
                    self.reaped.append({"identity": item, "wait_status": status})
            except ChildProcessError:
                pass

    def retire_all(self):
        if self.closed:
            return
        start = time.monotonic()
        quiet = 0
        remaining = list(self.known.values())
        try:
            while time.monotonic() - start < 3:
                try:
                    self.discover()
                    self.reap()
                    for pid in list(self.known):
                        self.send(
                            pid,
                            signal.SIGKILL if time.monotonic() - start >= 1.2 else signal.SIGTERM,
                        )
                    roots_done = all(p.returncode is not None for p, _, _, _ in self.processes)
                    if (
                        roots_done
                        and not self.children(os.getpid())
                        and all(self.gone(pid) for pid in self.known)
                    ):
                        quiet += 1
                        if quiet == 2:
                            self.clean = True
                            break
                    else:
                        quiet = 0
                except BaseException:
                    self.errors.append(traceback.format_exc())
                    quiet = 0
                time.sleep(0.01)
            remaining = [
                item
                for pid, item in self.known.items()
                if not self.gone(pid) or identity(pid) == item["start_ticks"]
            ]
            self.clean = self.clean and not self.errors and not remaining
        finally:
            for p, stdout, stderr, record in self.processes:
                for thread, pipe in self.pumps.get(p.pid, []):
                    thread.join(timeout=max(0, 3 - (time.monotonic() - start)))
                    if thread.is_alive() or not pipe.closed:
                        self.errors.append("native log pipe retirement unconfirmed")
                for stream in (stdout, stderr):
                    try:
                        stream.close()
                    except BaseException:
                        self.errors.append(traceback.format_exc())
                value = record | {
                    "actual_exit": p.returncode,
                    "log_pipes_closed": all(pipe.closed for _, pipe in self.pumps.get(p.pid, [])),
                    "reaped": p.returncode is not None,
                    "forced": any(
                        s["identity"]["pid"] == p.pid and s["signal"] == 9 for s in self.signals
                    ),
                    "absent": identity(p.pid) != record["start_ticks"],
                    "stdout_closed": stdout.closed,
                    "stderr_closed": stderr.closed,
                }
                self.receipts.append(value)
                durable(self.output / (record["name"] + ".native-end.json"), value)
            for fd in self.handles.values():
                os.close(fd)
            self.closed = True
        self.clean = self.clean and not self.errors
        durable(
            self.output / "native-retirement.json",
            {
                "clean": self.clean,
                "remaining": remaining,
                "identities": list(self.known.values()),
                "origins": self.origins,
                "signals": self.signals,
                "reaped_descendants": self.reaped,
                "remaining_direct_children": self.children(os.getpid()),
                "errors": self.errors,
                "pidfds_closed": True,
            },
        )
        if not self.clean:
            raise RuntimeError("native retirement unconfirmed; evidence retained")


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    mode = sys.argv[2] if len(sys.argv) > 2 else "full"
    assert mode in {"full", "scoped"}
    port = config.get("authorized_web_port")
    if mode == "full" and (type(port) is not int or port not in (5175, 5182)):
        raise ValueError("full mode requires an explicit allowed test port (5175 or 5182)")
    if mode == "scoped" and port is not None:
        raise ValueError("scoped denial requires an unallowed ephemeral origin")
    assert config["root"] == str(ROOT)
    runtime = Path(config["runtime"])
    env = config["env"]
    assert env["HOME"] == str(runtime / "home")
    assert not any(k.startswith("PG") for k in env)
    assert Path(sys.prefix) == ROOT / ".venv"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", port if mode == "full" else 0))
        return exercise(config, mode, reservation)


def exercise(config, mode, reservation):
    from tools import s02_harness as h

    env = config["env"]
    web_port = reservation.getsockname()[1]
    if web_port in (5173, 5180) or (mode == "scoped" and web_port in (5175, 5182)):
        raise RuntimeError("reserved origin conflicts with scope")
    output = ROOT / "browser-evidence" / "live" / ("probe-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    print(json.dumps({"output": str(output)}), flush=True)
    # All harness-owned native children get this literal invocation-owned env.
    h.child_environment = lambda directory: dict(env)
    durable(
        output / "verifier-environment.json",
        {
            "env": env,
            "instrumentation": (
                "h.child_environment rebound for owned literal native launch; source unchanged"
            ),
            "scope": "not zero whole-chain foreign-access certification",
        },
    )

    native = NativeChildren(output, env)
    launch = native.launch
    retire_all = native.retire_all
    receipts = native.receipts

    owner = None
    failure = None
    try:
        owner = h.Harness(output / "pg")
        with owner, contextlib.ExitStack() as stack:
            stack.callback(retire_all)
            owner.bootstrap()
            owner.revalidate()
            migration = launch(
                "migration",
                [str(ROOT / ".venv/bin/python"), "-m", "aiddos.runs.migrate"],
                {"AIDDOS_RUN_DB_SOCKET": str(owner.socket)},
            )
            assert migration.wait(timeout=8) == 0
            durable(
                output / "owned-endpoint.json",
                {
                    "socket": str(owner.socket),
                    "cid": owner.cid,
                    "volume": owner.volume,
                    "journal": str(owner.journal),
                    "source_sha256": owner.source_sha256,
                },
            )
            python = str(ROOT / ".venv/bin/python")
            listener = stack.enter_context(socket.socket())
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            api_inode = os.fstat(listener.fileno()).st_ino
            assert port not in (5173, 5180)
            api = launch(
                "api",
                [
                    python,
                    "-m",
                    "uvicorn",
                    "aiddos.api.app:app",
                    "--fd",
                    str(listener.fileno()),
                    "--no-access-log",
                ],
                {
                    "AIDDOS_RUN_DB_SOCKET": str(owner.socket),
                    "AIDDOS_UI_STATE_PATH": str(output / "draft.json"),
                },
                (listener.fileno(),),
            )
            listener.close()
            ready(
                f"http://127.0.0.1:{port}/api/v1/health",
                api,
                start=native.known[api.pid]["start_ticks"],
                announcement=(output / "api.stderr", "Application startup complete."),
                expected_inode=api_inode,
                receipt=output / "api-binding.json",
            )
            assert web_port not in (5173, 5180)
            web_origin = f"http://127.0.0.1:{web_port}"
            assert (
                "target: process.env.VITE_API_PROXY_TARGET ??"
                in (ROOT / "web/vite.config.ts").read_text()
            )
            reservation.close()  # strictPort + kernel ownership closes the bind-race gate.
            vite = launch(
                "vite",
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
                {"VITE_API_PROXY_TARGET": f"http://127.0.0.1:{port}"},
            )
            assert native.processes[-1][3]["environment"]["VITE_API_PROXY_TARGET"] == f"http://127.0.0.1:{port}"
            durable(output / "proxy-binding.json", {
                "api_origin": f"http://127.0.0.1:{port}", "api_pid": api.pid,
                "api_start_ticks": native.known[api.pid]["start_ticks"], "api_inode": api_inode,
                "web_origin": web_origin, "vite_pid": vite.pid,
                "proxy": native.processes[-1][3]["environment"]["VITE_API_PROXY_TARGET"],
                "default_active_endpoint_used": False})
            ready(
                web_origin,
                vite,
                start=native.known[vite.pid]["start_ticks"],
                announcement=(output / "vite.stdout", web_origin),
                receipt=output / "vite-binding.json",
            )
            with urllib.request.urlopen(web_origin + "/api/v1/offline-runs", timeout=2) as response:
                assert response.status == 200 and json.load(response)["total"] == 0
            test = launch(
                "chromium",
                [
                    "/usr/bin/node",
                    str(ROOT / "web/node_modules/playwright/cli.js"),
                    "test",
                    "--config",
                    str(ROOT / "web/playwright.runs.config.ts"),
                    "--grep",
                    "owned ephemeral-origin|exact-byte"
                    if mode == "scoped"
                    else "real EN/KO|exact-byte",
                ],
                {"I3_WEB_ORIGIN": web_origin, "I3_WEB_OUTPUT": str(output)},
            )
            deadline = time.monotonic() + 90
            worker = None
            while test.poll() is None:
                native.discover()
                if time.monotonic() >= deadline:
                    raise RuntimeError("original browser process deadline")
                if (output / "start-worker").exists() and worker is None:
                    owner.revalidate()
                    worker = launch(
                        "worker",
                        [python, "-m", "aiddos.runs.worker"],
                        {"AIDDOS_RUN_DB_SOCKET": str(owner.socket)},
                    )
                if worker is not None and worker.poll() is not None:
                    raise RuntimeError("separate worker exited during browser exercise")
                time.sleep(0.02)
            assert test.wait(timeout=2) == 0, "actual Playwright failure retained"
            # Independently read THIS freshly owned PG; no backend fault injection.
            owner.revalidate()
            import psycopg

            completed = json.loads(
                (
                    output
                    / (
                        "ordinary-browser-verification.json"
                        if mode == "scoped"
                        else "browser-verification.json"
                    )
                ).read_text()
            )
            run_id = completed["queuedRun"] if mode == "scoped" else completed["terminalRunId"]
            with psycopg.connect(**h.connection_parameters(owner.socket), autocommit=True) as db:
                row = db.execute(
                    "SELECT i.request,i.snapshot,r.result FROM aiddos_runs_v1.inputs i "
                    "JOIN aiddos_runs_v1.results r USING(run_id) WHERE i.run_id=%s",
                    (run_id,),
                ).fetchone()
                count = db.execute("SELECT count(*) FROM aiddos_runs_v1.inputs").fetchone()[0]
            terminal = json.loads(
                (
                    output
                    / (
                        "ordinary-B-terminal.body"
                        if mode == "scoped"
                        else "actual-browser-terminal.body"
                    )
                ).read_bytes()
            )
            assert row and count == (1 if mode == "scoped" else 2)
            raw_hashes = {}
            for field, raw in zip(("request", "snapshot", "result"), row, strict=True):
                data = bytes(raw)
                (output / ("pg-" + field + ".body")).write_bytes(data)
                raw_hashes[field] = hashlib.sha256(data).hexdigest()
            assert json.loads(bytes(row[1])) == terminal["snapshot"]
            assert json.loads(bytes(row[2])) == terminal["result"]
            durable(
                output / "independent-pg-readback.json",
                {
                    "run_id": run_id,
                    "input_count": count,
                    "raw_sha256": raw_hashes,
                    "cid": owner.cid,
                    "socket": str(owner.socket),
                    "snapshot_matches_http": True,
                    "result_matches_http": True,
                    "request": json.loads(bytes(row[0])),
                },
            )
    except BaseException as error:
        failure = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    finally:
        try:
            retire_all()
        except BaseException as error:
            cleanup = {"type": type(error).__name__, "traceback": traceback.format_exc()}
            failure = failure or {"type": "CleanupFailure"}
            failure["native_cleanup"] = cleanup
        durable(
            output / "result.json",
            {
                "failure": failure,
                "pg_state": owner.state if owner else "NOT_CONSTRUCTED",
                "processes": receipts,
                "scope": mode + ": I3 earlier-source runtime proof, not final W2 source acceptance",
            },
        )
    if failure:
        print(json.dumps(failure), flush=True)
        return 1
    assert owner.state == "CLEAN"
    assert all(
        x["absent"] and x["reaped"] and x["stdout_closed"] and x["stderr_closed"] for x in receipts
    )
    print(
        json.dumps(
            {
                "outcome": "I3_SCOPED_ORDINARY_BROWSER_VERIFIED_BROWSER_CREATE_HOLD"
                if mode == "scoped"
                else "I3_BROWSER_CREATE_VERIFIED",
                "output": str(output),
                "pg_state": owner.state,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
