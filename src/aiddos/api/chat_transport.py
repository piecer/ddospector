"""One owned, no-retry, no-proxy request to a pinned local literal."""

import re
from urllib.parse import urlsplit, urlunsplit

import httpx2

from .chat_models import encoded, valid_text
from .encoding import strict_json
from .errors import DraftError

UPSTREAM_BYTES = 2 * 1024 * 1024


def completion(raw):
    try:
        data = strict_json(raw)
        choices = data["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        if type(choice.get("index")) is not int or choice["index"] != 0:
            raise ValueError
        message = choice["message"]
        if (
            message.get("role") != "assistant"
            or "tool_calls" in message
            or "function_call" in message
        ):
            raise ValueError
        text = valid_text(message["content"])
        return text, choice["finish_reason"]
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        raise DraftError("CHAT_PROVIDER_PROTOCOL") from None


class SSEParser:
    """Byte framing before strict UTF-8/JSON decoding; no unbounded line buffer."""

    def __init__(self):
        self.buffer = bytearray()
        self.finished = False
        self.done = False

    def feed(self, chunk):
        self.buffer.extend(chunk)
        while match := re.search(rb"\r?\n\r?\n", self.buffer):
            raw = bytes(self.buffer[: match.start()])
            del self.buffer[: match.end()]
            if len(raw) > 65536:
                raise DraftError("CHAT_OUTPUT_LIMIT")
            try:
                lines = raw.decode("utf-8", errors="strict").split("\n")
                data = []
                for line in lines:
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
                    if not self.finished:
                        raise ValueError
                    self.done = True
                    continue
                if self.finished:
                    raise ValueError
                obj = strict_json(value.encode())
                choices = obj["choices"]
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError
                choice = choices[0]
                if type(choice.get("index")) is not int or choice["index"] != 0:
                    raise ValueError
                delta = choice["delta"]
                if (
                    not isinstance(delta, dict)
                    or "tool_calls" in delta
                    or "function_call" in delta
                    or delta.get("role", "assistant") != "assistant"
                ):
                    raise ValueError
                content = delta.get("content")
                text = valid_text("" if content is None else content)
                if text:
                    yield text
                finish = choice.get("finish_reason")
                if finish is not None:
                    if finish != "stop":
                        raise ValueError
                    self.finished = True
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
                raise DraftError("CHAT_PROVIDER_PROTOCOL") from None
        # A split separator is not payload. Reserve only the longest suffix
        # that can still complete the same LF/CRLF delimiter accepted above.
        pending = next(
            (
                len(prefix)
                for prefix in (b"\r\n\r", b"\r\n", b"\n\r", b"\r", b"\n")
                if self.buffer.endswith(prefix)
            ),
            0,
        )
        if len(self.buffer) - pending > 65536:
            raise DraftError("CHAT_OUTPUT_LIMIT")

    def end(self):
        # At EOF a pending prefix can no longer become a delimiter.
        if len(self.buffer) > 65536:
            raise DraftError("CHAT_OUTPUT_LIMIT")
        if self.buffer or not self.done or not self.finished:
            raise DraftError("CHAT_PROVIDER_PROTOCOL")


async def receive_text(profile, endpoint, payload):
    url = urlsplit(endpoint)
    host = url.netloc
    netloc = host.replace("localhost", "127.0.0.1", 1)
    target = urlunsplit((url.scheme, netloc, url.path, "", ""))
    limits = httpx2.Limits(max_connections=1, max_keepalive_connections=0)
    transport = httpx2.AsyncHTTPTransport(trust_env=False, retries=0, limits=limits)
    timeout = httpx2.Timeout(connect=3, write=5, read=30, pool=3)
    try:
        async with (
            httpx2.AsyncClient(
                transport=transport, trust_env=False, timeout=timeout, follow_redirects=False
            ) as client,
            client.stream(
                "POST",
                target,
                content=encoded(payload),
                headers={
                    "Host": host,
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    "Accept": "application/json",
                },
            ) as response,
        ):
            if not 200 <= response.status_code < 300:
                raise DraftError("CHAT_PROVIDER_ERROR")
            if (
                response.headers.get("content-encoding", "identity").lower() != "identity"
                or sum(len(k) + len(v) for k, v in response.headers.raw) > 32768
            ):
                raise DraftError("CHAT_PROVIDER_PROTOCOL")
            expected_type = "text/event-stream" if profile["streaming"] else "application/json"
            if response.headers.get("content-type", "").split(";")[0] != expected_type:
                raise DraftError("CHAT_PROVIDER_PROTOCOL")
            raw, count, parser = bytearray(), 0, SSEParser()
            async for chunk in response.aiter_raw():
                count += len(chunk)
                if count > UPSTREAM_BYTES:
                    raise DraftError("CHAT_OUTPUT_LIMIT")
                # Parse bounded pieces without waiting to fill an artificial read chunk.
                for offset in range(0, len(chunk), 4096):
                    part = chunk[offset : offset + 4096]
                    if profile["streaming"]:
                        for text in parser.feed(part):
                            yield text
                    else:
                        raw.extend(part)
            if profile["streaming"]:
                parser.end()
            else:
                text, finish = completion(bytes(raw))
                yield text
                if finish != "stop":
                    raise DraftError("CHAT_PROVIDER_PROTOCOL")
    except httpx2.TimeoutException:
        raise DraftError("CHAT_TIMEOUT") from None
    except httpx2.HTTPError:
        raise DraftError("CHAT_PROVIDER_ERROR") from None
