import asyncio
import json
import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start

from aiddos.api.app import create_app


@contextmanager
def provider(payload, *, content_type="application/json", status=200, headers=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(
                {
                    "path": self.path,
                    "host": self.headers["Host"],
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                    "encoding": self.headers.get("Accept-Encoding"),
                }
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://localhost:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def submit(client, session, text="안녕\n  text ", expected_sequence=0, request_id=None):
    body = {
        "request_id": request_id or str(uuid4()),
        "expected_sequence": expected_sequence,
        "text": text,
    }
    return client.post(f"/api/v1/chat/sessions/{session['id']}/turns", json=body), body


def settled(client, app, turn):
    async def wait():
        task = app.state.chat.task
        if task is not None:
            async with asyncio.timeout(5):
                await asyncio.shield(task)

    client.portal.call(wait)
    result = client.get(f"/api/v1/chat/turns/{turn['id']}")
    assert result.status_code == 200, result.text
    return result.json()


def sse(*pieces, finish="stop", done=True):
    records = [b": heartbeat\r\n\r\n"]
    for piece in pieces:
        records.append(
            (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": piece, "reasoning_content": "PRIVATE"},
                                "finish_reason": None,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\r\n\r\n"
            ).encode()
        )
    records.append(
        (
            "data: "
            + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
            + "\n\n"
        ).encode()
    )
    if done:
        records.append(b"data: [DONE]\n\n")
    return b"".join(records)


def test_streamed_provider_and_authoritative_terminal_events(tmp_path):
    text = "한글😀" * 1024
    with provider(sse(text[:1000], text[1000:]), content_type="text/event-stream") as (
        url,
        requests,
    ):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=url)
            session = start(client)[0].json()
            result, _ = submit(client, session)
            turn = settled(client, app, result.json())
            assert turn["status"] == "succeeded", turn
            assert turn["assistant_text"] == text
            assert turn["revision"] >= 5
            events = client.get(f"/api/v1/chat/turns/{turn['id']}/events?after=1")
            assert events.status_code == 200
            records = events.text.split("\n\n")
            parsed = [
                json.loads(record.removeprefix("event: chat\ndata: "))
                for record in records
                if record
            ]
            assert parsed == [
                {
                    "schema_version": 1,
                    "turn_id": turn["id"],
                    "revision": turn["revision"],
                    "type": "snapshot",
                    "turn": turn,
                    "text": None,
                }
            ]
            assert "PRIVATE" not in events.text
        assert len(requests) == 1


@pytest.mark.parametrize(
    "payload,code,partial",
    [
        (sse("good", finish="length"), "CHAT_PROVIDER_PROTOCOL", "good"),
        (sse("good", done=False), "CHAT_PROVIDER_PROTOCOL", "good"),
        (sse(""), "CHAT_EMPTY_RESPONSE", ""),
        (
            b'data: {"choices":[{"index":0,"delta":{"content":false},"finish_reason":null}]}\n\n'
            + sse("good"),
            "CHAT_PROVIDER_PROTOCOL",
            "",
        ),
        (
            b'data: {"choices":[{"index":0,"delta":{"tool_calls":[]},"finish_reason":null}]}\n\n',
            "CHAT_PROVIDER_PROTOCOL",
            "",
        ),
        (b'data: {"choices":[],"choices":[]}\n\n', "CHAT_PROVIDER_PROTOCOL", ""),
        (b"data: \xff\n\n", "CHAT_PROVIDER_PROTOCOL", ""),
        (b"data: " + b"x" * 65537, "CHAT_OUTPUT_LIMIT", ""),
        (sse("good\x00"), "CHAT_PROVIDER_PROTOCOL", ""),
    ],
)
def test_provider_protocol_failures_are_fixed_and_retain_only_valid_partial(
    tmp_path, payload, code, partial
):
    with provider(payload, content_type="text/event-stream") as (url, requests):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=url)
            session = start(client)[0].json()
            turn = settled(client, app, submit(client, session)[0].json())
            assert turn["status"] == "failed", turn
            assert turn["error_code"] == code
            assert turn["assistant_text"] == partial
            assert turn["transport"] == "closed" and turn["provider_stop"] == "unknown"
        assert len(requests) == 1


def test_sse_unicode_separators_inside_json_are_text_not_framing():
    from aiddos.api.chat_transport import SSEParser

    text = "a\u0085b\u2028c\u2029d"
    parser = SSEParser()
    assert "".join(parser.feed(sse(text))) == text
    parser.end()


def test_parser_handles_every_byte_fragment_without_reasoning_leak():
    from aiddos.api.chat_transport import SSEParser

    parser = SSEParser()
    output = []
    for byte in sse("안녕😀\n", "end"):
        output.extend(parser.feed(bytes([byte])))
    parser.end()
    assert "".join(output) == "안녕😀\nend"


@pytest.mark.parametrize(
    "status,headers,code",
    [
        (302, {}, "CHAT_PROVIDER_ERROR"),
        (500, {}, "CHAT_PROVIDER_ERROR"),
        (200, {"Content-Encoding": "gzip"}, "CHAT_PROVIDER_PROTOCOL"),
    ],
)
def test_status_and_encoding_never_retry_or_reflect_provider(tmp_path, status, headers, code):
    with provider(b"PRIVATE PROVIDER FAILURE", status=status, headers=headers) as (url, requests):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=url, streaming=False)
            turn = settled(client, app, submit(client, start(client)[0].json())[0].json())
            assert turn["status"] == "failed" and turn["error_code"] == code
            assert "PRIVATE" not in json.dumps(turn)
        assert len(requests) == 1


def test_literal_transport_ignores_proxy_environment_and_never_resolves_dns(tmp_path, monkeypatch):
    import socket

    payload = json.dumps(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "pinned"},
                    "finish_reason": "stop",
                }
            ]
        }
    ).encode()
    with provider(payload) as (endpoint, requests):

        def forbidden(*args, **kwargs):
            raise AssertionError("DNS was called")

        monkeypatch.setattr(socket, "getaddrinfo", forbidden)
        monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:1")
        monkeypatch.setenv("ALL_PROXY", "http://192.0.2.2:1")
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(
                client,
                base_url=endpoint,
                streaming=False,
                max_tokens=32,
                max_tokens_field="max_completion_tokens",
            )
            turn = settled(client, app, submit(client, start(client)[0].json())[0].json())
            assert turn["status"] == "succeeded", turn
        assert len(requests) == 1
        assert requests[0]["body"]["max_completion_tokens"] == 32
        assert "max_tokens" not in requests[0]["body"]


@pytest.mark.parametrize(
    "choices",
    [
        [None],
        [
            {
                "index": False,
                "message": {"role": "assistant", "content": "invalid index"},
                "finish_reason": "stop",
            }
        ],
    ],
)
def test_nonstream_choices_are_strict_protocol(tmp_path, choices):
    with provider(json.dumps({"choices": choices}).encode()) as (url, requests):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=url, streaming=False)
            turn = settled(client, app, submit(client, start(client)[0].json())[0].json())
            assert turn["status"] == "failed" and turn["error_code"] == "CHAT_PROVIDER_PROTOCOL"
        assert len(requests) == 1


def test_reasoning_counts_toward_cumulative_upstream_budget(tmp_path):
    frame = (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {"index": 0, "delta": {"reasoning_content": "R" * 60000}, "finish_reason": None}
                ]
            }
        )
        + "\n\n"
    ).encode()
    with provider(frame * 36, content_type="text/event-stream") as (url, requests):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=url)
            turn = settled(client, app, submit(client, start(client)[0].json())[0].json())
            assert turn["status"] == "failed" and turn["error_code"] == "CHAT_OUTPUT_LIMIT"
            assert turn["assistant_text"] == ""
        assert len(requests) == 1


def test_default_transport_nonstream_turn_and_server_context(tmp_path):
    payload = json.dumps(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "실제 HTTP fixture",
                        "reasoning": "PRIVATE",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
    ).encode()
    with provider(payload) as (endpoint, requests):
        app = create_app(state_path=tmp_path / "draft.json")
        with TestClient(app, base_url="http://localhost") as client:
            configure(client, base_url=endpoint, streaming=False)
            session = start(client)[0].json()
            result, body = submit(client, session)
            assert result.status_code == 202, result.text
            turn = settled(client, app, result.json())
            assert turn["status"] == "succeeded" and turn["assistant_text"] == "실제 HTTP fixture"
            assert turn["transport"] == "closed" and turn["provider_stop"] == "unknown"
            assert "PRIVATE" not in json.dumps(turn)
            again = client.post(f"/api/v1/chat/sessions/{session['id']}/turns", json=body)
            assert again.status_code == 200 and again.json() == turn
            assert client.get(f"/api/v1/chat/turns/by-request/{body['request_id']}").json() == turn
            result2, _ = submit(client, session, text="follow up", expected_sequence=1)
            assert settled(client, app, result2.json())["status"] == "succeeded"
            history = client.get(f"/api/v1/chat/sessions/{session['id']}").json()
            assert [t["sequence"] for t in history["turns"]] == [1, 2]
        assert len(requests) == 2
        first, second = [r["body"] for r in requests]
        assert first["model"] == "fixture-model" and first["stream"] is False
        assert "max_tokens" not in first and "max_completion_tokens" not in first
        assert first["messages"][-1] == {"role": "user", "content": body["text"]}
        assert second["messages"][1:] == [
            first["messages"][-1],
            {"role": "assistant", "content": "실제 HTTP fixture"},
            {"role": "user", "content": "follow up"},
        ]
        assert all(
            r["host"] == endpoint.removeprefix("http://").removesuffix("/v1")
            and r["encoding"] == "identity"
            for r in requests
        )
