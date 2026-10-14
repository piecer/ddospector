"""In-process B1 boundary proofs; no evidence routes, DB, or PCAP dependencies."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from aiddos.api import boundary

ROOT = "/api/v1/evidence"


class Exchange:
    def __init__(self, *, path=ROOT, method="POST", body=b"{}", headers=()):
        self.scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"), *headers],
        }
        self.body = body
        self.reads = 0
        self.messages = []
        self.receiving = asyncio.Event()
        self.body_gate: asyncio.Event | None = None
        self.frames: list[dict] | None = None
        self.sending = asyncio.Event()
        self.send_gate: asyncio.Event | None = None
        self.send_type = "http.response.body"
        self.send_failure: Exception | None = None

    async def receive(self):
        self.reads += 1
        self.receiving.set()
        if self.body_gate is not None:
            await self.body_gate.wait()
        if self.frames is not None:
            return self.frames[self.reads - 1]
        return {"type": "http.request", "body": self.body, "more_body": False}

    async def send(self, message):
        self.messages.append(message)
        if message["type"] == self.send_type:
            self.sending.set()
            if self.send_gate is not None:
                await self.send_gate.wait()
            if self.send_failure is not None:
                raise self.send_failure

    async def run(self, app):
        await app(self.scope, self.receive, self.send)

    @property
    def status(self):
        return self.messages[0]["status"]

    @property
    def payload(self):
        return json.loads(b"".join(m.get("body", b"") for m in self.messages))


class Downstream:
    """Observer stands in for the future handler and its DB-admission call."""

    def __init__(self):
        self.calls = 0
        self.db_calls = 0
        self.bodies = []
        self.entered = asyncio.Event()
        self.gate: asyncio.Event | None = None
        self.failure: Exception | None = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        self.bodies.append((await receive())["body"])
        self.db_calls += 1
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


@asynccontextmanager
async def running(exchange, app):
    task = asyncio.create_task(exchange.run(app))
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.done()


def observe_decode(monkeypatch):
    calls = []
    original = boundary.strict_json

    def observed(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr(boundary, "strict_json", observed)
    return calls


async def assert_busy(app, downstream, decodes, **kwargs):
    before = (len(decodes), downstream.calls, downstream.db_calls)
    second = Exchange(**kwargs)
    await second.run(app)
    assert second.status == 429
    assert second.payload == {
        "code": "EVIDENCE_BUSY",
        "message": "Another evidence upload is in progress.",
    }
    assert second.reads == 0
    assert (len(decodes), downstream.calls, downstream.db_calls) == before
    assert (b"cache-control", b"no-store") in second.messages[0]["headers"]
    return second


async def assert_admitted(app, downstream):
    before = downstream.calls
    later = Exchange()
    await later.run(app)
    assert later.status == 200
    assert later.reads == 1
    assert downstream.calls == before + 1


def test_second_post_is_rejected_before_receive_while_first_body_stalls(monkeypatch):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app) as task:
            await first.receiving.wait()
            assert first.reads == 1
            assert not decodes and downstream.calls == downstream.db_calls == 0
            await assert_busy(app, downstream, decodes)
            first.body_gate.set()
            await task
            assert first.status == 200
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "TRACE", "CUSTOM"])
@pytest.mark.parametrize("path", [ROOT, ROOT + "/", ROOT + "/unknown/nested"])
def test_unsupported_methods_cannot_read_or_bypass_admission(monkeypatch, method, path):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app):
            await first.receiving.wait()
            rejected = Exchange(path=path, method=method, body=b"not json")
            await rejected.run(app)
            assert rejected.status == 405
            assert rejected.payload["code"] == "METHOD_NOT_ALLOWED"
            assert rejected.reads == 0
            assert not decodes and downstream.calls == downstream.db_calls == 0
            await assert_busy(app, downstream, decodes)
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("path", [ROOT, ROOT + "/item/raw/ingress"])
@pytest.mark.parametrize(
    "headers",
    [[(b"content-length", b"1")], [(b"transfer-encoding", b"chunked")]],
)
def test_read_methods_reject_body_framing_without_receive(monkeypatch, method, path, headers):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        rejected = Exchange(method=method, path=path, headers=headers)
        await rejected.run(app)
        assert rejected.status == 400
        assert rejected.payload["code"] == "INVALID_FRAMING"
        assert rejected.reads == 0
        assert not decodes and downstream.calls == downstream.db_calls == 0
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["POST", "GET", "HEAD"])
@pytest.mark.parametrize("path", [ROOT, ROOT + "/nested"])
def test_evidence_operation_deadline_starts_after_body_admission(monkeypatch, method, path):
    async def exercise():
        clock = [100.0]
        monkeypatch.setattr(boundary, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange(path=path, method=method)
        if method == "POST":
            first.body_gate = asyncio.Event()
            async with asyncio.timeout(2), running(first, app) as task:
                await first.receiving.wait()
                assert "s02_deadline" not in first.scope
                clock[0] = 101.0
                first.body_gate.set()
                await task
        else:
            await first.run(app)
        assert first.scope["s02_deadline"] == clock[0] + 5.0
        assert first.status == 200
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "owner_path,contender_path",
    [(ROOT, ROOT + "/unknown"), (ROOT + "/", ROOT), (ROOT + "/a/b", ROOT + "/c")],
)
def test_process_wide_admission_is_shared_between_app_instances(
    monkeypatch, owner_path, contender_path
):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        other = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        other_app = boundary.DevelopmentBoundary(other)
        first = Exchange(path=owner_path)
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app) as task:
            await first.receiving.wait()
            await assert_busy(other_app, other, decodes, path=contender_path)
            first.body_gate.set()
            await task
        await assert_admitted(other_app, other)
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "fault,code,status",
    [
        ("host", "HOST_NOT_ALLOWED", 403),
        ("origin", "ORIGIN_NOT_ALLOWED", 403),
        ("duplicate", "INVALID_FRAMING", 400),
        ("content-type", "JSON_REQUIRED", 415),
        ("encoding", "UNSUPPORTED_ENCODING", 415),
        ("transfer", "INVALID_FRAMING", 400),
        ("length", "BODY_TOO_LARGE", 413),
    ],
)
def test_headers_are_checked_before_acquisition_and_cannot_release_owner(
    monkeypatch, fault, code, status
):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app):
            await first.receiving.wait()
            invalid = Exchange()
            headers = invalid.scope["headers"]
            if fault == "host":
                headers[0] = (b"host", b"evil.example")
            elif fault == "origin":
                headers.append((b"origin", b"https://evil.example"))
            elif fault == "duplicate":
                headers.append((b"content-type", b"application/json"))
            elif fault == "content-type":
                headers[1] = (b"content-type", b"text/plain")
            elif fault == "encoding":
                headers.append((b"content-encoding", b"gzip"))
            elif fault == "transfer":
                headers.extend([(b"transfer-encoding", b"chunked"), (b"content-length", b"2")])
            else:
                headers.append((b"content-length", b"262145"))
            await invalid.run(app)
            assert invalid.status == status
            assert invalid.payload["code"] == code
            assert invalid.reads == 0
            assert not decodes and downstream.calls == downstream.db_calls == 0
            await assert_busy(app, downstream, decodes)
            await assert_busy(app, downstream, decodes)
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_header_only_methods_do_not_consume_or_release_upload_permit(monkeypatch, method):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        calls = []

        async def header_handler(scope, receive, send):
            calls.append(scope["method"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        app = boundary.DevelopmentBoundary(downstream)
        other = boundary.DevelopmentBoundary(header_handler)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app):
            await first.receiving.wait()
            read = Exchange(method=method, headers=[
                (b"content-length", b"0"),
                (b"origin", b"http://localhost:5173"),
                (b"access-control-request-method", b"POST"),
                (b"access-control-request-headers", b"content-type"),
            ])
            await read.run(other)
            assert read.status == (204 if method == "OPTIONS" else 200)
            assert calls == ([] if method == "OPTIONS" else [method])
            assert read.reads == 0 and not decodes
            assert (b"access-control-allow-origin", b"http://localhost:5173") in (
                read.messages[0]["headers"]
            )
            await assert_busy(app, downstream, decodes)
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "fault,code,reads,decode_count",
    [
        ("disconnect", None, 1, 0),
        ("timeout", "REQUEST_TIMEOUT", 1, 0),
        ("length-mismatch", "INVALID_FRAMING", 1, 0),
        ("json", "VALIDATION_ERROR", 1, 1),
        ("duplicate-json", "VALIDATION_ERROR", 1, 1),
        ("bytes", "BODY_TOO_LARGE", 2, 0),
        ("frames", "BODY_TOO_LARGE", 4096, 0),
    ],
)
def test_body_failure_releases_for_a_later_positive_request(
    monkeypatch, fault, code, reads, decode_count
):
    assert boundary.BODY_TIMEOUT_SECONDS == 5.0
    assert boundary.MAX_BODY_FRAMES == 4096
    assert boundary.MAX_BODY_BYTES == 262144

    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        if fault == "disconnect":
            first.frames = [{"type": "http.disconnect"}]
        elif fault == "timeout":
            monkeypatch.setattr(boundary, "BODY_TIMEOUT_SECONDS", 0.01)
            first.body_gate = asyncio.Event()
        elif fault == "length-mismatch":
            first.scope["headers"].append((b"content-length", b"3"))
        elif fault == "json":
            first.body = b"{"
        elif fault == "duplicate-json":
            first.body = b'{"x":1,"x":2}'
        elif fault == "bytes":
            first.frames = [
                {"type": "http.request", "body": b" " * 262144, "more_body": True},
                {"type": "http.request", "body": b"x", "more_body": True},
                {"type": "http.request", "body": b"must not drain"},
            ]
        else:
            first.frames = [{"type": "http.request", "body": b"", "more_body": True}] * 4097
        async with asyncio.timeout(2):
            await first.run(app)
        assert first.receiving.is_set()
        assert first.reads == reads
        assert len(decodes) == decode_count
        assert downstream.calls == downstream.db_calls == 0
        if code is None:
            assert not first.messages
        else:
            assert first.payload["code"] == code
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_permit_covers_handler_wait_and_completion(monkeypatch, outcome):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        downstream.gate = asyncio.Event()
        failure = RuntimeError("injected handler failure")
        if outcome == "failure":
            downstream.failure = failure
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        async with asyncio.timeout(2), running(first, app) as task:
            await downstream.entered.wait()
            assert downstream.calls == downstream.db_calls == 1
            assert decodes == [b"{}"] and first.reads == 1
            await assert_busy(app, downstream, decodes)
            if outcome == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                downstream.gate.set()
                if outcome == "failure":
                    with pytest.raises(RuntimeError) as caught:
                        await task
                    assert caught.value is failure
                else:
                    await task
                    assert first.status == 200
        downstream.gate = None
        downstream.failure = None
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "send_type,outcome,body",
    [
        ("http.response.start", "success", b"{}"),
        ("http.response.body", "success", b"{}"),
        ("http.response.body", "failure", b"{}"),
        ("http.response.body", "cancel", b"{}"),
        ("http.response.body", "failure", b"{"),
    ],
)
def test_permit_covers_actual_send_including_validation_response(
    monkeypatch, send_type, outcome, body
):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange(body=body)
        first.send_gate = asyncio.Event()
        first.send_type = send_type
        failure = RuntimeError("injected send failure")
        if outcome == "failure":
            first.send_failure = failure
        async with asyncio.timeout(2), running(first, app) as task:
            await first.sending.wait()
            assert first.status == (200 if body == b"{}" else 422)
            assert not task.done()
            await assert_busy(app, downstream, decodes)
            if outcome == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                first.send_gate.set()
                if outcome == "failure":
                    with pytest.raises(RuntimeError) as caught:
                        await task
                    assert caught.value is failure
                else:
                    await task
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


def test_cancellation_does_not_release_until_handler_cleanup_finishes(monkeypatch):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        entered = asyncio.Event()
        cleanup = asyncio.Event()
        cleanup_gate = asyncio.Event()
        never = asyncio.Event()

        async def handler(scope, receive, send):
            entered.set()
            try:
                await never.wait()
            finally:
                cleanup.set()
                await cleanup_gate.wait()

        owner = boundary.DevelopmentBoundary(handler)
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        async with asyncio.timeout(2), running(first, owner) as task:
            try:
                await entered.wait()
                task.cancel()
                await cleanup.wait()
                assert not task.done()
                await assert_busy(app, downstream, decodes)
                cleanup_gate.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                cleanup_gate.set()
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("path,limit,code", [
    (ROOT, 262144, "BODY_TOO_LARGE"),
    (ROOT + "/nested", 262144, "BODY_TOO_LARGE"),
    ("/api/v1/targets", 262144, "BODY_TOO_LARGE"),
    ("/api/v1/offline-runs", 1024, "RUN_BODY_TOO_LARGE"),
    ("/api/v1/offline-runs/id/cancel", 1024, "RUN_BODY_TOO_LARGE"),
])
@pytest.mark.parametrize("declared", [False, True])
def test_existing_exact_and_plus_one_route_budgets_are_unchanged(path, limit, code, declared):
    async def exercise():
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        for size in (limit, limit + 1):
            raw = b"{}" + b" " * (size - 2)
            headers = [(b"content-length", str(size).encode())] if declared else []
            exchange = Exchange(path=path, body=raw, headers=headers)
            await exchange.run(app)
            if size == limit:
                assert exchange.status == 200
                assert exchange.reads == 1
                assert downstream.bodies == [raw]
            else:
                assert exchange.status == 413
                assert exchange.payload["code"] == code
                assert exchange.reads == (0 if declared else 1)
            assert downstream.calls == downstream.db_calls == 1
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("path", [
    "/api/v1/evidences", "/api/v1/evidence-other", "/api/v1/evidenceish/nested",
    "/api/v1/offline-runs-other",
])
def test_lookalike_namespaces_remain_generic_while_evidence_busy(monkeypatch, path):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app):
            await first.receiving.wait()
            for method in ("POST", "PUT"):
                generic = Exchange(path=path, method=method, body=b"{}" + b" " * 262142)
                await generic.run(app)
                assert generic.status == 200
                assert generic.reads == 1
                assert "s02_deadline" not in generic.scope
            await assert_busy(app, downstream, decodes)
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


def test_body_cancellation_is_propagated_and_releases_permit(monkeypatch):
    async def exercise():
        decodes = observe_decode(monkeypatch)
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange()
        first.body_gate = asyncio.Event()
        async with asyncio.timeout(2), running(first, app) as task:
            await first.receiving.wait()
            assert first.reads == 1
            await assert_busy(app, downstream, decodes)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
        assert not decodes and downstream.calls == downstream.db_calls == 0
        await assert_admitted(app, downstream)

    asyncio.run(exercise())


@pytest.mark.parametrize("path", [ROOT, "/api/v1/targets", "/api/v1/offline-runs"])
def test_exact_frame_budget_still_accepts_complete_body(path):
    async def exercise():
        downstream = Downstream()
        app = boundary.DevelopmentBoundary(downstream)
        first = Exchange(path=path)
        first.frames = [
            {"type": "http.request", "body": b"", "more_body": True}
        ] * 4095 + [{"type": "http.request", "body": b"{}", "more_body": False}]
        await first.run(app)
        assert first.status == 200
        assert first.reads == 4096
        assert downstream.bodies == [b"{}"]
        await assert_admitted(app, downstream)

    asyncio.run(exercise())
