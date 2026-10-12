"""I3-owned native API/PG/browser/worker exercise; no active services or shell.
Verifier-env instrumentation is explicit; not a whole-chain foreign-access certificate.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
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
    except FileNotFoundError:
        return None


def main():
    from tools import s02_harness as h

    config = json.loads(Path(sys.argv[1]).read_text())
    mode = sys.argv[2] if len(sys.argv) > 2 else "full"
    assert mode in {"full", "scoped"}
    assert config["root"] == str(ROOT)
    runtime = Path(config["runtime"])
    env = config["env"]
    assert env["HOME"] == str(runtime / "home")
    assert not any(k.startswith("PG") for k in env)
    assert Path(sys.prefix) == ROOT / ".venv"
    output = ROOT / "next-evidence" / "live" / ("probe-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    print(json.dumps({"output": str(output)}), flush=True)
    processes = []
    receipts = []
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

    def launch(name, argv, extra=None, pass_fds=()):
        stdout = (output / (name + ".stdout")).open("wb")
        stderr = (output / (name + ".stderr")).open("wb")
        try:
            p = subprocess.Popen(
                argv,
                cwd=ROOT,
                env=dict(env) | (extra or {}),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                pass_fds=pass_fds,
            )
        except BaseException:
            stdout.close()
            stderr.close()
            raise
        record = {
            "name": name,
            "argv": argv,
            "pid": p.pid,
            "start_ticks": identity(p.pid),
            "pass_fds": list(pass_fds),
            "environment": dict(env) | (extra or {}),
        }
        processes.append((p, stdout, stderr, record))
        durable(output / (name + ".native-start.json"), record)
        return p

    def ready(url, child):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("owned server exited before readiness")
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("owned server readiness deadline")

    def retire_all():
        for p, stdout, stderr, record in reversed(processes):
            graceful = p.poll() is not None
            if not graceful:
                os.killpg(p.pid, signal.SIGTERM)
            forced = False
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                forced = True
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=3)
            stdout.close()
            stderr.close()
            value = record | {
                "actual_exit": p.returncode,
                "forced": forced,
                "reaped": p.poll() is not None,
                "stdout_closed": stdout.closed,
                "stderr_closed": stderr.closed,
                "absent": identity(p.pid) is None,
            }
            receipts.append(value)
            durable(output / (record["name"] + ".native-end.json"), value)
        processes.clear()

    owner = h.Harness(output / "pg")
    failure = None
    try:
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
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
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
            ready(f"http://127.0.0.1:{port}/api/v1/health", api)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", config.get("authorized_web_port", 0)))
                web_port = reservation.getsockname()[1]
            assert web_port not in (5173, 5180)
            web_origin = f"http://127.0.0.1:{web_port}"
            assert (
                "target: process.env.VITE_API_PROXY_TARGET ??"
                in (ROOT / "web/vite.config.ts").read_text()
            )
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
            ready(web_origin, vite)
            with urllib.request.urlopen(web_origin + "/api/v1/offline-runs", timeout=2) as response:
                assert response.status == 200 and json.load(response)["total"] == 0
            test = launch(
                "chromium",
                [
                    "/usr/bin/node",
                    str(ROOT / "web/node_modules/playwright/cli.js"),
                    "test",
                    "--config",
                    str(ROOT / "next-evidence/playwright.config.ts"),
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
            assert json.loads(bytes(row[1])) == terminal["snapshot"]
            assert json.loads(bytes(row[2])) == terminal["result"]
            durable(
                output / "independent-pg-readback.json",
                {
                    "run_id": run_id,
                    "input_count": count,
                    "snapshot_matches_http": True,
                    "result_matches_http": True,
                    "request": json.loads(bytes(row[0])),
                },
            )
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    finally:
        retire_all()
        durable(
            output / "result.json",
            {
                "failure": failure,
                "pg_state": owner.state,
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
