#!/usr/bin/env python3
"""Source-bound CHAT-01 acceptance. Default preflight sends ZERO provider requests.

Run from a frozen integrated tree. Real mode requires --allow-real-model; four
planned dispatches, no retries. Additional reserve requires an explicit reason.
This is a source-UI (Vite), not production-build, acceptance runner.
"""

import argparse
import contextvars
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, suppress
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "http://localhost:11434/v1"
MODEL = "qwen3.8:27b"
API = "http://127.0.0.1:5182"
WEB = "http://127.0.0.1:5175"
OWNED = (
    "tests/chat/test_chat_integration.py",
    "tests/chat/provider_fixture.py",
    "web/e2e/chat-real-model.case.ts",
    "web/playwright.chat.config.ts",
    "tools/chat_acceptance.py",
    "tests/tooling/test_chat_acceptance.py",
)


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clean_env(extra=None):
    env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "HOME",
            "TMPDIR",
            "PLAYWRIGHT_BROWSERS_PATH",
        )
        if key in os.environ
    }
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        PYTHONUNBUFFERED="1",
        npm_config_offline="true",
        npm_config_update_notifier="false",
        npm_config_audit="false",
        npm_config_fund="false",
    )
    if extra:
        env.update(extra)
    return env


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "pid": pid,
            "starttime": fields[19],
            "group": int(fields[2]),
            "parent": int(fields[1]),
            "state": fields[0],
        }
    except FileNotFoundError:
        return None


class OwnedProcess:
    def __init__(self, command, *, env, log, cwd=ROOT, pass_fds=()):
        self.command = list(map(str, command))
        self.log = open(log, "ab", buffering=0)  # noqa: SIM115 -- owned until stop()
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=cwd,
                env=env,
                stdout=self.log,
                stderr=self.log,
                start_new_session=True,
                pass_fds=pass_fds,
            )
        except BaseException:
            self.log.close()
            raise
        self.owner = identity(self.process.pid)
        assert self.owner is not None
        self.members = {self.process.pid: self.owner}
        self.cleaned = False

    def refresh(self):
        # Playwright/Chromium can start a new session: process-group-only cleanup
        # misses those children. Admit descendants while a verified owner is live.
        census = {}
        for path in Path("/proc").iterdir():
            if path.name.isdecimal() and (item := identity(int(path.name))):
                census[item["pid"]] = item
        owned = {
            pid
            for pid, old in self.members.items()
            if pid in census and census[pid]["starttime"] == old["starttime"]
        }
        changed = True
        while changed:
            changed = False
            for pid, item in census.items():
                if pid not in owned and (
                    item["parent"] in owned
                    or (self.process.pid in owned and item["group"] == self.process.pid)
                ):
                    owned.add(pid)
                    changed = True
        for pid in owned:
            self.members[pid] = census[pid]

    def stop(self, *, crash=False):
        if self.cleaned:
            return
        self.refresh()
        for sig in (signal.SIGKILL,) if crash else (signal.SIGTERM, signal.SIGKILL):
            for pid, owner in self.members.items():
                current = identity(pid)
                if current and current["starttime"] == owner["starttime"]:
                    with suppress(ProcessLookupError):
                        os.kill(pid, sig)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                continue
            until = time.monotonic() + 1
            while time.monotonic() < until:
                if all(
                    (current := identity(pid)) is None
                    or current["state"] == "Z"
                    or current["starttime"] != self.members[pid]["starttime"]
                    for pid in self.members
                ):
                    break
                time.sleep(0.01)
        self.process.wait(timeout=3)
        remaining = [
            pid
            for pid, owner in self.members.items()
            if (current := identity(pid))
            and current["state"] != "Z"
            and current["starttime"] == owner["starttime"]
        ]
        self.log.close()
        assert not remaining, f"owned processes remain: {remaining}"
        self.cleaned = True

    def receipt(self):
        return {
            "command": self.command,
            "identity": self.owner,
            "owned_members": list(self.members.values()),
            "actual_exit": self.process.poll(),
            "cleanup_verified": self.cleaned,
        }


def supervise(command, *, env, log, timeout, cwd=ROOT, tick=None):
    """Latch timeout before cleanup, even if SIGTERM makes the child exit zero."""
    if timeout <= 0:
        return {
            "actual_exit": None,
            "deadline_expired": True,
            "wrapper_exit": 1,
            "cleanup_verified": True,
            "spawned": False,
        }
    deadline = time.monotonic() + timeout
    try:
        child = OwnedProcess(command, env=env, log=log, cwd=cwd)
    except OSError as exc:
        return {
            "actual_exit": None,
            "deadline_expired": False,
            "wrapper_exit": 1,
            "cleanup_verified": True,
            "spawned": False,
            "spawn_error": type(exc).__name__,
        }
    timed_out = False
    failure = None
    try:
        while child.process.poll() is None:
            child.refresh()
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if tick:
                tick()
            time.sleep(0.05)
        # A slow observer or spawn may cross the deadline after the child exits.
        timed_out = timed_out or time.monotonic() >= deadline
    except Exception as exc:
        failure = type(exc).__name__
    finally:
        try:
            dump(
                Path(str(log) + ".before-cleanup.json"),
                {
                    **child.receipt(),
                    "deadline_expired": timed_out,
                    "observer_error": failure,
                    "expected_exit": 0,
                },
            )
        finally:
            child.stop()
    return {
        **child.receipt(),
        "deadline_expired": timed_out,
        "observer_error": failure,
        "wrapper_exit": 1 if timed_out or failure or child.process.returncode else 0,
    }


def http(base, path, method="GET", body=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        data = response.read(1048577)
        assert len(data) <= 1048576, "response budget exceeded"
        return response.status, json.loads(data)


def healthy(child, base, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert child.process.poll() is None, "owned API exited before readiness"
        try:
            if http(base, "/api/v1/health")[0] == 200:
                return
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise RuntimeError("API readiness deadline")


@contextmanager
def reserved_port(port=0):
    if port in (5173, 5180):
        raise ValueError("caller port forbidden")
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen()
        yield sock


def profile(endpoint, model=MODEL, *, streaming=True):
    return {
        "id": f"llm-{uuid4()}",
        "name": "CHAT-01 owned acceptance",
        "format": "openai",
        "model": model,
        "base_url": endpoint,
        "credential_env": "",
        "rate_per_second": 0,
        "rate_per_minute": 0,
        "context_window_k": 0,
        "streaming": streaming,
        "max_tokens": 512,
        "max_tokens_field": "",
        "thinking_type": "",
        "reasoning_effort": "",
        "retry": {key: {"attempts": 0, "interval_ms": 0} for key in ("connect", "empty", "stream")},
    }


def bootstrap(base, endpoint, model=MODEL, *, streaming=True):
    status, before = http(base, "/api/v1/ai-settings")
    assert status == 200
    selected = profile(endpoint, model, streaming=streaming)
    status, saved = http(
        base,
        "/api/v1/ai-settings",
        "PUT",
        {
            "revision": before["revision"],
            "profiles": [selected],
            "default_profile_id": selected["id"],
            "agent_profile_id": selected["id"],
        },
    )
    assert status == 200, (status, saved)
    assert http(base, "/api/v1/ai-settings") == (200, saved)
    return saved


def launch_api(state, artifacts, *, port=0, real=None):
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    with reserved_port(port) as sock:
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        extra = {"DDOSPECTOR_UI_STATE_PATH": str(state)}
        if real:
            extra.update(
                CHAT_ACCEPTANCE_LEDGER=str(real["ledger"]),
                CHAT_ACCEPTANCE_LIMIT=str(real["limit"]),
                CHAT_ACCEPTANCE_DEADLINE=str(real["deadline"]),
            )
        child = OwnedProcess(
            [sys.executable, __file__, "--serve-api", str(sock.fileno())],
            env=clean_env(extra),
            log=artifacts / "api.log",
            pass_fds=(sock.fileno(),),
        )
    try:
        healthy(child, base)
    except BaseException:
        child.stop()
        raise
    return child, base


def debit(path, limit, deadline, endpoint, payload, *, authorization=False):
    """Persist before forwarding. Failed attempts still consume the finite allowance."""
    if time.monotonic() >= deadline:
        raise RuntimeError("aggregate real-model deadline expired")
    allowed = (ENDPOINT + "/chat/completions", "http://127.0.0.1:11434/v1/chat/completions")
    if endpoint not in allowed or payload.get("model") != MODEL or authorization:
        raise RuntimeError("unapproved real-model binding")
    if payload.get("max_tokens") != 512 or payload.get("stream") is not True:
        raise RuntimeError("unapproved real-model options")
    rows = json.loads(Path(path).read_text())
    if len(rows) >= limit:
        raise RuntimeError("finite dispatch allowance exhausted")
    rows.append(
        {
            "dispatch": len(rows) + 1,
            "endpoint": endpoint,
            "monotonic": time.monotonic(),
            "request": payload,
        }
    )
    dump(path, rows)


def serve_api(fd):
    import uvicorn

    import aiddos.api.app as module

    assert Path(module.__file__).resolve() == ROOT / "src/aiddos/api/app.py"
    ledger = os.environ.get("CHAT_ACCEPTANCE_LEDGER")
    if ledger:
        import httpx2

        allowed = contextvars.ContextVar("chat_acceptance_dispatch", default=False)
        original = httpx2.AsyncClient.send

        async def observed_send(client, request, *args, **kwargs):
            payload = json.loads(request.content)
            debit(
                ledger,
                int(os.environ["CHAT_ACCEPTANCE_LIMIT"]),
                float(os.environ["CHAT_ACCEPTANCE_DEADLINE"]),
                str(request.url),
                payload,
                authorization="authorization" in request.headers,
            )
            token = allowed.set(True)
            try:
                return await original(client, request, *args, **kwargs)
            finally:
                allowed.reset(token)

        httpx2.AsyncClient.send = observed_send

        def audit(event, args):
            if event == "socket.connect":
                address = args[1]
                if not allowed.get() or address[:2] != ("127.0.0.1", 11434):
                    raise RuntimeError("unobserved or unapproved outbound connection")

        sys.addaudithook(audit)
    uvicorn.run(module.app, fd=fd, log_level="warning", timeout_graceful_shutdown=2)


def manifest():
    files = sorted(
        set(OWNED)
        | {
            str(p.relative_to(ROOT))
            for folder in (
                ROOT / "src",
                ROOT / "web/src",
            )
            for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        | {
            "web/vite.config.ts",
            "web/package.json",
            "web/package-lock.json",
            "pyproject.toml",
            "uv.lock",
        }
    )
    return [
        {
            "path": name,
            "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
            "mode": oct((ROOT / name).stat().st_mode & 0o777),
        }
        for name in files
        if (ROOT / name).is_file()
    ]


def browser_preflight(artifacts):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node missing from sanitized PATH")
    script = """
      import { chromium } from '@playwright/test';
      import { mkdtempSync, rmSync } from 'node:fs';
      import { join } from 'node:path';
      const dir = mkdtempSync(join(process.env.TMPDIR, 'chat-browser-'));
      try {
        const browser = await chromium.launch({headless: true});
        try {
          const page = await browser.newPage();
          await page.setContent('<button>observer preflight</button>');
          await page.getByRole('button').focus();
          if (!await page.getByRole('button').evaluate(e => e === document.activeElement))
            throw Error('focus observer failed');
          console.log(JSON.stringify({browser: browser.version(), headless: true,
            tempWritable: true, focus: true, providerRequests: 0}));
        } finally { await browser.close(); }
      } finally { rmSync(dir, {recursive: true}); }
    """
    if not os.environ.get("TMPDIR") or not Path(os.environ["TMPDIR"]).is_dir():
        raise RuntimeError("explicit existing TMPDIR required")
    return supervise(
        [node, "--input-type=module", "-e", script],
        env=clean_env(),
        log=artifacts / "browser-preflight.log",
        timeout=40,
        cwd=ROOT / "web",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "fixture", "real"), default="preflight")
    parser.add_argument("--allow-real-model", action="store_true")
    parser.add_argument("--max-dispatches", type=int, choices=(4, 5, 6), default=4)
    parser.add_argument("--reserve-reason")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--serve-api", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve_api is not None:
        serve_api(args.serve_api)
        return 0
    if args.mode == "real" and not args.allow_real_model:
        parser.error("real mode requires explicit --allow-real-model")
    if args.max_dispatches > 4 and not args.reserve_reason:
        parser.error("reserve allowance requires --reserve-reason")
    artifacts = args.artifacts or ROOT / ".hermes/chat01-acceptance" / str(uuid4())
    artifacts.mkdir(parents=True, exist_ok=False)
    artifacts = artifacts.resolve()
    os.chmod(artifacts, 0o700)
    state_dir = artifacts / "owned-state"
    state_dir.mkdir(mode=0o700)
    ledger = artifacts / "dispatches.json"
    dump(ledger, [])
    before = manifest()
    dump(artifacts / "source-manifest.json", before)
    result = {
        "mode": args.mode,
        "ui_mode": "actual-source-vite",
        "verdict": "HOLD",
        "real_model_requests": 0,
        "wrapper_exit": 1,
        "children": [],
        "provider_binding": {"endpoint": ENDPOINT, "model": MODEL},
        "reserve_reason": args.reserve_reason,
        "product_green": False,
    }
    api = vite = fixture = None
    try:
        # Never adopt another listener, including canonical E2E ports.
        with reserved_port(5175), reserved_port(5182):
            pass
        result["browser_preflight"] = browser_preflight(artifacts)
        assert result["browser_preflight"]["wrapper_exit"] == 0, "browser preflight failed"
        if args.mode == "preflight":
            result.update(verdict="PREFLIGHT_ONLY", wrapper_exit=0)
        else:
            deadline = time.monotonic() + 900
            endpoint = ENDPOINT
            model = MODEL
            if args.mode == "fixture":
                sys.path.insert(0, str(ROOT / "tests/chat"))
                from provider_fixture import ProviderFixture, Scenario

                fixture = ProviderFixture([Scenario.text(), Scenario.text(terminal=False)])
                fixture.__enter__()
                endpoint = fixture.base_url
                model = "SYNTHETIC-fixture-only"
            real = {"ledger": ledger, "limit": args.max_dispatches, "deadline": deadline}
            api, base = launch_api(
                state_dir / "draft.json",
                artifacts,
                port=5182,
                real=real if args.mode == "real" else None,
            )
            bootstrap(base, endpoint, model)
            status, runtime = http(base, "/api/v1/chat/runtime")
            dump(artifacts / "runtime.json", {"status": status, "body": runtime})
            assert status == 200 and runtime["supported"], (status, runtime)
            assert runtime["profile"]["endpoint"] == endpoint.rstrip("/") + "/chat/completions"
            vite = OwnedProcess(
                [
                    shutil.which("node"),
                    "node_modules/vite/bin/vite.js",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5175",
                    "--strictPort",
                ],
                env=clean_env({"VITE_API_PROXY_TARGET": API}),
                log=artifacts / "vite.log",
                cwd=ROOT / "web",
            )
            # Do not trust a health reply until this Vite has logged its own bind.
            ready_by = time.monotonic() + 20
            while "http://127.0.0.1:5175/" not in (artifacts / "vite.log").read_text():
                assert vite.process.poll() is None, "owned Vite failed to bind"
                assert time.monotonic() < ready_by, "Vite bind deadline"
                time.sleep(0.05)
            # Proxy health proves the source server reaches this owned API.
            healthy(vite, WEB)
            restarted = False

            def tick():
                nonlocal api, restarted
                marker = artifacts / "restart-request.json"
                if marker.exists() and not restarted:
                    wanted = json.loads(marker.read_text())
                    status, turn = http(API, f"/api/v1/chat/turns/{wanted['turn_id']}")
                    assert status == 200 and turn["status"] == "running"
                    assert turn["assistant_text"], "no committed partial before crash"
                    dump(artifacts / "pre-restart-turn.json", turn)
                    api.stop(crash=True)
                    result["children"].append(api.receipt())
                    api, _ = launch_api(state_dir / "draft.json", artifacts, port=5182, real=real)
                    restarted = True
                    dump(artifacts / "restart-ready.json", {"ready": True})

            browser_env = clean_env(
                {"CHAT_ACCEPTANCE_MODE": args.mode, "CHAT_ACCEPTANCE_DIR": str(artifacts)}
            )
            result["browser"] = supervise(
                [
                    shutil.which("node"),
                    "node_modules/@playwright/test/cli.js",
                    "test",
                    "--config",
                    "playwright.chat.config.ts",
                ],
                env=browser_env,
                log=artifacts / "browser.log",
                cwd=ROOT / "web",
                timeout=max(0, deadline - time.monotonic()),
                tick=tick,
            )
            assert result["browser"]["wrapper_exit"] == 0, "browser acceptance failed"
            if args.mode == "real":
                assert restarted, "restart gate not exercised"
                assert len(json.loads(ledger.read_text())) == 4, "four planned dispatches required"
            else:
                assert len(fixture.requests) == 2
                dump(artifacts / "synthetic-provider.json", fixture.requests)
            assert manifest() == before, "source changed during acceptance"
            result.update(
                verdict="REAL_PRODUCT_PASS"
                if args.mode == "real"
                else "FIXTURE_BROWSER_PASS_NOT_REAL",
                wrapper_exit=0,
                product_green=args.mode == "real",
            )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup_errors = []
        try:
            result["real_model_requests"] = len(json.loads(ledger.read_text()))
            # Capture the verdict before cleanup; cleanup never repairs a failed gate.
            result["pre_cleanup_children"] = [child.receipt() for child in (vite, api) if child]
            dump(artifacts / "before-cleanup.json", result)
        except Exception as exc:
            cleanup_errors.append(f"pre-cleanup receipt unavailable: {type(exc).__name__}")
            result["real_model_requests"] = None
        for child in (vite, api):
            if child:
                try:
                    child.stop()
                except Exception as exc:
                    cleanup_errors.append(str(exc))
                result["children"].append(child.receipt())
        if fixture:
            try:
                fixture.__exit__()
                result["fixture_counters"] = {
                    "opened": fixture.opened,
                    "closed": fixture.closed,
                    "peer_closed": fixture.peer_closed,
                }
            except Exception as exc:
                cleanup_errors.append(str(exc))
        if cleanup_errors:
            result.update(
                cleanup_errors=cleanup_errors, wrapper_exit=1, verdict="HOLD", product_green=False
            )
        dump(artifacts / "result.json", result)
        print(json.dumps({"artifacts": str(artifacts), **result}, ensure_ascii=False))
    return result["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
