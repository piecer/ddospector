"""Pre-framework, bounded admission for a loopback-only development service.

Origin/Host checks are browser request hardening, NOT production authentication.
Non-browser requests without Origin are allowed when Host is loopback.
"""

import asyncio
import re

from starlette.responses import Response

from .encoding import strict_json
from .errors import DraftError, error_response

MAX_BODY_BYTES = 256 * 1024
MAX_BODY_FRAMES = 4096
BODY_TIMEOUT_SECONDS = 5.0
ALLOWED_ORIGINS = frozenset(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1", "[::1]")
    for port in (5173, 5175, 5180, 5182)
)
SECURITY_HEADERS = frozenset(
    {
        "host",
        "origin",
        "content-type",
        "content-length",
        "content-encoding",
        "transfer-encoding",
        "sec-fetch-site",
        "access-control-request-method",
        "access-control-request-headers",
    }
)
DENIAL_PATHS = frozenset({"/api/v1/runs", "/api/v1/agent/execute"})


def checked_headers(scope: dict) -> dict[str, str]:
    headers = {}
    for name, value in scope["headers"]:
        key = name.decode("latin-1").lower()
        if key in SECURITY_HEADERS and key in headers:
            raise DraftError("INVALID_FRAMING")
        headers[key] = value.decode("latin-1")
    host = headers.get("host", "")
    if not re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host):
        raise DraftError("HOST_NOT_ALLOWED")
    origin = headers.get("origin")
    if (origin is not None and origin not in ALLOWED_ORIGINS) or (
        origin is None and headers.get("sec-fetch-site") == "cross-site"
    ):
        raise DraftError("ORIGIN_NOT_ALLOWED")
    return headers


def body_headers(headers: dict[str, str]) -> int | None:
    if not re.fullmatch(
        r'application/json(?:\s*;\s*charset=(?:utf-8|"utf-8"))?',
        headers.get("content-type", ""),
        re.IGNORECASE,
    ):
        raise DraftError("JSON_REQUIRED")
    if "content-encoding" in headers:
        raise DraftError("UNSUPPORTED_ENCODING")
    length = headers.get("content-length")
    transfer = headers.get("transfer-encoding")
    if transfer is not None and (transfer != "chunked" or length is not None):
        raise DraftError("INVALID_FRAMING")
    if length is None:
        return None
    if not re.fullmatch(r"[0-9]{1,20}", length):
        raise DraftError("INVALID_FRAMING")
    size = int(length)
    if size > MAX_BODY_BYTES:
        raise DraftError("BODY_TOO_LARGE")
    return size


class DevelopmentBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        origin = None

        async def protected_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"cache-control", b"no-store")]
                if origin is not None:
                    message["headers"].extend(
                        [
                            (b"access-control-allow-origin", origin.encode("ascii")),
                            (b"vary", b"Origin"),
                        ]
                    )
            await send(message)

        try:
            headers = checked_headers(scope)
            origin = headers.get("origin")
            if scope["method"] == "OPTIONS":
                requested_headers = {
                    value.strip().lower()
                    for value in headers.get("access-control-request-headers", "").split(",")
                    if value.strip()
                }
                if (
                    origin is None
                    or headers.get("access-control-request-method") not in {"GET", "POST", "PUT"}
                    or not requested_headers <= {"content-type"}
                ):
                    raise DraftError("ORIGIN_NOT_ALLOWED")
                await Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Methods": "GET, POST, PUT",
                        "Access-Control-Allow-Headers": "Content-Type",
                    },
                )(scope, receive, protected_send)
                return
            downstream_receive = receive
            if scope["method"] not in {"GET", "HEAD"}:
                expected_length = body_headers(headers)
                body = bytearray()
                try:
                    async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                        for _ in range(MAX_BODY_FRAMES):
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            chunk = message.get("body", b"")
                            if len(body) + len(chunk) > MAX_BODY_BYTES:
                                raise DraftError("BODY_TOO_LARGE")
                            body.extend(chunk)
                            if not message.get("more_body", False):
                                break
                        else:
                            raise DraftError("BODY_TOO_LARGE")
                except TimeoutError:
                    raise DraftError("REQUEST_TIMEOUT") from None
                if expected_length is not None and len(body) != expected_length:
                    raise DraftError("INVALID_FRAMING")
                raw = bytes(body)
                if scope["path"] not in DENIAL_PATHS:
                    try:
                        strict_json(raw)
                    except (ValueError, RecursionError):
                        raise DraftError("VALIDATION_ERROR") from None
                sent = False

                async def replay():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": raw, "more_body": False}
                    return await receive()

                downstream_receive = replay
            await self.app(scope, downstream_receive, protected_send)
        except DraftError as exc:
            await error_response(exc.code)(scope, receive, protected_send)
