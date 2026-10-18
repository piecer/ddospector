"""Bounded observers. Observation never owns or cancels generation."""

import asyncio
from collections import deque

from starlette.responses import StreamingResponse

from .chat_models import TERMINAL, encoded


def event(turn, text=None):
    data = {
        "schema_version": 1,
        "turn_id": turn["id"],
        "revision": turn["revision"],
        "type": "snapshot" if text is None else "delta",
        "turn": turn if text is None else None,
        "text": text,
    }
    raw = encoded(data)
    if len(raw) > 1024 * 1024:
        raise ValueError("Event budget exceeded")
    return raw, text is None and turn["status"] in TERMINAL


class Subscriber:
    def __init__(self, turn_id):
        self.turn_id = turn_id
        self.queue = deque()
        self.bytes = 0
        self.closed = False
        self.ready = asyncio.Event()

    def put(self, record):
        if self.closed:
            return
        raw, _ = record
        if len(self.queue) >= 16 or self.bytes + len(raw) > 1024 * 1024:
            self.close()
            return
        self.queue.append(record)
        self.bytes += len(raw)
        self.ready.set()

    def close(self):
        self.closed = True
        self.queue.clear()
        self.bytes = 0
        self.ready.set()

    async def records(self):
        wire_bytes = 0
        while not self.closed:
            await self.ready.wait()
            if self.closed:
                return
            raw, terminal = self.queue.popleft()
            self.bytes -= len(raw)
            if not self.queue:
                self.ready.clear()
            frame = b"event: chat\ndata: " + raw + b"\n\n"
            wire_bytes += len(frame)
            if wire_bytes > 2 * 1024 * 1024:
                return
            yield frame
            if terminal:
                return


class EventResponse(StreamingResponse):
    def __init__(self, runtime, subscriber):
        self.runtime = runtime
        self.subscriber = subscriber
        super().__init__(
            subscriber.records(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(125):
                await super().__call__(scope, receive, send)
        except TimeoutError:
            pass
        finally:
            self.subscriber.close()
            self.runtime.subscribers.discard(self.subscriber)
