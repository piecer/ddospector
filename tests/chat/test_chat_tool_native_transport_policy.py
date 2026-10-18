"""Pinned policy and response limits observed through real owned HTTP."""

import asyncio
import socket

import httpx2
import pytest
from provider_fixture import ProviderFixture, Scenario
from test_chat_tool_native_transport import PAYLOAD, native_wire, transport_class

from aiddos.api.errors import DraftError


@pytest.mark.parametrize("extra", [0, 1])
def test_response_header_exact_limit(extra):
    with ProviderFixture([Scenario((native_wire(),))]) as fixture:
        handler = fixture.server.RequestHandlerClass
        end_headers = handler.end_headers
        measured = []

        def padded_headers(self):
            pairs = [line.rstrip(b"\r\n").split(b": ", 1) for line in self._headers_buffer[1:]]
            current = sum(len(k) + len(v) for k, v in pairs)
            self.send_header("X-Pad", "p" * (32768 + extra - current - len("X-Pad")))
            measured.append(current + len("X-Pad") + (32768 + extra - current - len("X-Pad")))
            end_headers(self)

        handler.end_headers = padded_headers

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                return [event async for event in owner.round(PAYLOAD)]

        if extra:
            with pytest.raises(DraftError) as exc:
                asyncio.run(run())
            assert exc.value.code == "CHAT_TOOL_PROTOCOL"
        else:
            assert asyncio.run(run())[-1]["reason"] == "tool_calls"
        fixture.wait_closed()
        assert measured == [32768 + extra]


@pytest.mark.parametrize("kind", ["redirect", "status", "encoding", "content_type"])
def test_http_envelope_refuses_without_retry_or_redirect(kind):
    scenario = Scenario(
        (native_wire(),),
        status=307 if kind == "redirect" else 500 if kind == "status" else 200,
        content_type="text/html" if kind == "content_type" else "text/event-stream",
    )
    with ProviderFixture([Scenario.text()]) as sink, ProviderFixture([scenario]) as fixture:
        handler = fixture.server.RequestHandlerClass
        end_headers = handler.end_headers

        def modified_headers(self):
            if kind == "redirect":
                self.send_header("Location", sink.base_url + "/chat/completions")
            if kind == "encoding":
                self.send_header("Content-Encoding", "gzip")
            end_headers(self)

        handler.end_headers = modified_headers

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                return [event async for event in owner.round(PAYLOAD)]

        with pytest.raises(DraftError) as exc:
            asyncio.run(run())
        assert exc.value.code == (
            "CHAT_PROVIDER_ERROR" if kind in {"redirect", "status"} else "CHAT_TOOL_PROTOCOL"
        )
        fixture.wait_closed()
        assert len(fixture.requests) == 1 and not sink.requests and not sink.opened


def test_localhost_pinned_host_no_dns_auth_proxy_or_retries(monkeypatch):
    observed = []
    with (
        ProviderFixture([Scenario.text()]) as proxy,
        ProviderFixture([Scenario((native_wire(),))]) as fixture,
    ):
        handler = fixture.server.RequestHandlerClass
        post = handler.do_POST

        def observe_post(self):
            observed.append(dict(self.headers))
            post(self)

        handler.do_POST = observe_post

        def forbidden_dns(*args, **kwargs):
            raise AssertionError("DNS lookup forbidden")

        monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            monkeypatch.setenv(name, proxy.base_url)
        monkeypatch.setenv("NO_PROXY", "")

        async def run():
            endpoint = fixture.base_url.replace("127.0.0.1", "localhost") + "/chat/completions"
            async with transport_class()({"streaming": True}, endpoint) as owner:
                client = owner._client
                assert client.timeout == httpx2.Timeout(connect=3, write=5, read=30, pool=3)
                assert client.follow_redirects is False and client.trust_env is False
                pool = client._transport._pool
                assert pool._max_connections == 1 and pool._max_keepalive_connections == 0
                assert pool._retries == 0
                assert [e async for e in owner.round(PAYLOAD)][-1]["reason"] == "tool_calls"

        asyncio.run(run())
        fixture.wait_closed()
        assert len(observed) == 1 and proxy.opened == 0
        assert observed[0]["Host"] == f"localhost:{fixture.server.server_port}"
        assert observed[0]["Accept-Encoding"] == "identity"
        assert "Authorization" not in observed[0] and "Proxy-Authorization" not in observed[0]


def test_response_cookies_never_become_authentication_on_later_rounds():
    observed = []
    with ProviderFixture([Scenario((native_wire(),)), Scenario.text()]) as fixture:
        handler = fixture.server.RequestHandlerClass
        post, end_headers = handler.do_POST, handler.end_headers

        def observe_post(self):
            observed.append(self.headers.get("Cookie"))
            post(self)

        def cookie_headers(self):
            self.send_header("Set-Cookie", "auth=provider-value; Path=/")
            end_headers(self)

        handler.do_POST, handler.end_headers = observe_post, cookie_headers

        async def run():
            async with transport_class()(
                {"streaming": True}, fixture.base_url + "/chat/completions"
            ) as owner:
                for _ in range(2):
                    assert [e async for e in owner.round(PAYLOAD)][-1]["type"] == "finish"
                assert observed == [None, None]
                assert not list(owner._client.cookies)

        asyncio.run(run())
        fixture.wait_closed(2)
        assert observed == [None, None]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/v1/chat/completions",
        "http://127.0.0.2/v1/chat/completions",
        "https://localhost/v1/chat/completions",
        "http://u:p@localhost/v1/chat/completions",
        "http://localhost:0/v1/chat/completions",
        "http://localhost:65536/v1/chat/completions",
        "http://localhost/v1/chat/completions?x=1",
        "http://localhost/v1/chat/completions#fragment",
        "http://localhost/elsewhere",
    ],
)
def test_unsupported_endpoint_is_rejected_before_client_creation(endpoint):
    with pytest.raises(DraftError) as exc:
        transport_class()({"streaming": True}, endpoint)
    assert exc.value.code == "CHAT_UNSUPPORTED_PROFILE"
