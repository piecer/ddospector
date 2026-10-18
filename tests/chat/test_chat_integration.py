"""CHAT-01 black-box API/protocol: actual uvicorn + owned synthetic HTTP provider.

Run explicitly: pytest tests/chat/test_chat_integration.py (not in baseline testpaths).
No PostgreSQL, Docker, ASGI response replacement, credentials, or real model calls.
"""

import json
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests/chat"))
from chat_acceptance import bootstrap, http, launch_api  # noqa: E402
from provider_fixture import ProviderFixture, Scenario, sse  # noqa: E402

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
TURN_KEYS = set(
    [
        "schema_version",
        "id",
        "request_id",
        "session_id",
        "sequence",
        "revision",
        "status",
        "user_text",
        "assistant_text",
        "error_code",
        "transport",
        "provider_stop",
        "created_at",
        "finished_at",
    ]
)


class Product:
    def __init__(self, directory):
        self.directory = directory
        self.state = directory / "draft.json"
        self.child, self.base = launch_api(self.state, directory)

    def request(self, path, method="GET", body=None):
        return http(self.base, path, method, body)

    def restart(self, *, crash=False):
        self.child.stop(crash=crash)
        self.child, self.base = launch_api(self.state, self.directory)


@pytest.fixture
def product(tmp_path):
    app = Product(tmp_path)
    try:
        yield app
    finally:
        app.child.stop()
        assert app.child.cleaned


def test_chat_runtime_route_is_real(product):
    status, body = product.request("/api/v1/chat/runtime")
    assert status == 200, (status, body)
    assert body["schema_version"] == 1
    assert body["mode"] == "chat_only"
    assert body["configuration_tools"] is False
    assert body["live_execution"] is False
    assert body["mcp_execution"] is False


def session(product, provider, *, streaming=True):
    saved = bootstrap(
        product.base, provider.base_url, "SYNTHETIC-fixture-only", streaming=streaming
    )
    status, runtime = product.request("/api/v1/chat/runtime")
    assert status == 200, (status, runtime)
    assert runtime["supported"] is True
    assert runtime["profile"]["id"] == saved["agent_profile_id"]  # B1 prefixed identity
    body = {
        "request_id": str(uuid4()),
        "settings_revision": runtime["settings_revision"],
        "profile_id": runtime["profile"]["id"],
        "approved_endpoint": runtime["profile"]["endpoint"],
        "locale": "ko",
    }
    status, created = product.request("/api/v1/chat/sessions", "POST", body)
    assert status == 201, (status, created)
    assert UUID(created["id"]).version == 4
    assert created["profile_id"] == saved["agent_profile_id"]
    assert product.request("/api/v1/chat/sessions", "POST", body) == (200, created)
    assert not provider.requests
    return created


def submit(product, saved, text="SYNTHETIC user: 안녕", sequence=0, request_id=None):
    body = {"request_id": request_id or str(uuid4()), "expected_sequence": sequence, "text": text}
    status, turn = product.request(f"/api/v1/chat/sessions/{saved['id']}/turns", "POST", body)
    assert status == 202, (status, turn)
    assert set(turn) == TURN_KEYS
    return turn, body


def read_turn(product, turn):
    status, found = product.request(f"/api/v1/chat/turns/{turn['id']}")
    assert status == 200, (status, found)
    assert set(found) == TURN_KEYS
    return found


def wait_turn(product, turn, predicate=lambda value: value["status"] in TERMINAL, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read_turn(product, turn)
        if predicate(value):
            return value
        time.sleep(0.03)
    raise AssertionError(f"turn condition deadline: {value['status']}")


def events(product, turn):
    """Independent wire observer: strict UTF-8, finite stream, snapshot/delta conservation."""
    result = []
    total = 0
    with (
        httpx2.Client(trust_env=False, timeout=15) as client,
        client.stream("GET", product.base + f"/api/v1/chat/turns/{turn['id']}/events") as res,
    ):
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        assert "no-store" in res.headers["cache-control"]
        pending = b""
        for chunk in res.iter_bytes():
            total += len(chunk)
            assert total <= 2 * 1024 * 1024
            pending += chunk
            while b"\n\n" in pending:
                frame, pending = pending.split(b"\n\n", 1)
                if frame.startswith(b":"):
                    continue
                assert len(frame) <= 1048576 + 128
                lines = frame.decode("utf-8", errors="strict").splitlines()
                assert "event: chat" in lines
                data = [line[6:] for line in lines if line.startswith("data: ")]
                assert len(data) == 1
                result.append(json.loads(data[0]))
            assert len(pending) <= 1048576 + 128
        assert not pending.strip()
    assert result and result[0]["type"] == "snapshot"
    current = None
    for event in result:
        assert set(event) == {"schema_version", "turn_id", "revision", "type", "turn", "text"}
        assert event["schema_version"] == 1 and event["turn_id"] == turn["id"]
        if current:
            assert event["revision"] == current["revision"] + 1
        if event["type"] == "snapshot":
            assert event["text"] is None
            assert event["revision"] == event["turn"]["revision"]
            current = dict(event["turn"])
        else:
            assert event["type"] == "delta" and current is not None
            assert event["turn"] is None
            assert 0 < len(event["text"].encode()) <= 4096
            current["assistant_text"] += event["text"]
            current["revision"] = event["revision"]
    assert result[-1]["type"] == "snapshot" and current["status"] in TERMINAL
    assert read_turn(product, turn) == current
    return result, current


def test_stream_context_idempotency_and_history(product):
    replies = ["SYNTHETIC 첫 답변 🌍", "SYNTHETIC follow-up", "SYNTHETIC third"]
    with ProviderFixture([Scenario.text(text, split=1) for text in replies]) as provider:
        saved = session(product, provider)
        turns = []
        for seq, reply in enumerate(replies):
            turn, body = submit(product, saved, text=f"SYNTHETIC user {seq}", sequence=seq)
            observed, final = events(product, turn)
            assert final["status"] == "succeeded" and final["assistant_text"] == reply
            assert final["transport"] == "closed" and final["provider_stop"] == "unknown"
            assert final["error_code"] is None
            status, replay = product.request(
                f"/api/v1/chat/sessions/{saved['id']}/turns", "POST", body
            )
            assert status == 200 and replay["id"] == final["id"]
            assert product.request(f"/api/v1/chat/turns/by-request/{body['request_id']}") == (
                200,
                final,
            )
            turns.append(final)
        assert len(provider.requests) == 3
        messages = provider.requests[1]["body"]["messages"]
        assert messages[-3:] == [
            {"role": "user", "content": "SYNTHETIC user 0"},
            {"role": "assistant", "content": replies[0]},
            {"role": "user", "content": "SYNTHETIC user 1"},
        ]
        assert messages[0]["role"] == "system" and messages[0]["content"]
        assert provider.requests[0]["body"]["max_tokens"] == 512
        product.restart()
        status, history = product.request(f"/api/v1/chat/sessions/{saved['id']}")
        assert status == 200 and history["turns"] == turns[1:]
        assert history["next_before_sequence"] == 2
        status, older = product.request(f"/api/v1/chat/sessions/{saved['id']}?before_sequence=2")
        assert status == 200 and older["turns"] == turns[:1]
        assert older["next_before_sequence"] is None
        assert len(provider.requests) == 3


@pytest.mark.parametrize(
    "scenario,code",
    [
        (Scenario.text(terminal=False), "CHAT_PROVIDER_PROTOCOL"),
        (Scenario((b"data: " + b"x" * 65537 + b"\n\n",)), "CHAT_OUTPUT_LIMIT"),
        (Scenario((b"data: \xff\n\n",)), "CHAT_PROVIDER_PROTOCOL"),
        (Scenario((b"SYNTHETIC upstream unavailable",), status=503), "CHAT_PROVIDER_ERROR"),
        (Scenario((sse("SYNTHETIC partial"), sse(finish="length"))), "CHAT_PROVIDER_PROTOCOL"),
    ],
)
def test_provider_failure_is_not_success(product, scenario, code):
    with ProviderFixture([scenario]) as provider:
        saved = session(product, provider)
        turn, _ = submit(product, saved)
        final = wait_turn(product, turn)
        assert final["status"] == "failed"
        assert final["error_code"] == code
        assert final["transport"] == "closed" and final["provider_stop"] == "unknown"
        provider.wait_closed()
        assert len(provider.requests) == 1


def test_single_response_has_no_fabricated_deltas(product):
    text = "SYNTHETIC nonstream 응답"
    wire = json.dumps(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ]
        }
    ).encode()
    with ProviderFixture([Scenario((wire,), content_type="application/json")]) as provider:
        saved = session(product, provider, streaming=False)
        turn, _ = submit(product, saved)
        observed, final = events(product, turn)
        assert all(event["type"] == "snapshot" for event in observed)
        assert final["status"] == "succeeded" and final["assistant_text"] == text
        assert provider.requests[0]["body"]["stream"] is False


def test_stop_closes_local_transport_without_remote_stop_claim(product):
    with ProviderFixture([Scenario.slow()]) as provider:
        saved = session(product, provider)
        turn, _ = submit(product, saved)
        partial = wait_turn(product, turn, lambda value: bool(value["assistant_text"]))
        status, _ = product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})
        assert status == 200
        final = wait_turn(product, turn)
        assert final["status"] == "cancelled" and final["error_code"] == "CHAT_CANCELLED"
        assert final["assistant_text"].startswith(partial["assistant_text"])
        assert final["transport"] == "closed" and final["provider_stop"] == "unknown"
        provider.wait_closed()
        assert provider.peer_closed == 1 and len(provider.requests) == 1


def test_crash_recovers_committed_partial_without_retry(product):
    with ProviderFixture([Scenario.slow()]) as provider:
        saved = session(product, provider)
        turn, _ = submit(product, saved)
        partial = wait_turn(product, turn, lambda value: bool(value["assistant_text"]))
        product.restart(crash=True)
        final = read_turn(product, turn)
        assert final["status"] == "interrupted" and final["error_code"] == "CHAT_INTERRUPTED"
        assert final["assistant_text"] == partial["assistant_text"]
        assert final["revision"] == partial["revision"] + 1
        assert final["transport"] == "unknown" and final["provider_stop"] == "unknown"
        assert final["finished_at"]
        provider.wait_closed()
        assert len(provider.requests) == 1
        status, history = product.request(f"/api/v1/chat/sessions/{saved['id']}")
        assert status == 200 and history["session"]["active_turn_id"] is None


def test_missing_history_reads_do_not_create_storage(product):
    assert product.request("/api/v1/chat/sessions") == (200, {"schema_version": 1, "sessions": []})
    status, body = product.request(f"/api/v1/chat/turns/{uuid4()}")
    assert status == 404 and body["code"] == "CHAT_NOT_FOUND"
    assert not list(product.directory.glob("draft.chat*"))


def test_output_limit_retains_failed_partial(product):
    chunks = tuple(sse("SYNTHETIC-" + "x" * 1014) for _ in range(65))
    with ProviderFixture([Scenario(chunks + (sse(finish="stop"),))]) as provider:
        saved = session(product, provider)
        turn, _ = submit(product, saved)
        final = wait_turn(product, turn)
        assert final["status"] == "failed" and final["error_code"] == "CHAT_OUTPUT_LIMIT"
        assert 0 < len(final["assistant_text"].encode()) <= 65536
        assert len(provider.requests) == 1


def test_provider_idle_timeout_is_not_terminal_success(product):
    scenario = Scenario((sse("SYNTHETIC timeout partial " * 16), sse(finish="stop")), (0, 35))
    with ProviderFixture([scenario]) as provider:
        saved = session(product, provider)
        turn, _ = submit(product, saved)
        final = wait_turn(product, turn, timeout=40)
        assert final["status"] == "failed" and final["error_code"] == "CHAT_TIMEOUT"
        assert final["assistant_text"] and final["transport"] == "closed"
        provider.wait_closed()
        assert len(provider.requests) == 1


def test_legacy_preview_and_live_denials_do_not_dispatch(product):
    with ProviderFixture([Scenario.text()]) as provider:
        bootstrap(product.base, provider.base_url, "SYNTHETIC-fixture-only")
        body = {"goal": "SYNTHETIC preview only", "locale": "en"}
        first = product.request("/api/v1/agent/preview", "POST", body)
        assert first[0] == 200 and first[1]["origin"] == "deterministic_context_preview"
        assert product.request("/api/v1/agent/preview", "POST", body) == first
        for path, code in (
            ("runs", "LIVE_NOT_AVAILABLE"),
            ("agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"),
            ("ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"),
        ):
            status, value = product.request(f"/api/v1/{path}", "POST", {})
            assert status >= 400 and value["code"] == code
        assert not provider.requests
