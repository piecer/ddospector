"""Bounded synthetic OpenAI HTTP fixture. Never a real-model fallback."""

import json
import select
import socket
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_REQUEST = 128 * 1024
MAX_WIRE = 3 * 1024 * 1024


def sse(content=None, *, finish=None):
    delta = {} if content is None else {"content": content}
    value = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return b"data: " + json.dumps(value, ensure_ascii=False).encode() + b"\n\n"


@dataclass(frozen=True)
class Scenario:
    chunks: tuple[bytes, ...]
    delays: tuple[float, ...] = ()
    status: int = 200
    content_type: str = "text/event-stream"

    def __post_init__(self):
        if not 1 <= len(self.chunks) <= 4096:
            raise ValueError("fixture chunk budget")
        if sum(map(len, self.chunks)) > MAX_WIRE:
            raise ValueError("fixture wire budget")
        if self.delays and len(self.delays) != len(self.chunks):
            raise ValueError("fixture delay shape")
        if any(not 0 <= delay <= 35 for delay in self.delays) or sum(self.delays) > 125:
            raise ValueError("fixture delay budget")

    @classmethod
    def text(cls, text="SYNTHETIC fixture: 안녕하세요 🌍", *, terminal=True, split=0):
        wire = sse(text) + (sse(finish="stop") + b"data: [DONE]\n\n" if terminal else b"")
        chunks = (
            tuple(wire[i : i + split] for i in range(0, len(wire), split)) if split else (wire,)
        )
        return cls(chunks)

    @classmethod
    def slow(cls):
        return cls((sse("SYNTHETIC partial " * 32), sse("later"), sse(finish="stop")), (0, 10, 0))


class ProviderFixture:
    """At most eight requests, finite wire/time, explicit socket-closure census."""

    def __init__(self, scenarios, *, max_requests=8):
        if not 1 <= max_requests <= 8 or not 1 <= len(scenarios) <= max_requests:
            raise ValueError("fixture request budget")
        self.scenarios = tuple(scenarios)
        self.max_requests = max_requests
        self.requests = []
        self.opened = 0
        self.closed = 0
        self.peer_closed = 0
        self.stop = threading.Event()
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def log_message(self, format, *args):
                pass

            def do_POST(self):
                self.close_connection = True
                self.connection.settimeout(3)
                with owner.lock:
                    owner.opened += 1
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/v1/chat/completions" or not 0 < length <= MAX_REQUEST:
                        self.send_error(400)
                        return
                    body = json.loads(self.rfile.read(length))
                    with owner.lock:
                        index = len(owner.requests)
                        if index >= min(owner.max_requests, len(owner.scenarios)):
                            self.send_error(429)
                            return
                        owner.requests.append({"path": self.path, "body": body})
                    scenario = owner.scenarios[index]
                    self.send_response(scenario.status)
                    self.send_header("Content-Type", scenario.content_type)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    for index, chunk in enumerate(scenario.chunks):
                        delay = scenario.delays[index] if scenario.delays else 0
                        until = time.monotonic() + delay
                        while time.monotonic() < until:
                            if owner.stop.wait(min(0.02, max(0, until - time.monotonic()))):
                                return
                            if select.select([self.connection], [], [], 0)[
                                0
                            ] and not self.connection.recv(1, socket.MSG_PEEK):
                                with owner.lock:
                                    owner.peer_closed += 1
                                return
                        if owner.stop.is_set():
                            return
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                except (OSError, ValueError):
                    with owner.lock:
                        owner.peer_closed += 1
                finally:
                    with owner.lock:
                        owner.closed += 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}
        )
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.server.shutdown()
        # Flush pending accepts as well as closing the FD (not just a thread exit).
        self.server.socket.shutdown(socket.SHUT_RDWR)
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "fixture listener leaked"
        assert self.opened == self.closed, "fixture request handler leaked"

    def wait_closed(self, count=1, timeout=5):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            with self.lock:
                if self.closed >= count:
                    return
            time.sleep(0.01)
        raise AssertionError("fixture socket did not close within deadline")
