"""Native tools over one owned local HTTP client; no domain execution here."""

import re
from urllib.parse import urlsplit, urlunsplit

import httpx2

from .chat_models import encoded, valid_text
from .chat_transport import UPSTREAM_BYTES
from .encoding import strict_json
from .errors import DraftError

FRAME_BYTES = 65536
ARGUMENT_BYTES = 16384
SEPARATOR = re.compile(rb"\r?\n\r?\n")
TOOL_NAMES = ("configuration_read", "agent_profile_update", "target_create")


class NativeParser:
    """Accumulate a single native call; terminal events are withheld until EOF."""

    def __init__(self, *, allow_tools=True):
        self.allow_tools = allow_tools
        self.buffer = bytearray()
        self._scan = 0
        self.identifier = ""
        self.name = ""
        self.arguments = ""
        self.argument_bytes = 0
        self.call_type = None
        self.has_call = False
        self.finish = None
        self.done = False

    def delta(self, choice):
        if type(choice["index"]) is not int or choice["index"] != 0:
            raise ValueError
        delta = choice["delta"]
        if not isinstance(delta, dict) or "function_call" in delta:
            raise ValueError
        if delta.get("role", "assistant") != "assistant":
            raise ValueError
        content = delta.get("content")
        text = valid_text("" if content is None else content)
        if "tool_calls" in delta:
            if not self.allow_tools:
                raise ValueError
            calls = delta["tool_calls"]
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError
            call = calls[0]
            if not isinstance(call, dict) or call.keys() - {"index", "id", "type", "function"}:
                raise ValueError
            if type(call["index"]) is not int or call["index"] != 0:
                raise ValueError
            self.has_call = True
            self.identifier += call.get("id", "")
            valid_text(self.identifier, 128)
            if not self.identifier.isascii():
                raise ValueError
            if "type" in call:
                if self.call_type is not None or call["type"] != "function":
                    raise ValueError
                self.call_type = call["type"]
            function = call.get("function", {})
            if not isinstance(function, dict) or function.keys() - {"name", "arguments"}:
                raise ValueError
            self.name += function.get("name", "")
            if not any(name.startswith(self.name) for name in TOOL_NAMES):
                raise ValueError
            fragment = valid_text(function.get("arguments", ""))
            self.argument_bytes += len(fragment.encode())
            if self.argument_bytes > ARGUMENT_BYTES:
                raise ValueError
            self.arguments += fragment
        finish = choice.get("finish_reason")
        if finish is not None:
            if finish not in ("stop", "tool_calls") or (finish == "tool_calls") != self.has_call:
                raise ValueError
            self.finish = finish
        return [{"type": "text", "text": text}] if text else []

    def feed(self, chunk):
        self.buffer.extend(chunk)
        try:
            while match := SEPARATOR.search(self.buffer, self._scan):
                if match.start() > FRAME_BYTES:
                    raise DraftError("CHAT_OUTPUT_LIMIT")
                raw = bytes(self.buffer[: match.start()])
                del self.buffer[: match.end()]
                self._scan = 0
                data = []
                for line in raw.decode("utf-8", errors="strict").split("\n"):
                    line = line.removesuffix("\r")
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        raise ValueError
                    data.append(line[5:].removeprefix(" "))
                if not data:
                    continue
                value = "\n".join(data)
                if self.done:
                    raise ValueError
                if value == "[DONE]":
                    if self.finish is None:
                        raise ValueError
                    self.done = True
                    continue
                if self.finish is not None:
                    raise ValueError
                choices = strict_json(value.encode())["choices"]
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError
                yield from self.delta(choices[0])
            # Only a delimiter's final three bytes can cross a feed boundary.
            self._scan = max(0, len(self.buffer) - 3)
            pending = next(
                (
                    len(prefix)
                    for prefix in (b"\r\n\r", b"\r\n", b"\n\r", b"\r", b"\n")
                    if self.buffer.endswith(prefix)
                ),
                0,
            )
            if len(self.buffer) - pending > FRAME_BYTES:
                raise DraftError("CHAT_OUTPUT_LIMIT")
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise DraftError("CHAT_TOOL_PROTOCOL") from None

    def completion(self, raw):
        try:
            choices = strict_json(raw)["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if message["role"] != "assistant":
                raise ValueError
            delta = dict(message)
            if "tool_calls" in delta:
                calls = delta["tool_calls"]
                if not isinstance(calls, list) or len(calls) != 1:
                    raise ValueError
                if not isinstance(calls[0], dict) or calls[0].keys() != {"id", "type", "function"}:
                    raise ValueError
                delta["tool_calls"] = [{**calls[0], "index": 0}]
            events = self.delta(
                {"index": choice["index"], "delta": delta, "finish_reason": choice["finish_reason"]}
            )
            self.done = True
            return events + self.end()
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise DraftError("CHAT_TOOL_PROTOCOL") from None

    def end(self):
        if len(self.buffer) > FRAME_BYTES:
            raise DraftError("CHAT_OUTPUT_LIMIT")
        try:
            if self.buffer or not self.done or self.finish is None:
                raise ValueError
            events = []
            if self.has_call:
                if not self.identifier or self.call_type != "function":
                    raise ValueError
                if self.name not in TOOL_NAMES:
                    raise ValueError
                arguments = strict_json(self.arguments.encode())
                if not isinstance(arguments, dict):
                    raise ValueError
                # Reject escaped lone surrogates and numeric overflow as well.
                # Only validation uses this encoding; the native string is retained.
                encoded(arguments)
                events.append(
                    {
                        "type": "call",
                        "id": self.identifier,
                        "name": self.name,
                        "arguments": self.arguments,
                    }
                )
            return [*events, {"type": "finish", "reason": self.finish}]
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise DraftError("CHAT_TOOL_PROTOCOL") from None


class ToolTransport:
    """One context per turn; iterate each round completely (or explicitly close it)."""

    def __init__(self, profile, endpoint):
        match = re.fullmatch(
            r"http://(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?/v1/chat/completions",
            endpoint,
        )
        if match is None or (match[2] is not None and not 1 <= int(match[2]) <= 65535):
            raise DraftError("CHAT_UNSUPPORTED_PROFILE")
        self.streaming = profile["streaming"]
        url = urlsplit(endpoint)
        self.host = url.netloc
        self.target = urlunsplit(
            (url.scheme, self.host.replace("localhost", "127.0.0.1", 1), url.path, "", "")
        )
        self._client = None
        self._response = None
        self._active = False
        self.closed = False
        self.requests_started = 0
        self.upstream_bytes = 0

    @property
    def response_open(self):
        return self._response is not None and not self._response.is_closed

    async def __aenter__(self):
        if self._client is not None or self.closed:
            raise RuntimeError("ToolTransport contexts cannot be reused")
        limits = httpx2.Limits(max_connections=1, max_keepalive_connections=0)
        transport = httpx2.AsyncHTTPTransport(trust_env=False, retries=0, limits=limits)
        self._client = httpx2.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx2.Timeout(connect=3, write=5, read=30, pool=3),
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args):
        self.closed = True
        try:
            if self._response is not None:
                await self._response.aclose()
        finally:
            if self._client is not None:
                await self._client.__aexit__(*args)

    async def round(self, payload):
        if self._client is None or self.closed:
            raise RuntimeError("ToolTransport requires an open context")
        if self._active:
            raise DraftError("CHAT_BUSY")
        self._active = True
        try:
            body = encoded(payload)
            self.requests_started += 1
            async with self._client.stream(
                "POST",
                self.target,
                content=body,
                headers={
                    "Host": self.host,
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    "Accept": "application/json",
                },
            ) as response:
                self._response = response
                if not 200 <= response.status_code < 300:
                    raise DraftError("CHAT_PROVIDER_ERROR")
                expected = "text/event-stream" if self.streaming else "application/json"
                if (
                    response.headers.get("content-encoding", "identity").lower() != "identity"
                    or sum(len(k) + len(v) for k, v in response.headers.raw) > 32768
                    or response.headers.get("content-type", "").split(";")[0] != expected
                ):
                    raise DraftError("CHAT_TOOL_PROTOCOL")
                parser, raw = NativeParser(allow_tools=bool(payload.get("tools"))), bytearray()
                async for chunk in response.aiter_raw():
                    self.upstream_bytes += len(chunk)
                    if self.upstream_bytes > UPSTREAM_BYTES:
                        raise DraftError("CHAT_OUTPUT_LIMIT")
                    if self.streaming:
                        for offset in range(0, len(chunk), 4096):
                            for event in parser.feed(chunk[offset : offset + 4096]):
                                if self.closed:
                                    raise RuntimeError("ToolTransport context has closed")
                                yield event
                    else:
                        raw.extend(chunk)
                terminal = parser.end() if self.streaming else parser.completion(bytes(raw))
            for event in terminal:
                if self.closed:
                    raise RuntimeError("ToolTransport context has closed")
                yield event
        except httpx2.TimeoutException:
            raise DraftError("CHAT_TIMEOUT") from None
        except httpx2.HTTPError:
            raise DraftError("CHAT_PROVIDER_ERROR") from None
        finally:
            self._client.cookies.clear()
            self._response = None
            self._active = False
