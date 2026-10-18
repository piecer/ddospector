"""SQLite publication faults/restart and real lost-ACK approval recovery."""

import json
import socket
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from test_chat_integration import wait_turn
from test_chat_tool_routes_controls import waiting
from test_chat_tool_routes_runtime import companion, grant_turn
from test_chat_tool_runtime_lifecycle import LiveProduct, world


def test_lost_decision_ack_get_only_recovery_one_write(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        body = {
            "request_id": str(uuid4()),
            "proposal_digest": call["proposal"]["digest"],
            "decision": "approve",
        }
        raw = json.dumps(body).encode()
        target = urlsplit(product.base)
        with socket.create_connection((target.hostname, target.port), timeout=2) as peer:
            peer.sendall(
                (
                    f"POST /api/v1/chat/tool-calls/{call['id']}/decision HTTP/1.1\r\n"
                    f"Host: {target.netloc}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + raw
            )
            peer.shutdown(socket.SHUT_WR)
            # Drop the ACK, never repeat the POST.
        assert wait_turn(product, turn)["status"] == "succeeded"
        result = companion(product, turn)["calls"][0]
        assert result["decision"]["request_id"] == body["request_id"]
        assert result["decision"]["proposal_digest"] == body["proposal_digest"]
        assert result["decision"]["call_id"] == call["id"]
        assert result["decision"]["decision"] == "approve"
        assert result["status"] == "succeeded"
        assert json.loads(product.state.read_text())["audit_total"] == before["audit_total"] + 1
        assert len(provider.requests) == 2


def test_simultaneous_decisions_commit_once(tmp_path):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        bodies = [
            {
                "request_id": str(uuid4()),
                "proposal_digest": call["proposal"]["digest"],
                "decision": "approve",
            }
            for _ in range(2)
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda b: product.request(
                        f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", b
                    ),
                    bodies,
                )
            )
        assert sorted(r[0] for r in results) == [201, 409]
        assert wait_turn(product, turn)["status"] == "succeeded"
        assert json.loads(product.state.read_text())["audit_total"] == before["audit_total"] + 1
        assert len(provider.requests) == 2


@pytest.mark.parametrize("phase", ["intent", "receipt", "receipt_committed"])
def test_sqlite_commit_fault_fences_then_restart_never_redispatches(tmp_path, monkeypatch, phase):
    with world(tmp_path) as (product, provider, saved, before):
        grant, turn, _ = grant_turn(product, saved)
        call = waiting(product, turn)
        runtime = product.runtime
        real = runtime.storage.db
        fired, armed = [], []

        class Fault:
            def __getattr__(self, name):
                return getattr(real, name)

            def execute(self, sql, *args):
                if sql.startswith("INSERT INTO tool_calls") and args:
                    record = json.loads(args[0][-1])["call"]
                    if record["status"] == ("executing" if phase == "intent" else "succeeded"):
                        armed.append(True)
                return real.execute(sql, *args)

            def commit(self):
                if armed and not fired:
                    fired.append(phase)
                    if phase == "receipt_committed":
                        real.commit()
                    raise sqlite3.OperationalError("injected commit failure")
                return real.commit()

        product.on_loop(lambda: setattr(runtime.storage, "db", Fault()))
        body = {
            "request_id": str(uuid4()),
            "proposal_digest": call["proposal"]["digest"],
            "decision": "approve",
        }
        status, response = product.request(
            f"/api/v1/chat/tool-calls/{call['id']}/decision", "POST", body
        )
        if phase == "intent":
            assert status == 503, (status, response)
        else:
            assert status == 201
        until = time.monotonic() + 3
        while not fired and time.monotonic() < until:
            time.sleep(0.01)
        assert fired == [phase], "fault did not fire"
        assert (
            product.request(f"/api/v1/chat/turns/{turn['id']}/tools")[1]["code"]
            == "CHAT_COMMIT_UNCERTAIN"
        )
        assert product.request("/api/v1/chat/tools/fence")[1]["code"] == "CHAT_COMMIT_UNCERTAIN"
        assert json.loads(product.state.read_text())["audit_total"] == before["audit_total"] + (
            phase != "intent"
        )
        product.close()
        reopened = LiveProduct(tmp_path)
        try:
            found = companion(reopened, turn)["calls"][0]
            assert (
                found["status"]
                == {
                    "intent": "cancelled",
                    "receipt": "uncertain",
                    "receipt_committed": "succeeded",
                }[phase]
            )
            assert reopened.request("/api/v1/chat/tools/fence")[1]["fenced"] == (phase == "receipt")
            assert (
                reopened.request(f"/api/v1/chat/turns/{turn['id']}")[1]["status"] == "interrupted"
            )
            assert len(provider.requests) == 1
        finally:
            reopened.close()
