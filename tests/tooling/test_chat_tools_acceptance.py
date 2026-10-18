"""Harness safety controls ONLY: no product acceptance, no inference sockets."""

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import chat_tools_acceptance as harness  # noqa: E402


def test_native_fixture_preserves_original_arguments():
    raw = '{ "kind" : "agent_profile" }'
    scenario = harness.native("configuration_read", raw, "native-read-01")
    frames = [
        json.loads(line[6:])
        for line in b"".join(scenario.chunks).splitlines()
        if line.startswith(b"data: ") and line != b"data: [DONE]"
    ]
    call = frames[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["id"] == "native-read-01"
    assert call["function"]["arguments"] == raw
    assert frames[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_default_is_zero_model_preflight(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("default preflight attempted a socket")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    out = tmp_path / "default"
    assert harness.main(["--artifacts", str(out)]) == 0
    result = json.loads((out / "result.json").read_text())
    assert result["verdict"] == "PREFLIGHT_ONLY"
    assert result["real_model_requests"] == 0
    assert result["product_green"] is False


def test_installed_keyword_request_observer_persists_before_forward(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    harness.initialize_ledger(ledger, time.monotonic(), time.monotonic() + 60)
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    forwarded = []

    def transport(request):
        rows = json.loads(ledger.read_text())["dispatches"]
        assert len(rows) == 1 and rows[0]["request"] == json.loads(request.content)
        hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
        forwarded.append(request)
        return httpx2.Response(200, content=b"SYNTHETIC")

    original = httpx2.AsyncClient.send
    try:
        harness.install_observer(ledger)

        async def run():
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(transport), trust_env=False
            ) as client:
                request = client.build_request(
                    "POST", harness.COMPLETIONS, json=harness.observer_payload()
                )
                response = await client.send(request=request, stream=True)
                assert await response.aread() == b"SYNTHETIC"
                await response.aclose()

        asyncio.run(run())
        assert len(forwarded) == 1
        with pytest.raises(RuntimeError):
            hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
    finally:
        httpx2.AsyncClient.send = original


@pytest.mark.parametrize(
    "control",
    [
        "model",
        "tokens",
        "stream",
        "auth",
        "proxy-auth",
        "method",
        "host",
        "port",
        "path",
        "query",
        "userinfo",
        "scheme",
        "tools",
        "options",
        "expired",
        "exhausted",
        "bad-cap",
    ],
)
def test_installed_observer_forbidden_controls_never_forward(tmp_path, monkeypatch, control):
    ledger = tmp_path / "ledger.json"
    started = time.monotonic()
    harness.initialize_ledger(ledger, started, started + 30)
    payload = harness.observer_payload()
    url, method, headers = harness.COMPLETIONS, "POST", {}
    changes = {
        "model": {"model": "wrong"},
        "tokens": {"max_tokens": 513},
        "stream": {"stream": False},
        "tools": {"tools": []},
        "options": {"temperature": 1},
    }
    payload.update(changes.get(control, {}))
    if control in {"auth", "proxy-auth"}:
        headers["authorization" if control == "auth" else "proxy-authorization"] = "SYNTHETIC"
    if control == "method":
        method = "GET"
    urls = {
        "host": "http://example.invalid:11434/v1/chat/completions",
        "port": "http://localhost:11435/v1/chat/completions",
        "path": "http://localhost:11434/v1/models",
        "query": harness.COMPLETIONS + "?x=1",
        "userinfo": "http://user@localhost:11434/v1/chat/completions",
        "scheme": "https://localhost:11434/v1/chat/completions",
    }
    url = urls.get(control, url)
    value = json.loads(ledger.read_text())
    if control == "expired":
        value.update(started=started - 60, deadline=started - 30)
    elif control == "exhausted":
        value["dispatches"] = [{"dispatch": index + 1} for index in range(6)]
    elif control == "bad-cap":
        value["maximum"] = 7
    harness.dump(ledger, value)
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)

    def forbidden(*args, **kwargs):
        pytest.fail("forbidden control reached transport/network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    original = httpx2.AsyncClient.send
    try:
        harness.install_observer(ledger)

        async def run():
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(forbidden), trust_env=False
            ) as client:
                await client.send(
                    request=client.build_request(method, url, json=payload, headers=headers),
                    stream=True,
                )

        with pytest.raises(RuntimeError):
            asyncio.run(run())
        assert json.loads(ledger.read_text())["dispatches"] == value["dispatches"]
    finally:
        httpx2.AsyncClient.send = original


@pytest.mark.parametrize("route", ["positional", "keyword", "stream"])
@pytest.mark.parametrize("failure", [False, True])
def test_installed_observer_actual_sdk_entrypoints_and_failed_attempt_debit(
    tmp_path, monkeypatch, route, failure
):
    ledger = tmp_path / "ledger.json"
    start = time.monotonic()
    harness.initialize_ledger(ledger, start, start + 30)
    hooks, forwards = [], []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)

    def forbidden(*args, **kwargs):
        pytest.fail("MockTransport selftest opened network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    error = RuntimeError("SYNTHETIC transport fault")

    def transport(request):
        assert len(json.loads(ledger.read_text())["dispatches"]) == 1
        hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
        for address in (("127.0.0.1", 11435), ("192.0.2.1", 11434), ("::1", 11434, 0, 0)):
            with pytest.raises(RuntimeError):
                hooks[0]("socket.connect", (None, address))
        forwards.append(request)
        if failure:
            raise error
        return httpx2.Response(200, content=b"SYNTHETIC")

    original = httpx2.AsyncClient.send
    try:
        harness.install_observer(ledger)

        async def run():
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(transport), trust_env=False
            ) as client:
                if route == "stream":
                    async with client.stream(
                        "POST", harness.COMPLETIONS, json=harness.observer_payload()
                    ) as response:
                        assert await response.aread() == b"SYNTHETIC"
                else:
                    request = client.build_request(
                        "POST", harness.COMPLETIONS, json=harness.observer_payload()
                    )
                    response = (
                        await client.send(request, stream=True)
                        if route == "positional"
                        else await client.send(request=request, stream=True)
                    )
                    assert await response.aread() == b"SYNTHETIC"
                    await response.aclose()

        if failure:
            with pytest.raises(RuntimeError) as caught:
                asyncio.run(run())
            assert caught.value is error
        else:
            asyncio.run(run())
        assert len(forwards) == len(json.loads(ledger.read_text())["dispatches"]) == 1
        with pytest.raises(RuntimeError):
            hooks[0]("socket.connect", (None, ("127.0.0.1", 11434)))
    finally:
        httpx2.AsyncClient.send = original


def test_default_attempt_cannot_spend_three_parent_correction_dispatches(tmp_path):
    ledger = tmp_path / "ledger.json"
    started = time.monotonic()
    harness.initialize_ledger(ledger, started, started + 30)
    request = httpx2.Request("POST", harness.COMPLETIONS, json=harness.observer_payload())
    for _ in range(3):
        harness.debit(ledger, request)
    with pytest.raises(RuntimeError, match="explicit parent correction"):
        harness.debit(ledger, request)
    assert len(json.loads(ledger.read_text())["dispatches"]) == 3


def test_ledger_six_dispatches_original_clock_and_no_reset(tmp_path):
    path, value, source = admission(tmp_path)
    harness.validate_admission(path, source)
    ledger = Path(value["ledger"])
    started = value["started"]
    request = httpx2.Request("POST", harness.COMPLETIONS, json=harness.observer_payload())
    for _ in range(3):
        harness.debit(ledger, request)
    value["correction"] = {
        "reason": "HARNESS observer correction only",
        "prior_dispatches": 3,
        "prior_ledger_sha256": harness.hashlib.sha256(ledger.read_bytes()).hexdigest(),
    }
    harness.dump(path, value)
    harness.validate_admission(path, source, value["correction"]["reason"])
    for _ in range(3):
        harness.debit(ledger, request)
    with pytest.raises(RuntimeError, match="exhausted"):
        harness.debit(ledger, request)
    with pytest.raises(FileExistsError):
        harness.initialize_ledger(ledger, started, started + 30)
    value = json.loads(ledger.read_text())
    assert value["started"] == started and value["deadline"] == started + 30
    assert len(value["dispatches"]) == 6


def test_ledger_persistence_failure_prevents_forward(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    start = time.monotonic()
    harness.initialize_ledger(ledger, start, start + 30)

    def fail(*args, **kwargs):
        raise OSError("SYNTHETIC fsync failure")

    monkeypatch.setattr(harness.os, "fsync", fail)
    with pytest.raises(OSError):
        harness.debit(
            ledger, httpx2.Request("POST", harness.COMPLETIONS, json=harness.observer_payload())
        )
    assert json.loads(ledger.read_text())["dispatches"] == []


@pytest.mark.parametrize(
    "args", [[], ["--allow-real-model"], ["--parent-admission", "/nonexistent"]]
)
def test_real_mode_needs_both_parent_admission_and_flag_before_outputs(tmp_path, args):
    out = tmp_path / "denied"
    with pytest.raises(SystemExit) as caught:
        harness.main(["--mode", "real", "--artifacts", str(out), *args])
    assert caught.value.code == 2 and not out.exists()


def admission(tmp_path):
    source = harness.manifest()
    receipt = tmp_path / "fixture.json"
    harness.dump(
        receipt,
        {
            "verdict": "FIXTURE_BROWSER_PASS_NOT_REAL",
            "wrapper_exit": 0,
            "source_sha256": harness.digest(source),
        },
    )
    start = time.monotonic()
    value = {
        "schema_version": 1,
        "parent_admitted": True,
        "source_sha256": harness.digest(source),
        "started": start,
        "deadline": start + 30,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "ledger": str(tmp_path / "ledger.json"),
        "fixture_receipt": str(receipt),
        "fixture_sha256": harness.hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "review_passed": True,
        "correction": None,
    }
    path = tmp_path / "admission.json"
    harness.dump(path, value)
    return path, value, source


@pytest.mark.parametrize(
    "control",
    [
        "source",
        "review",
        "parent",
        "expired",
        "extended",
        "boot",
        "fixture-hash",
        "fixture-red",
        "extra",
    ],
)
def test_parent_admission_fail_closed(tmp_path, control):
    path, value, source = admission(tmp_path)
    if control == "source":
        value["source_sha256"] = "0" * 64
    elif control == "review":
        value["review_passed"] = False
    elif control == "parent":
        value["parent_admitted"] = False
    elif control == "expired":
        value.update(started=value["started"] - 90, deadline=value["deadline"] - 90)
    elif control == "extended":
        value["deadline"] = value["started"] + 901
    elif control == "boot":
        value["boot_id"] = "another-boot"
    elif control == "fixture-hash":
        value["fixture_sha256"] = "0" * 64
    elif control == "extra":
        value["allow_retry"] = True
    elif control == "fixture-red":
        receipt = Path(value["fixture_receipt"])
        harness.dump(receipt, {"verdict": "HOLD"})
        value["fixture_sha256"] = harness.hashlib.sha256(receipt.read_bytes()).hexdigest()
    harness.dump(path, value)
    with pytest.raises(RuntimeError):
        harness.validate_admission(path, source)
    assert not Path(value["ledger"]).exists()


def test_admission_control_is_harness_only_and_preserves_existing_ledger(tmp_path):
    path, value, source = admission(tmp_path)
    assert harness.validate_admission(path, source) == value
    request = httpx2.Request("POST", harness.COMPLETIONS, json=harness.observer_payload())
    harness.debit(value["ledger"], request)
    before = Path(value["ledger"]).read_bytes()
    with pytest.raises(RuntimeError, match="no automatic rerun"):
        harness.validate_admission(path, source)
    assert Path(value["ledger"]).read_bytes() == before


@pytest.mark.parametrize("program,exit_code", [("pass", 0), ("raise SystemExit(7)", 7)])
def test_reused_supervisor_actual_exit_cleanup_and_wrapper(tmp_path, program, exit_code):
    receipt = harness.supervise(
        [sys.executable, "-c", program],
        env=harness.clean_env(),
        log=tmp_path / "child.log",
        timeout=5,
        cwd=ROOT,
    )
    assert receipt["actual_exit"] == exit_code
    assert receipt["wrapper_exit"] == (0 if exit_code == 0 else 1)
    assert receipt["deadline_expired"] is False and receipt["cleanup_verified"] is True
    assert harness.legacy.identity(receipt["identity"]["pid"]) is None


def test_reused_supervisor_latches_deadline_before_graceful_zero(tmp_path):
    receipt = harness.supervise(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, lambda *_: exit(0)); "
            "print('ready',flush=True); time.sleep(10)",
        ],
        env=harness.clean_env(),
        log=tmp_path / "child.log",
        timeout=0.4,
        cwd=ROOT,
    )
    assert "ready" in (tmp_path / "child.log").read_text()
    assert receipt["actual_exit"] == 0 and receipt["wrapper_exit"] == 1
    assert receipt["deadline_expired"] is True and receipt["cleanup_verified"] is True


def test_reused_supervisor_spawn_failure_and_expired_admission(tmp_path):
    for timeout, expired in [(1, False), (0, True)]:
        receipt = harness.supervise(
            ["/nonexistent-chat02a-command"],
            env=harness.clean_env(),
            log=tmp_path / "spawn.log",
            timeout=timeout,
            cwd=ROOT,
        )
        assert receipt["actual_exit"] is None and receipt["wrapper_exit"] == 1
        assert receipt["deadline_expired"] is expired and receipt["spawned"] is False


def test_fixture_network_guard_denies_real_and_foreign_destinations(tmp_path, monkeypatch):
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    harness.install_fixture_network_guard(tmp_path)
    hook = hooks[0]
    with pytest.raises(RuntimeError):
        hook("socket.connect", (None, ("127.0.0.1", 49151)))
    harness.dump(tmp_path / "provider-origin.json", {"host": "127.0.0.1", "port": 49151})
    hook("socket.connect", (None, ("127.0.0.1", 49151)))
    hook("socket.getaddrinfo", ("127.0.0.1", 49151, 0, 0, 0))
    for address in (
        ("127.0.0.1", 11434),
        ("127.0.0.1", 5173),
        ("127.0.0.1", 5180),
        ("192.0.2.1", 49151),
        ("127.0.0.1", 49152),
    ):
        with pytest.raises(RuntimeError):
            hook("socket.connect", (None, address))


def test_parent_gate_refuses_concurrent_runner(tmp_path):
    path, _, source = admission(tmp_path)
    with (
        harness.parent_gate(path, source),
        pytest.raises(RuntimeError, match="already active"),
        harness.parent_gate(path, source),
    ):
        pytest.fail("second gate admitted")


@pytest.mark.parametrize("control", ["reason", "count", "hash", "unrequested"])
def test_correction_is_explicit_bound_and_does_not_reset_ledger(tmp_path, control):
    path, value, source = admission(tmp_path)
    harness.validate_admission(path, source)
    ledger = Path(value["ledger"])
    harness.debit(
        ledger, httpx2.Request("POST", harness.COMPLETIONS, json=harness.observer_payload())
    )
    before = ledger.read_bytes()
    value["correction"] = {
        "reason": "diagnosed observer only",
        "prior_dispatches": 1,
        "prior_ledger_sha256": harness.hashlib.sha256(before).hexdigest(),
    }
    if control == "reason":
        value["correction"]["reason"] = "different"
    if control == "count":
        value["correction"]["prior_dispatches"] = 0
    if control == "hash":
        value["correction"]["prior_ledger_sha256"] = "0" * 64
    harness.dump(path, value)
    with pytest.raises(RuntimeError):
        harness.validate_admission(
            path, source, None if control == "unrequested" else "diagnosed observer only"
        )
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
def test_native_provider_fixture_actual_http_bytes_and_shutdown(streaming):
    raw = '{ "kind" : "agent_profile" }'
    with harness.ProviderFixture(
        [harness.native("configuration_read", raw, "literal-native", streaming=streaming)]
    ) as provider:
        with httpx2.Client(trust_env=False, timeout=5) as client:
            response = client.post(provider.base_url + "/chat/completions", json={"messages": []})
        assert response.status_code == 200
        if streaming:
            assert response.content.endswith(b"data: [DONE]\n\n")
            data = json.loads(response.content.splitlines()[0][6:])
            call = data["choices"][0]["delta"]["tool_calls"][0]
        else:
            call = response.json()["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["arguments"] == raw and call["id"] == "literal-native"
        assert len(provider.requests) == 1
    assert provider.closed == provider.opened == 1 and not provider.thread.is_alive()


@pytest.mark.parametrize("mode", ["prepublication-failure", "postpublication-failure"])
def test_filesystem_fault_fixture_seam_really_fires(tmp_path, mode):
    state = tmp_path / "draft.json"
    original_fsync, original_replace = harness.os.fsync, harness.os.replace
    (tmp_path / "fault-arm").touch()
    try:
        harness.install_fault(tmp_path, state, mode)
        if mode == "prepublication-failure":
            with (tmp_path / ".ui-drafts-synthetic").open("wb") as stream:
                stream.write(b"SYNTHETIC")
                stream.flush()
                with pytest.raises(OSError):
                    harness.os.fsync(stream.fileno())
        else:
            fd = harness.os.open(tmp_path, harness.os.O_RDONLY | harness.os.O_DIRECTORY)
            try:
                with pytest.raises(OSError):
                    harness.os.fsync(fd)
            finally:
                harness.os.close(fd)
        assert json.loads((tmp_path / "fault-fired.json").read_text())["mode"] == mode
    finally:
        harness.os.fsync, harness.os.replace = original_fsync, original_replace


def test_sanitized_environment_is_absolute_and_offline(monkeypatch):
    for name in ("PGHOST", "PGPASSWORD", "DATABASE_URL", "OPENAI_API_KEY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "SYNTHETIC-not-for-child")
    env = harness.clean_env()
    assert env["PYTHONPATH"] == str(ROOT / "src")
    assert env["npm_config_offline"] == "true"
    for name in ("npm_config_update_notifier", "npm_config_audit", "npm_config_fund"):
        assert env[name] == "false"
    assert not {
        "PGHOST",
        "PGPASSWORD",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "HTTP_PROXY",
    }.intersection(env)
