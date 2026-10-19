#!/usr/bin/env python3
"""CHAT02A source-bound native tool acceptance; default is offline zero-model preflight.

Fixture mode runs real product HTTP/browser routes, not mocked API responses.
Real mode is parent-only: --allow-real-model plus a frozen admission file, a
persistent six-dispatch ledger and ONE original 900-second deadline. No retry.
"""

import argparse
import asyncio
import contextvars
import fcntl
import hashlib
import json
import os
import shutil
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import chat_acceptance as legacy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/chat"))
from provider_fixture import ProviderFixture, Scenario  # noqa: E402

MODEL = "qwen3.8:27b"
ENDPOINT = "http://localhost:11434/v1"
COMPLETIONS = ENDPOINT + "/chat/completions"
NAME = "CHAT02A 승인된 에이전트 🌍"
TARGET_NAME = "CHAT02B1 승인된 대상 🌍"
TARGET_INPUT = {"name": TARGET_NAME, "address": "Example.COM.", "kind": "DUT"}
OWNED = (
    "tools/chat_tools_acceptance.py",
    "tests/tooling/test_chat_tools_acceptance.py",
    "tests/tooling/test_chat_tools_acceptance_origin.py",
    "tests/tooling/test_chat_tools_acceptance_target.py",
    "tests/chat/test_chat_target_integration.py",
    "tests/chat/chat_target_capture.py",
    "tests/chat/test_chat_tools_integration.py",
    "web/e2e/chat-tools.case.ts",
    "web/playwright.chat-tools.config.ts",
)
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
CALL_TERMINAL = {"succeeded", "denied", "conflict", "failed", "uncertain", "cancelled"}
http = legacy.http
supervise = legacy.supervise


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def dump(path, value):
    """Atomic, fsynced evidence/ledger publication; never debit after forwarding."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".pending")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def manifest():
    files = {entry["path"] for entry in legacy.manifest()} | set(OWNED)
    return [
        {
            "path": name,
            "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
            "mode": oct((ROOT / name).stat().st_mode & 0o777),
        }
        for name in sorted(files)
        if (ROOT / name).is_file()
    ]


def clean_env(extra=None):
    return legacy.clean_env(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_OFFLINE": "1",
            "UV_NO_SYNC": "1",
            **(extra or {}),
        }
    )


def native(name, arguments, call_id="native-call-01", *, streaming=True):
    """Native provider protocol only; retain literal argument JSON in context."""
    raw = arguments if isinstance(arguments, str) else encoded(arguments).decode()
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}
    if not streaming:
        return Scenario(
            (
                encoded(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [call],
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    }
                ),
            ),
            content_type="application/json",
        )
    frames = [
        {
            "choices": [
                {"index": 0, "delta": {"tool_calls": [{"index": 0, **call}]}, "finish_reason": None}
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    return Scenario(
        tuple(b"data: " + encoded(frame) + b"\n\n" for frame in frames) + (b"data: [DONE]\n\n",)
    )


def revision(workspace):
    return workspace["meta"]["audit_retention"]["total_recorded"]


def agent(workspace):
    return {
        "resource_id": "agent-profile",
        "name": workspace["agent_profile"]["name"],
        "skill_ids": workspace["agent_profile"]["skill_ids"],
    }


def plan(workspace, *, skills=None, fixture_case="agent"):
    if fixture_case == "target":
        if skills is not None:
            raise ValueError("target fixture does not have Agent skill authority")
        return [
            native(
                "configuration_read",
                {"kind": "targets", "offset": 0, "limit": 10},
                "native-target-read-01",
            ),
            native(
                "target_create",
                {"expected_draft_revision": revision(workspace), **TARGET_INPUT},
                "native-target-create-02",
            ),
            Scenario.text("SYNTHETIC approved target receipt observed."),
        ]
    if fixture_case != "agent":
        raise ValueError("unknown fixture case")
    arguments = {
        "expected_draft_revision": revision(workspace),
        "name": NAME,
        "skill_ids": workspace["agent_profile"]["skill_ids"] if skills is None else skills,
    }
    return [
        native("configuration_read", '{ "kind" : "agent_profile" }', "native-read-01"),
        native("agent_profile_update", arguments, "native-update-02"),
        Scenario.text("SYNTHETIC approved operation receipt observed."),
    ]


def observer_payload():
    return {
        "model": MODEL,
        "stream": True,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "HARNESS ONLY"}],
    }


def initialize_ledger(path, started, deadline):
    if not 0 < deadline - started <= 900:
        raise RuntimeError("invalid original 900-second deadline")
    path = Path(path)
    # Exclusive creation: existing counts/deadlines are NEVER reset by a rerun.
    with path.open("x") as stream:
        json.dump(
            {
                "started": started,
                "deadline": deadline,
                "maximum": 6,
                "admitted_until": 3,
                "corrections": [],
                "dispatches": [],
                "network": [],
            },
            stream,
        )
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def ledger_lock(path):
    with Path(str(path) + ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def debit(path, request):
    payload = json.loads(request.content)
    if (
        request.method != "POST"
        or str(request.url) not in (COMPLETIONS, "http://127.0.0.1:11434/v1/chat/completions")
        or "authorization" in request.headers
        or "proxy-authorization" in request.headers
        or payload.get("model") != MODEL
        or payload.get("stream") is not True
        or type(payload.get("max_tokens")) is not int
        or payload["max_tokens"] != 512
        or not isinstance(payload.get("messages"), list)
    ):
        raise RuntimeError("unapproved model request")
    if set(payload) - {"model", "stream", "max_tokens", "messages", "tools", "tool_choice"}:
        raise RuntimeError("unapproved model options")
    if "tools" in payload:
        tools = payload["tools"]
        if (
            not isinstance(tools, list)
            or len(tools) != 2
            or {item.get("function", {}).get("name") for item in tools}
            != {"configuration_read", "agent_profile_update"}
        ):
            raise RuntimeError("unapproved tool registry")
    with ledger_lock(path):
        value = json.loads(Path(path).read_text())
        now = time.monotonic()
        if (
            value["maximum"] != 6
            or not 0 < value["deadline"] - value["started"] <= 900
            or now < value["started"]
            or now >= value["deadline"]
        ):
            raise RuntimeError("original aggregate deadline expired or invalid")
        if len(value["dispatches"]) >= 6:
            raise RuntimeError("six-dispatch aggregate allowance exhausted")
        if (
            not 3 <= value["admitted_until"] <= 6
            or len(value["dispatches"]) >= value["admitted_until"]
        ):
            raise RuntimeError("additional dispatch requires explicit parent correction")
        value["dispatches"].append(
            {
                "dispatch": len(value["dispatches"]) + 1,
                "monotonic": now,
                "endpoint": str(request.url),
                "request": payload,
            }
        )
        dump(path, value)


def install_observer(path):
    """Instrument the INSTALLED SDK primitive, including send(request=...)."""
    import httpx2

    allowed = contextvars.ContextVar("chat02a_observed_send", default=False)
    original = httpx2.AsyncClient.send

    async def observed_send(client, request, **kwargs):
        debit(path, request)
        token = allowed.set(True)
        try:
            return await original(client, request=request, **kwargs)
        finally:
            allowed.reset(token)

    def audit(event, args):
        if event not in ("socket.connect", "socket.getaddrinfo"):
            return
        if event == "socket.connect":
            address = args[1]
            valid = allowed.get() and address[:2] == ("127.0.0.1", 11434)
        else:
            address = args[:2]
            valid = (
                allowed.get() and address[0] in ("localhost", "127.0.0.1") and address[1] == 11434
            )
        with ledger_lock(path):
            value = json.loads(Path(path).read_text())
            value["network"].append(
                {"event": event, "address": list(address), "allowed": bool(valid)}
            )
            dump(path, value)
        if not valid:
            raise RuntimeError("unobserved or unapproved outbound connection")

    httpx2.AsyncClient.send = observed_send
    sys.addaudithook(audit)
    return original


def observer_preflight(directory):
    """Actual SDK + MockTransport; no socket or API startup, no inference."""
    import httpx2

    ledger = Path(directory) / "observer-selftest.json"
    start = time.monotonic()
    initialize_ledger(ledger, start, start + 30)
    hooks = []
    original_hook = sys.addaudithook
    original_send = httpx2.AsyncClient.send
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    forwarded = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("observer selftest attempted network")

    def transport(request):
        assert len(json.loads(ledger.read_text())["dispatches"]) == 1
        hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
        forwarded.append(request)
        return httpx2.Response(200, content=b"SYNTHETIC")

    async def run():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(transport), trust_env=False
        ) as client:
            response = await client.send(
                request=client.build_request("POST", COMPLETIONS, json=observer_payload()),
                stream=True,
            )
            assert await response.aread() == b"SYNTHETIC"
            await response.aclose()
            for patch in ({"model": "wrong"}, {"max_tokens": 513}, {"stream": False}):
                try:
                    await client.send(
                        request=client.build_request(
                            "POST", COMPLETIONS, json={**observer_payload(), **patch}
                        ),
                        stream=True,
                    )
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("forbidden request forwarded")

    try:
        sys.addaudithook = hooks.append
        socket.socket.connect = forbidden
        socket.socket.connect_ex = forbidden
        install_observer(ledger)
        asyncio.run(run())
        try:
            hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
        except RuntimeError:
            pass
        else:
            raise AssertionError("unobserved connection accepted")
        assert len(forwarded) == 1
        return {"verdict": "HARNESS_ONLY_PASS", "mock_forwards": 1, "network_requests": 0}
    finally:
        sys.addaudithook = original_hook
        httpx2.AsyncClient.send = original_send
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


def validate_admission(path, source, correction_reason=None):
    value = json.loads(Path(path).read_text())
    required = {
        "schema_version",
        "parent_admitted",
        "source_sha256",
        "started",
        "deadline",
        "boot_id",
        "ledger",
        "fixture_receipt",
        "fixture_sha256",
        "review_passed",
        "correction",
    }
    if (
        set(value) != required
        or value["schema_version"] != 1
        or value["parent_admitted"] is not True
    ):
        raise RuntimeError("explicit frozen parent admission required")
    if value["source_sha256"] != digest(source) or value["review_passed"] is not True:
        raise RuntimeError("frozen integration/review mismatch")
    if value["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise RuntimeError("admission belongs to another boot")
    now = time.monotonic()
    if (
        not value["started"] <= now < value["deadline"]
        or not 0 < value["deadline"] - value["started"] <= 900
    ):
        raise RuntimeError("parent original deadline expired or invalid")
    receipt_bytes = Path(value["fixture_receipt"]).read_bytes()
    if hashlib.sha256(receipt_bytes).hexdigest() != value["fixture_sha256"]:
        raise RuntimeError("fixture receipt hash mismatch")
    receipt = json.loads(receipt_bytes)
    if (
        receipt.get("verdict") != "FIXTURE_BROWSER_PASS_NOT_REAL"
        or receipt.get("wrapper_exit") != 0
        or receipt.get("source_sha256") != digest(source)
    ):
        raise RuntimeError("complete current-source fixture gate required")
    ledger = Path(value["ledger"])
    if not ledger.is_absolute() or ledger.is_symlink():
        raise RuntimeError("absolute owned regular ledger required")
    if not ledger.exists():
        initialize_ledger(ledger, value["started"], value["deadline"])
    saved = json.loads(ledger.read_text())
    if (
        saved["started"] != value["started"]
        or saved["deadline"] != value["deadline"]
        or saved["maximum"] != 6
    ):
        raise RuntimeError("persistent admission ledger mismatch")
    if saved["dispatches"]:
        correction = value["correction"]
        if not correction_reason or not isinstance(correction, dict):
            raise RuntimeError("no automatic rerun: parent must diagnose existing dispatches")
        if (
            set(correction) != {"reason", "prior_dispatches", "prior_ledger_sha256"}
            or correction["reason"] != correction_reason
            or not correction_reason.strip()
            or correction["prior_dispatches"] != len(saved["dispatches"])
            or correction["prior_ledger_sha256"] != hashlib.sha256(ledger.read_bytes()).hexdigest()
            or saved["corrections"]
            or not 1 <= len(saved["dispatches"]) <= 3
        ):
            raise RuntimeError("explicit parent correction binding mismatch")
        saved["admitted_until"] = len(saved["dispatches"]) + 3
        saved["corrections"].append(correction)
        dump(ledger, saved)
    elif correction_reason or value["correction"] is not None:
        raise RuntimeError("correction requires a prior observed dispatch")
    return value


@contextmanager
def parent_gate(path, source, correction_reason=None):
    # Hold a separate process-wide lock through cleanup; debit uses its own lock.
    ledger = Path(json.loads(Path(path).read_text())["ledger"])
    if not ledger.is_absolute():
        raise RuntimeError("absolute parent ledger required")
    with Path(str(ledger) + ".gate").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("parent gate already active") from None
        yield validate_admission(path, source, correction_reason)


def install_fault(directory, state, mode):
    """Fixture-only real filesystem seams. Arming after bootstrap avoids setup faults."""
    original_fsync = os.fsync
    original_replace = os.replace
    directory, state = Path(directory), Path(state).resolve()

    def activated():
        return (directory / "fault-arm").exists()

    def fired(phase):
        # Avoid recursive fsync hooks while writing the observation.
        (directory / "fault-fired.json").write_text(json.dumps({"mode": mode, "phase": phase}))

    def fsync(fd):
        target = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if activated() and target.parent == state.parent and target.name.startswith(".ui-drafts-"):
            if mode == "pause-before-publication":
                fired("temp-fsync-before-final-guard")
                until = time.monotonic() + 15
                while not (directory / "fault-release").exists():
                    if time.monotonic() >= until:
                        raise OSError("SYNTHETIC bounded barrier timeout")
                    time.sleep(0.01)
            elif mode == "prepublication-failure":
                fired("temp-fsync")
                raise OSError("SYNTHETIC prepublication failure")
        if activated() and target == state.parent and mode == "postpublication-failure":
            fired("directory-fsync-after-publication")
            raise OSError("SYNTHETIC postpublication failure")
        return original_fsync(fd)

    def replace(source, destination, *args, **kwargs):
        if activated() and Path(destination).resolve() == state and mode == "pause-armed-intent":
            fired("armed-intent-before-replace")
            until = time.monotonic() + 15
            while not (directory / "fault-release").exists():
                if time.monotonic() >= until:
                    raise OSError("SYNTHETIC bounded barrier timeout")
                time.sleep(0.01)
        return original_replace(source, destination, *args, **kwargs)

    os.fsync = fsync
    os.replace = replace


def install_fixture_network_guard(directory):
    """All fixture outbound sockets must name this invocation's recorded provider."""
    directory = Path(directory)

    def audit(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo"}:
            return
        marker = directory / "provider-origin.json"
        allowed = json.loads(marker.read_text()) if marker.exists() else None
        address = args[1][:2] if event == "socket.connect" else args[:2]
        if (
            not isinstance(allowed, dict)
            or set(allowed) != {"host", "port"}
            or allowed["host"] != "127.0.0.1"
            or type(allowed["port"]) is not int
            or allowed["port"] in {11434, 5173, 5180}
            or tuple(address) != (allowed["host"], allowed["port"])
        ):
            raise RuntimeError("fixture outbound destination not owned")

    sys.addaudithook(audit)


def record_provider(directory, provider):
    from urllib.parse import urlsplit

    origin = urlsplit(provider.base_url)
    assert origin.hostname == "127.0.0.1" and origin.port not in {11434, 5173, 5180}
    dump(Path(directory) / "provider-origin.json", {"host": origin.hostname, "port": origin.port})


def serve_api(fd):
    import uvicorn

    import aiddos.api.app as module

    assert Path(module.__file__).resolve() == ROOT / "src/aiddos/api/app.py"
    ledger = os.environ.get("CHAT02A_LEDGER")
    fault = os.environ.get("CHAT02A_FAULT")
    if ledger and fault:
        raise RuntimeError("fault injection forbidden in real mode")
    if ledger:
        install_observer(Path(ledger))
    else:
        install_fixture_network_guard(os.environ["CHAT02A_ARTIFACTS"])
        if fault:
            install_fault(
                os.environ["CHAT02A_FAULT_DIR"], os.environ["DDOSPECTOR_UI_STATE_PATH"], fault
            )
    uvicorn.run(module.app, fd=fd, log_level="warning", timeout_graceful_shutdown=2)


def launch_api(state, artifacts, *, port=0, ledger=None, fault=None):
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    extra = {"DDOSPECTOR_UI_STATE_PATH": str(state), "CHAT02A_ARTIFACTS": str(artifacts)}
    if ledger:
        extra["CHAT02A_LEDGER"] = str(ledger)
    if fault:
        extra.update(CHAT02A_FAULT=fault, CHAT02A_FAULT_DIR=str(artifacts))
    with legacy.reserved_port(port) as sock:
        base = f"http://127.0.0.1:{sock.getsockname()[1]}"
        child = legacy.OwnedProcess(
            [sys.executable, __file__, "--serve-api", str(sock.fileno())],
            env=clean_env(extra),
            log=artifacts / "api.log",
            cwd=ROOT,
            pass_fds=(sock.fileno(),),
        )
    try:
        legacy.healthy(child, base)
    except BaseException:
        child.stop()
        raise
    return child, base


def require_runtime(base, artifacts, *, fixture_case="agent"):
    status, runtime = http(base, "/api/v1/chat/tools/runtime")
    dump(Path(artifacts) / "tools-runtime.json", {"status": status, "body": runtime})
    assert status == 200, f"missing CHAT02A runtime: HTTP {status}: {runtime}"
    assert runtime["supported"] is True and runtime["requires_write_approval"] is True
    expected = {
        1: ["configuration_read", "agent_profile_update"],
        2: ["configuration_read", "agent_profile_update", "target_create"],
    }
    assert type(runtime["schema_version"]) is int and runtime["schema_version"] in expected
    assert runtime["tools"] == expected[runtime["schema_version"]]
    if fixture_case == "target":
        assert runtime["schema_version"] == 2, "missing CHAT02B1 target runtime"


def run_browser(mode, directory, result, admission=None, *, fixture_case="agent"):
    if mode == "fixture" and admission is not None:
        raise RuntimeError("fixture cannot use real-model admission or ledger")
    if fixture_case not in {"agent", "target"} or (mode != "fixture" and fixture_case != "agent"):
        raise RuntimeError("target fixture cannot authorize real inference")
    deadline = admission["deadline"] if admission else time.monotonic() + 900
    ledger = admission["ledger"] if admission else None
    api = vite = provider = None
    state = directory / "owned-state" / "draft.json"
    try:
        endpoint, model = ENDPOINT, MODEL
        if mode == "fixture":
            provider = ProviderFixture([Scenario.text()])
            provider.__enter__()
            record_provider(directory, provider)
            endpoint, model = provider.base_url, "SYNTHETIC-fixture-only"
        api, base = launch_api(state, directory, ledger=ledger)
        legacy.bootstrap(base, endpoint, model)
        status, before = http(base, "/api/v1/workspace")
        assert status == 200
        dump(directory / "workspace-before.json", before)
        if provider:
            provider.scenarios = tuple(plan(before, fixture_case=fixture_case))
        require_runtime(base, directory, fixture_case=fixture_case)
        # Use an already-allowed browser Origin; never broaden backend policy.
        # Reservation and strictPort both refuse collision, never adopt a server.
        with legacy.reserved_port(5175) as sock:
            port = sock.getsockname()[1]
        web = f"http://127.0.0.1:{port}"
        vite = legacy.OwnedProcess(
            [
                shutil.which("node"),
                "node_modules/vite/bin/vite.js",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=ROOT / "web",
            env=clean_env({"VITE_API_PROXY_TARGET": base}),
            log=directory / "vite.log",
        )
        ready = min(deadline, time.monotonic() + 20)
        while web + "/" not in (directory / "vite.log").read_text():
            assert vite.process.poll() is None and time.monotonic() < ready, "owned Vite not ready"
            time.sleep(0.05)
        legacy.healthy(vite, web)
        restarted = False

        def tick():
            nonlocal api, restarted
            if (directory / "restart-request.json").exists() and not restarted:
                marker = json.loads((directory / "restart-request.json").read_text())
                status, turn = http(base, f"/api/v1/chat/turns/{marker['turn_id']}")
                assert status == 200 and turn["status"] == "succeeded"
                old_port = int(base.rsplit(":", 1)[1])
                api.stop()
                result["children"].append(api.receipt())
                api, new_base = launch_api(state, directory, port=old_port, ledger=ledger)
                assert new_base == base
                restarted = True
                dump(directory / "restart-ready.json", {"ready": True})

        result["browser"] = supervise(
            [
                shutil.which("node"),
                "node_modules/@playwright/test/cli.js",
                "test",
                "--config",
                "playwright.chat-tools.config.ts",
            ],
            cwd=ROOT / "web",
            env=clean_env(
                {
                    "CHAT02A_DIR": str(directory),
                    "CHAT02A_MODE": mode,
                    "CHAT02A_WEB": web,
                    "CHAT02A_NAME": TARGET_NAME if fixture_case == "target" else NAME,
                    **({"CHAT02B1_FIXTURE_CASE": fixture_case} if mode == "fixture" else {}),
                }
            ),
            log=directory / "browser.log",
            timeout=max(0, deadline - time.monotonic()),
            tick=tick,
        )
        assert result["browser"]["wrapper_exit"] == 0, "browser acceptance failed"
        assert restarted, "owned restart not exercised"
        if provider:
            assert len(provider.requests) == 3, "planned read/proposal/final dispatches required"
            dump(directory / "provider-requests.json", provider.requests)
        else:
            rows = json.loads(Path(ledger).read_text())["dispatches"]
            prior = admission["correction"]["prior_dispatches"] if admission["correction"] else 0
            assert len(rows) - prior == 3, "unplanned dispatch: parent diagnosis required, no retry"
        result.update(
            verdict="REAL_PRODUCT_PASS" if mode == "real" else "FIXTURE_BROWSER_PASS_NOT_REAL",
            product_green=mode == "real",
            wrapper_exit=0,
        )
    finally:
        for child in (vite, api):
            if child:
                child.stop()
                result["children"].append(child.receipt())
        if provider:
            dump(directory / "provider-requests.json", provider.requests)
            provider.__exit__()
            result["provider_requests"] = len(provider.requests)
            result["provider_handlers_closed"] = provider.opened == provider.closed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "fixture", "real"), default="preflight")
    parser.add_argument("--fixture-case", choices=("agent", "target"), default=None)
    parser.add_argument("--allow-real-model", action="store_true")
    parser.add_argument("--parent-admission", type=Path)
    parser.add_argument("--correction-reason")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--serve-api", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.fixture_case is not None and (args.mode != "fixture" or args.serve_api is not None):
        parser.error("--fixture-case is allowed only in fixture mode")
    if args.serve_api is not None:
        serve_api(args.serve_api)
        return 0
    if args.mode == "real" and (not args.allow_real_model or not args.parent_admission):
        parser.error("real mode requires --allow-real-model and frozen --parent-admission")
    directory = (args.artifacts or ROOT / ".hermes/chat02a-acceptance" / str(uuid4())).resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = manifest()
    dump(directory / "source-pre.json", source)
    result = {
        "mode": args.mode,
        "fixture_case": (args.fixture_case or "agent") if args.mode == "fixture" else None,
        "verdict": "HOLD",
        "product_green": False,
        "real_model_requests": 0,
        "wrapper_exit": 1,
        "children": [],
        "source_sha256": digest(source),
        "root": str(ROOT),
        "planned_dispatches": 3,
        "hard_dispatch_cap": 6,
        "wall_seconds": 900,
    }
    admission = None
    try:
        result["observer_preflight"] = observer_preflight(directory)
        if args.mode == "preflight":
            result.update(verdict="PREFLIGHT_ONLY", wrapper_exit=0)
        else:
            if args.mode == "real":
                with parent_gate(args.parent_admission, source, args.correction_reason) as admitted:
                    admission = admitted
                    run_browser(args.mode, directory, result, admission)
            else:
                run_browser(args.mode, directory, result, fixture_case=args.fixture_case or "agent")
    except Exception as exc:
        result.update(
            error=f"{type(exc).__name__}: {exc}",
            verdict="HOLD",
            wrapper_exit=1,
            product_green=False,
        )
    finally:
        after = manifest()
        dump(directory / "source-post.json", after)
        if source != after:
            result.update(
                verdict="HOLD",
                wrapper_exit=1,
                product_green=False,
                error="source changed during gate",
            )
        if admission:
            result["real_model_requests"] = len(
                json.loads(Path(admission["ledger"]).read_text())["dispatches"]
            )
        dump(directory / "result.json", result)
        print(json.dumps({"artifacts": str(directory), **result}, ensure_ascii=False))
    return result["wrapper_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
