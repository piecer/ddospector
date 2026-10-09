import asyncio
import json

import pytest

from aiddos.api.app import create_app

TARGET = {"name": "Lab", "address": "localhost", "kind": "DUT"}
LIMIT = 256 * 1024


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "http://localhost:5174",
        "http://localhost:5173.evil",
        "http://127.0.0.1:5173/",
        "http://localhost:5173/path",
        "https://localhost:5173",
    ],
)
def test_untrusted_origins_are_rejected_without_mutation(client, state_path, origin):
    response = client.post("/api/v1/targets", json=TARGET, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
    assert "access-control-allow-origin" not in response.headers
    assert not state_path.exists()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
@pytest.mark.parametrize("port", [5173, 5175, 5180, 5182])
def test_exact_development_origins_support_mutation_and_preflight(client, host, port):
    origin = f"http://{host}:{port}"
    preflight = client.options(
        "/api/v1/targets",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["vary"] == "Origin"
    assert "access-control-allow-credentials" not in preflight.headers
    response = client.post("/api/v1/targets", json=TARGET, headers={"Origin": origin})
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/plain",
        "application/x-www-form-urlencoded",
        "application/jsonp",
        "application/json; charset=utf-16",
    ],
)
def test_mutations_require_utf8_json(client, state_path, content_type):
    headers = {} if content_type is None else {"Content-Type": content_type}
    response = client.post("/api/v1/targets", content=json.dumps(TARGET), headers=headers)
    assert response.status_code == 415
    assert response.json()["code"] == "JSON_REQUIRED"
    assert not state_path.exists()


@pytest.mark.parametrize(
    "headers,code,status",
    [
        ({"Host": "evil.example"}, "HOST_NOT_ALLOWED", 403),
        ({"Sec-Fetch-Site": "cross-site"}, "ORIGIN_NOT_ALLOWED", 403),
        ({"Content-Encoding": "gzip"}, "UNSUPPORTED_ENCODING", 415),
        ({"Content-Length": "-1"}, "INVALID_FRAMING", 400),
        ({"Content-Length": "bad"}, "INVALID_FRAMING", 400),
        ({"Content-Length": str(LIMIT + 1)}, "BODY_TOO_LARGE", 413),
    ],
)
def test_transport_rejections_are_sanitized_and_have_no_writes(
    client, state_path, headers, code, status
):
    response = client.post("/api/v1/targets", json=TARGET, headers=headers)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert not state_path.exists()


@pytest.mark.parametrize(
    "body",
    [
        b'{"name":"first","name":"second","address":"localhost","kind":"DUT"}',
        b'{"goal":"Review","locale":"en","extra":{"x":1,"x":2}}',
        b'{"name": NaN}',
        b'{"name": Infinity}',
        b"\xff",
        b"{",
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_json_grammar_and_nesting_are_bounded_before_admission(client, state_path, body):
    response = client.post(
        "/api/v1/targets", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert not state_path.exists()


def test_body_byte_boundary_is_inclusive(client, state_path):
    raw = json.dumps(TARGET).encode()
    response = client.post(
        "/api/v1/targets",
        content=raw + b" " * (LIMIT - len(raw)),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 201
    before = state_path.read_bytes()
    response = client.post(
        "/api/v1/targets", content=b" " * (LIMIT + 1), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert state_path.read_bytes() == before


def asgi_request(app, chunks, headers, delay=0):
    messages = []
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        if delay:
            await asyncio.sleep(delay)
        if reads <= len(chunks):
            return {
                "type": "http.request",
                "body": chunks[reads - 1],
                "more_body": reads < len(chunks),
            }
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/targets",
        "raw_path": b"/api/v1/targets",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"), *headers],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    }
    asyncio.run(app(scope, receive, send))
    return messages, reads


def test_unexpected_failures_are_fixed_json_without_exception_text(client, state_path, monkeypatch):
    from aiddos.api.store import DraftStore

    def broken_snapshot(self):
        raise RuntimeError("private-secret /home/operator/storage.json")

    monkeypatch.setattr(DraftStore, "snapshot", broken_snapshot)
    response = client.get("/api/v1/workspace")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "The draft service could not complete the request.",
    }
    assert not state_path.exists()


def test_unknown_routes_methods_and_docs_have_sanitized_failures(client):
    assert client.get("/api/v1/missing").json().get("code") == "NOT_FOUND"
    assert (
        client.request("DELETE", "/api/v1/targets", json={}).json()["code"] == "METHOD_NOT_ALLOWED"
    )
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_empty_frame_flood_is_bounded_without_drain(state_path):
    messages, reads = asgi_request(create_app(state_path=state_path), [b""] * 4097, [])
    assert messages[0]["status"] == 413
    assert reads <= 4096
    assert not state_path.exists()


def test_body_receive_has_a_total_deadline(state_path, monkeypatch):
    from aiddos.api import boundary

    monkeypatch.setattr(boundary, "BODY_TIMEOUT_SECONDS", 0.01, raising=False)
    messages, reads = asgi_request(create_app(state_path=state_path), [b"{}"], [], delay=0.03)
    assert messages[0]["status"] == 408
    assert reads == 1
    assert not state_path.exists()


@pytest.mark.parametrize(
    "headers,expected_reads",
    [
        ([(b"content-length", str(LIMIT + 1).encode())], 0),
        ([], 2),
        ([(b"content-length", b"1")], 2),
        ([(b"transfer-encoding", b"chunked")], 2),
    ],
)
def test_asgi_body_limit_stops_reading_before_downstream_or_drain(
    state_path, headers, expected_reads
):
    messages, reads = asgi_request(
        create_app(state_path=state_path), [b" " * LIMIT, b"x", b"must-not-be-read"], headers
    )
    assert messages[0]["status"] == 413
    assert reads == expected_reads
    assert not state_path.exists()


@pytest.mark.parametrize(
    "headers",
    [
        [(b"origin", b"http://localhost:5173"), (b"origin", b"http://evil.example")],
        [(b"content-length", b"1"), (b"content-length", b"2")],
        [(b"transfer-encoding", b"gzip")],
        [(b"transfer-encoding", b"chunked"), (b"content-length", b"1")],
    ],
)
def test_ambiguous_framing_and_duplicate_security_headers_are_rejected_before_read(
    state_path, headers
):
    messages, reads = asgi_request(create_app(state_path=state_path), [b"{}"], headers)
    assert messages[0]["status"] in {400, 403}
    assert reads == 0
    assert not state_path.exists()
