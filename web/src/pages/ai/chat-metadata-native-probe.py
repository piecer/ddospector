"""Test-only cancelled native metadata lifetime; no HTTP/provider/model calls."""

import asyncio
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from aiddos.api.chat_models import runtime_view
from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.store import DraftStore


async def main():
    root = Path(__file__).resolve().parents[4]
    import aiddos.api.chat_tool_domain as module

    assert Path(module.__file__).resolve() == root / "src/aiddos/api/chat_tool_domain.py"
    with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as directory:
        draft = DraftStore(Path(directory) / "draft.json")
        worker = DomainWorker(draft)
        entered, release = threading.Event(), threading.Event()
        original = draft.ai_snapshot

        def held():
            entered.set()
            assert release.wait(10), "native test barrier expired"
            return original()

        draft.ai_snapshot = held
        task = asyncio.create_task(worker.ai_snapshot())
        try:
            async with asyncio.timeout(3):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert worker.busy
            print(json.dumps({"held_after_cancel": True, "origin": module.__file__}), flush=True)
            while line := await asyncio.to_thread(sys.stdin.readline):
                command = json.loads(line)
                if command == "release":
                    release.set()
                    async with asyncio.timeout(3):
                        while worker.busy:
                            await asyncio.sleep(0.001)
                    print(json.dumps({"retired": True}), flush=True)
                elif command == "runtime":
                    try:
                        value = runtime_view(await worker.ai_snapshot())
                        print(json.dumps({"status": 200, "body": value}), flush=True)
                    except DraftError as error:
                        assert error.code == "CHAT_BUSY"
                        print(
                            json.dumps(
                                {
                                    "status": 429,
                                    "body": {"code": error.code, "message": "Chat is busy."},
                                }
                            ),
                            flush=True,
                        )
                elif command == "close":
                    break
                else:
                    raise AssertionError(command)
        finally:
            release.set()
            await worker.shutdown()
            assert not worker.busy
            assert worker._executor is not None
            assert all(not t.is_alive() for t in worker._executor._threads)
            print(json.dumps({"closed": True}), flush=True)


asyncio.run(main())
