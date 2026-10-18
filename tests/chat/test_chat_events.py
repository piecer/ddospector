import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from test_chat_runtime import configure
from test_chat_sessions import start
from test_chat_transport import settled, submit

from aiddos.api.app import create_app


def test_atomic_subscription_has_one_event_per_revision_and_durable_deltas(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    entered, release = asyncio.Event(), asyncio.Event()

    async def transport(*args):
        entered.set()
        await release.wait()
        yield "😀" * 2500

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        turn = submit(client, session)[0].json()
        client.portal.call(entered.wait)

        async def observe():
            runtime = app.state.chat
            subscriber = await runtime.subscribe(turn["id"], 0)
            first_raw, _ = subscriber.queue[0]
            first = json.loads(first_raw)
            assert first["type"] == "snapshot"
            release.set()
            await asyncio.wait_for(asyncio.shield(runtime.task), 5)
            records = [json.loads(raw) for raw, _ in subscriber.queue]
            runtime.subscribers.discard(subscriber)
            return records

        records = client.portal.call(observe)
        final = client.get(f"/api/v1/chat/turns/{turn['id']}").json()
        revisions = [e["revision"] for e in records]
        assert revisions == list(range(revisions[0], revisions[-1] + 1))
        reconstructed = records[0]["turn"]["assistant_text"]
        for record in records[1:]:
            if record["type"] == "delta":
                assert record["turn"] is None and 0 < len(record["text"].encode()) <= 4096
                reconstructed += record["text"]
            else:
                assert record["revision"] == record["turn"]["revision"]
                assert record["turn"]["assistant_text"] == reconstructed
        assert reconstructed == final["assistant_text"] == "😀" * 2500
        assert records[-1]["turn"] == final
        future = client.get(f"/api/v1/chat/turns/{turn['id']}/events?after={final['revision'] + 1}")
        assert future.status_code == 409 and future.json()["code"] == "CHAT_CURSOR_INVALID"


def test_sse_disconnect_only_detaches_observer(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def transport(*args):
        calls.append(1)
        entered.set()
        await release.wait()
        yield "continues after navigation"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        turn = submit(client, start(client)[0].json())[0].json()
        client.portal.call(entered.wait)

        async def disconnect():
            disconnected = asyncio.Event()
            bodies = []

            async def send(message):
                if message["type"] == "http.response.body" and message.get("body"):
                    bodies.append(message["body"])
                    disconnected.set()

            async def receive():
                await disconnected.wait()
                return {"type": "http.disconnect"}

            scope = {
                "type": "http",
                "asgi": {"spec_version": "2.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": f"/api/v1/chat/turns/{turn['id']}/events",
                "query_string": b"",
                "headers": [(b"host", b"localhost")],
                "server": ("localhost", 80),
                "client": ("127.0.0.1", 1234),
                "root_path": "",
            }
            await asyncio.wait_for(app(scope, receive, send), 2)
            assert len(bodies) == 1
            assert json.loads(bodies[0].removeprefix(b"event: chat\ndata: "))["type"] == "snapshot"
            assert not app.state.chat.subscribers
            assert app.state.chat.active == turn["id"]
            release.set()

        client.portal.call(disconnect)
        final = settled(client, app, turn)
        assert final["status"] == "succeeded"
        assert final["assistant_text"] == "continues after navigation" and calls == [1]
        assert client.get(f"/api/v1/chat/turns/{turn['id']}/events").status_code == 200


def test_subscriber_overflow_closes_observation_not_generation(tmp_path):
    app = create_app(state_path=tmp_path / "draft.json")
    entered, release = asyncio.Event(), asyncio.Event()

    async def transport(*args):
        entered.set()
        await release.wait()
        for _ in range(25):
            yield "a" * 256

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client)
        session = start(client)[0].json()
        turn = submit(client, session)[0].json()
        client.portal.call(entered.wait)

        async def observe():
            runtime = app.state.chat
            one = await runtime.subscribe(turn["id"], 0)
            two = await runtime.subscribe(turn["id"], 0)
            from aiddos.api.errors import DraftError

            with pytest.raises(DraftError, match="CHAT_BUSY"):
                await runtime.subscribe(turn["id"], 0)
            release.set()
            await asyncio.wait_for(asyncio.shield(runtime.task), 5)
            assert one.closed and two.closed
            assert len(one.queue) <= 16 and one.bytes <= 1024 * 1024
            runtime.subscribers.clear()

        client.portal.call(observe)
        final = client.get(f"/api/v1/chat/turns/{turn['id']}").json()
        assert final["status"] == "succeeded" and final["assistant_text"] == "a" * 6400


@pytest.mark.parametrize("text", ["\x01" * 65536, "😀" * 16384])
def test_maximum_escaped_output_two_turn_readback_and_paging(tmp_path, text):
    app = create_app(state_path=tmp_path / "draft.json")

    async def transport(*args):
        # Failed exchanges remain visible but are excluded from future context.
        yield text + "x"

    app.state.chat.transport = transport
    with TestClient(app, base_url="http://localhost") as client:
        configure(client, streaming=False)
        session = start(client)[0].json()
        for sequence in range(3):
            turn = settled(
                client, app, submit(client, session, expected_sequence=sequence)[0].json()
            )
            assert turn["status"] == "failed" and turn["error_code"] == "CHAT_OUTPUT_LIMIT"
            assert turn["assistant_text"] == text
        response = client.get(f"/api/v1/chat/sessions/{session['id']}")
        assert response.status_code == 200 and len(response.content) <= 1024 * 1024
        page = response.json()
        assert [t["sequence"] for t in page["turns"]] == [2, 3]
        assert [t["assistant_text"] for t in page["turns"]] == [text, text]
        assert page["next_before_sequence"] == 2
        older = client.get(f"/api/v1/chat/sessions/{session['id']}?before_sequence=2").json()
        assert [t["sequence"] for t in older["turns"]] == [1]
        assert older["next_before_sequence"] is None
        event = client.get(f"/api/v1/chat/turns/{turn['id']}/events")
        assert event.status_code == 200
        assert len(event.content) <= 1024 * 1024 + 128
        record = json.loads(event.text.removeprefix("event: chat\ndata: ").strip())
        assert record["turn"]["assistant_text"] == text
