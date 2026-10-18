"""Harness-only controls, never product acceptance or real provider inference."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests/chat"))
import chat_acceptance as harness  # noqa: E402
from provider_fixture import ProviderFixture, Scenario  # noqa: E402


def test_sanitized_environment_drops_database_and_credentials(monkeypatch):
    for key in ("PGHOST", "PGPASSWORD", "DATABASE_URL", "DSN", "OPENAI_API_KEY", "HTTP_PROXY"):
        monkeypatch.setenv(key, "not-for-child")
    env = harness.clean_env()
    assert env["PYTHONPATH"] == str(ROOT / "src")
    assert env["npm_config_offline"] == "true"
    assert env["npm_config_update_notifier"] == "false"
    assert not any(
        key.startswith("PG")
        or key
        in (
            "DSN",
            "DATABASE_URL",
            "OPENAI_API_KEY",
            "HTTP_PROXY",
        )
        for key in env
    )


@pytest.mark.parametrize("code,expected", [("pass", 0), ("raise SystemExit(7)", 7)])
def test_supervisor_preserves_actual_exit_and_reaps(tmp_path, code, expected):
    receipt = harness.supervise(
        [sys.executable, "-c", code], env=harness.clean_env(), log=tmp_path / "child.log", timeout=3
    )
    assert receipt["actual_exit"] == expected
    assert receipt["wrapper_exit"] == (0 if expected == 0 else 1)
    assert receipt["deadline_expired"] is False
    assert receipt["cleanup_verified"] is True
    assert harness.identity(receipt["identity"]["pid"]) is None


def test_deadline_latched_even_when_child_exits_zero_on_sigterm(tmp_path):
    code = (
        "import signal,time; signal.signal(signal.SIGTERM, lambda *_: exit(0)); "
        "print('ready',flush=True); time.sleep(10)"
    )
    receipt = harness.supervise(
        [sys.executable, "-c", code],
        env=harness.clean_env(),
        log=tmp_path / "child.log",
        timeout=0.3,
    )
    assert "ready" in (tmp_path / "child.log").read_text()
    assert receipt["actual_exit"] == 0
    assert receipt["deadline_expired"] is True and receipt["wrapper_exit"] == 1
    assert receipt["cleanup_verified"] is True


def test_ignored_sigterm_gets_bounded_kill(tmp_path):
    code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    receipt = harness.supervise(
        [sys.executable, "-c", code],
        env=harness.clean_env(),
        log=tmp_path / "child.log",
        timeout=0.3,
    )
    assert receipt["actual_exit"] == -9
    assert receipt["deadline_expired"] is True and receipt["wrapper_exit"] == 1
    assert receipt["cleanup_verified"] is True


def test_pid_starttime_mismatch_is_not_signalled(tmp_path, monkeypatch):
    child = harness.OwnedProcess(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        env=harness.clean_env(),
        log=tmp_path / "child.log",
    )
    original = harness.identity
    original_kill = os.kill
    signalled = []
    try:
        monkeypatch.setattr(
            harness,
            "identity",
            lambda pid: (
                {
                    **original(pid),
                    "starttime": "different-owner",
                }
                if original(pid)
                else None
            ),
        )
        monkeypatch.setattr(os, "kill", lambda pid, sig: signalled.append((pid, sig)))
        monkeypatch.setattr(
            child.process,
            "wait",
            lambda timeout: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("mismatched-owner", timeout)
            ),
        )
        with pytest.raises(subprocess.TimeoutExpired):
            child.stop()
        assert not signalled
    finally:
        monkeypatch.undo()
        original_kill(child.process.pid, 9)
        child.process.wait(timeout=3)
        child.log.close()


def test_occupied_ports_are_not_adopted():
    with harness.reserved_port() as owned:
        port = owned.getsockname()[1]
        with pytest.raises(OSError), harness.reserved_port(port):
            pytest.fail("occupied port accepted")
    with pytest.raises(ValueError), harness.reserved_port(5173):
        pass
    with pytest.raises(ValueError), harness.reserved_port(5180):
        pass


def test_real_mode_requires_explicit_flag_before_any_launch(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/chat_acceptance.py"),
            "--mode",
            "real",
            "--artifacts",
            str(tmp_path / "denied"),
        ],
        cwd=ROOT,
        env=harness.clean_env(),
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert b"requires explicit --allow-real-model" in result.stderr
    assert not (tmp_path / "denied").exists()


def test_finite_dispatch_guard_binds_endpoint_model_options_and_deadline(tmp_path):
    ledger = tmp_path / "ledger.json"
    harness.dump(ledger, [])
    payload = {"model": harness.MODEL, "stream": True, "max_tokens": 512, "messages": []}
    endpoint = harness.ENDPOINT + "/chat/completions"
    for patch in ({"model": "wrong"}, {"stream": False}, {"max_tokens": 513}):
        with pytest.raises(RuntimeError):
            harness.debit(ledger, 4, time.monotonic() + 10, endpoint, {**payload, **patch})
    with pytest.raises(RuntimeError):
        harness.debit(ledger, 4, time.monotonic() + 10, endpoint, payload, authorization=True)
    with pytest.raises(RuntimeError):
        harness.debit(ledger, 4, time.monotonic() - 1, endpoint, payload)
    with pytest.raises(RuntimeError):
        harness.debit(ledger, 4, time.monotonic() + 10, "http://example.invalid/v1", payload)
    assert json.loads(ledger.read_text()) == []
    for _ in range(4):
        harness.debit(ledger, 4, time.monotonic() + 10, endpoint, payload)
    with pytest.raises(RuntimeError, match="exhausted"):
        harness.debit(ledger, 4, time.monotonic() + 10, endpoint, payload)
    assert len(json.loads(ledger.read_text())) == 4  # bookkeeping only: zero sockets opened


@pytest.fixture
def installed_dispatch_observer(tmp_path, monkeypatch):
    """Install serve_api's real wrapper without a server or permanent audit hook."""
    import uvicorn

    ledger = tmp_path / "observer-ledger.json"
    harness.dump(ledger, [])
    monkeypatch.setenv("CHAT_ACCEPTANCE_LEDGER", str(ledger))
    monkeypatch.setenv("CHAT_ACCEPTANCE_LIMIT", "4")
    monkeypatch.setenv("CHAT_ACCEPTANCE_DEADLINE", str(time.monotonic() + 60))
    monkeypatch.setenv("DDOSPECTOR_UI_STATE_PATH", str(tmp_path / "draft.json"))
    hooks, launches, forwarded = [], [], []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: launches.append((a, kw)))

    def no_network(*_args, **_kwargs):
        pytest.fail("observer selftest attempted a real socket connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    original_send = httpx2.AsyncClient.send

    async def captured_send(client, request, *args, **kwargs):
        # This is the boundary BEFORE the installed underlying send/transport.
        rows = json.loads(ledger.read_text())
        assert len(rows) == 1
        assert rows[0]["dispatch"] == 1
        assert rows[0]["endpoint"] == str(request.url)
        assert rows[0]["request"] == json.loads(request.content)
        assert isinstance(rows[0]["monotonic"], float)
        assert args == () and kwargs["stream"] is True
        forwarded.append(request)
        return await original_send(client, request, *args, **kwargs)

    # serve_api assigns send directly, so restore it explicitly even on RED.
    httpx2.AsyncClient.send = captured_send
    try:
        harness.serve_api(123)
        assert len(hooks) == len(launches) == 1
        assert launches[0][1] == {"fd": 123, "log_level": "warning", "timeout_graceful_shutdown": 2}
        assert httpx2.AsyncClient.send is not captured_send
        yield ledger, hooks[0], forwarded
    finally:
        httpx2.AsyncClient.send = original_send
        assert httpx2.AsyncClient.send is original_send


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
@pytest.mark.parametrize("transport_fails", [False, True])
def test_installed_observer_stream_debits_before_send_and_scopes_audit(
    installed_dispatch_observer, host, transport_fails
):
    ledger, audit, forwarded = installed_dispatch_observer
    endpoint = f"http://{host}:11434/v1/chat/completions"
    payload = {"model": harness.MODEL, "stream": True, "max_tokens": 512, "messages": []}
    transported = []
    failure = RuntimeError("SYNTHETIC transport failure")

    def denied(address):
        with pytest.raises(RuntimeError, match="unobserved or unapproved outbound connection"):
            audit("socket.connect", (None, address))

    def transport(request):
        assert forwarded == [request]
        assert request.method == "POST" and str(request.url) == endpoint
        assert json.loads(request.content) == payload
        audit("socket.connect", (None, ("127.0.0.1", 11434)))
        for address in (("127.0.0.1", 11435), ("192.0.2.1", 11434), ("::1", 11434, 0, 0)):
            denied(address)
        transported.append(request)
        if transport_fails:
            raise failure
        return httpx2.Response(200, content=b"SYNTHETIC response")

    async def run():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(transport), trust_env=False
        ) as client:
            denied(("127.0.0.1", 11434))
            try:
                async with client.stream("POST", endpoint, json=payload) as response:
                    assert response.status_code == 200
                    assert await response.aread() == b"SYNTHETIC response"
                assert response.is_closed
            finally:
                denied(("127.0.0.1", 11434))

    if transport_fails:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(run())
        assert caught.value is failure
    else:
        asyncio.run(run())
    assert len(forwarded) == len(transported) == len(json.loads(ledger.read_text())) == 1
    audit("unrelated.event", ())


@pytest.mark.parametrize(
    "case,message",
    [
        ("endpoint", "unapproved real-model binding"),
        ("model", "unapproved real-model binding"),
        ("authorization", "unapproved real-model binding"),
        ("stream", "unapproved real-model options"),
        ("max_tokens", "unapproved real-model options"),
        ("expired", "aggregate real-model deadline expired"),
        ("full", "finite dispatch allowance exhausted"),
    ],
)
def test_installed_observer_stream_rejects_without_forward_or_debit(
    installed_dispatch_observer, monkeypatch, case, message
):
    ledger, audit, forwarded = installed_dispatch_observer
    endpoint = harness.ENDPOINT + "/chat/completions"
    payload = {"model": harness.MODEL, "stream": True, "max_tokens": 512, "messages": []}
    headers = {}
    if case == "endpoint":
        endpoint = "http://example.invalid/v1/chat/completions"
    elif case == "model":
        payload["model"] = "unapproved-model"
    elif case == "authorization":
        headers["Authorization"] = "SYNTHETIC denied credential"
    elif case == "stream":
        payload["stream"] = False
    elif case == "max_tokens":
        payload["max_tokens"] = 513
    elif case == "expired":
        monkeypatch.setenv("CHAT_ACCEPTANCE_DEADLINE", str(time.monotonic() - 1))
    elif case == "full":
        for _ in range(4):
            harness.debit(ledger, 4, time.monotonic() + 60, endpoint, payload)
    before = ledger.read_bytes()

    def forbidden_transport(_request):
        pytest.fail("denied request reached transport")

    async def run():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(forbidden_transport), trust_env=False
        ) as client:
            with pytest.raises(RuntimeError, match=message):
                async with client.stream("POST", endpoint, json=payload, headers=headers):
                    pytest.fail("denied request returned a response")

    asyncio.run(run())
    assert forwarded == []
    assert ledger.read_bytes() == before
    with pytest.raises(RuntimeError, match="unobserved or unapproved outbound connection"):
        audit("socket.connect", (None, ("127.0.0.1", 11434)))


def test_default_parser_has_no_model_admission():
    source = (ROOT / "tools/chat_acceptance.py").read_text()
    assert 'default="preflight"' in source
    assert 'args.mode == "real" and not args.allow_real_model' in source


def test_profile_is_fresh_supported_and_does_not_inherit_caller_options():
    first = harness.profile(harness.ENDPOINT)
    second = harness.profile(harness.ENDPOINT)
    assert first["id"] != second["id"] and first["id"].startswith("llm-")
    assert first["model"] == harness.MODEL and first["credential_env"] == ""
    assert first["streaming"] and first["max_tokens"] == 512
    assert first["reasoning_effort"] == first["thinking_type"] == ""
    assert all(rule["attempts"] == 0 for rule in first["retry"].values())


def test_fixture_real_http_one_byte_chunks_preserves_multibyte_utf8():
    text = "SYNTHETIC 한글 🌍"
    with ProviderFixture([Scenario.text(text, split=1)]) as provider:
        with httpx2.Client(trust_env=False) as client:
            response = client.post(provider.base_url + "/chat/completions", json={"fixture": True})
        assert response.status_code == 200
        assert text in response.content.decode("utf-8", errors="strict")
        assert response.content.endswith(b"data: [DONE]\n\n")
        provider.wait_closed()
        assert provider.opened == provider.closed == len(provider.requests) == 1


@pytest.mark.parametrize(
    "scenario,status,marker",
    [
        (Scenario.text(terminal=False), 200, b"SYNTHETIC"),
        (Scenario((b"SYNTHETIC failure",), status=503), 503, b"failure"),
        (Scenario((b"x" * 65537,)), 200, b"x" * 65537),
        (Scenario((b"data: \xff\n\n",)), 200, b"\xff"),
    ],
)
def test_fixture_malformed_and_failure_modes_are_genuine_http(scenario, status, marker):
    with ProviderFixture([scenario]) as provider:
        with httpx2.Client(trust_env=False) as client:
            response = client.post(provider.base_url + "/chat/completions", json={"fixture": True})
        assert response.status_code == status
        assert marker in response.content
        assert b"[DONE]" not in response.content
        provider.wait_closed()


def test_fixture_cancel_detects_closed_peer_during_delay():
    with ProviderFixture([Scenario.slow()]) as provider:
        with (
            httpx2.Client(trust_env=False) as client,
            client.stream(
                "POST", provider.base_url + "/chat/completions", json={"fixture": True}
            ) as response,
        ):
            assert b"SYNTHETIC partial" in next(response.iter_bytes())
        provider.wait_closed()
        assert provider.peer_closed == 1


def test_fixture_caps_request_and_wire_budgets():
    with pytest.raises(ValueError):
        Scenario((b"x" * (3 * 1024 * 1024 + 1),))
    with pytest.raises(ValueError):
        Scenario((b"x",), (126,))
    with ProviderFixture([Scenario.text()]) as provider:
        with httpx2.Client(trust_env=False) as client:
            assert (
                client.post(
                    provider.base_url + "/chat/completions", json={"fixture": True}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    provider.base_url + "/chat/completions", json={"fixture": True}
                ).status_code
                == 429
            )
        provider.wait_closed(count=2)
        assert len(provider.requests) == 1


def test_delayed_observer_cannot_publish_success_after_deadline(tmp_path):
    receipt = harness.supervise(
        [sys.executable, "-c", "import time; time.sleep(.1)"],
        env=harness.clean_env(),
        log=tmp_path / "late.log",
        timeout=0.2,
        tick=lambda: time.sleep(0.3),
    )
    assert receipt["actual_exit"] == 0
    assert receipt["deadline_expired"] is True
    assert receipt["wrapper_exit"] == 1


def test_spawn_failure_and_expired_admission_have_no_child(tmp_path):
    for command, timeout, expired in (
        (["/nonexistent/chat-harness-binary"], 1, False),
        ([sys.executable, "-c", "raise SystemExit(9)"], 0, True),
    ):
        receipt = harness.supervise(
            command, env=harness.clean_env(), log=tmp_path / "spawn.log", timeout=timeout
        )
        assert receipt["actual_exit"] is None and receipt["spawned"] is False
        assert receipt["deadline_expired"] is expired
        assert receipt["wrapper_exit"] == 1 and receipt["cleanup_verified"] is True


def test_receipt_write_failure_still_reaps_child(tmp_path, monkeypatch):
    children = []
    original = harness.OwnedProcess

    def tracked(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    def fail_receipt(*_args):
        raise OSError("SYNTHETIC receipt write failure")

    monkeypatch.setattr(harness, "OwnedProcess", tracked)
    monkeypatch.setattr(harness, "dump", fail_receipt)
    with pytest.raises(OSError, match="receipt write failure"):
        harness.supervise(
            [sys.executable, "-c", "pass"],
            env=harness.clean_env(),
            log=tmp_path / "receipt.log",
            timeout=2,
        )
    assert len(children) == 1 and children[0].cleaned
    assert harness.identity(children[0].process.pid) is None


def test_owned_subprocess_tree_is_cleaned(tmp_path):
    owner_file = tmp_path / "detached-child.json"
    script = (
        "import subprocess,sys,time,json; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], "
        "start_new_session=True); "
        "start=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]; "
        f"Path({str(owner_file)!r}).write_text(json.dumps(dict(pid=p.pid,starttime=start))); "
        "time.sleep(30)"
    )
    try:
        receipt = harness.supervise(
            [sys.executable, "-c", script],
            env=harness.clean_env(),
            log=tmp_path / "tree.log",
            timeout=0.4,
        )
        assert receipt["deadline_expired"] and receipt["cleanup_verified"]
        assert len(receipt["owned_members"]) >= 2
        for owner in receipt["owned_members"]:
            current = harness.identity(owner["pid"])
            assert (
                not current or current["starttime"] != owner["starttime"] or current["state"] == "Z"
            )
    finally:
        # The regression's RED must not leak the deliberately detached child.
        if owner_file.exists():
            owner = json.loads(owner_file.read_text())
            current = harness.identity(owner["pid"])
            if current and current["starttime"] == owner["starttime"] and current["state"] != "Z":
                os.kill(owner["pid"], 9)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    current = harness.identity(owner["pid"])
                    if not current or current["state"] == "Z":
                        break
                    time.sleep(0.01)
                assert not current or current["state"] == "Z"


def test_plain_socket_fixture_cleanup():
    with ProviderFixture([Scenario.text()]) as provider:
        port = provider.server.server_port
        connection = socket.create_connection(("127.0.0.1", port), timeout=1)
        connection.close()
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
