"""Original-authority regressions with real native bytes and frozen S1 records."""

import hashlib
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_scenario_grant_staging import bootstrap, issue
from test_chat_scenario_proposal_runtime import setup_path, waiting

from aiddos.api import chat_tool_runtime
from aiddos.api.app import create_app
from aiddos.api.chat_models import encoded
from aiddos.api.chat_tool_models import DecisionInput, digest
from aiddos.api.errors import DraftError


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(state_path=tmp_path / "draft.json"), base_url="http://localhost"
    ) as c:
        yield c


def record(name, data):
    if "REVIEW_OUTPUT" not in os.environ:
        return
    p = Path(os.environ["REVIEW_OUTPUT"])
    p.mkdir(parents=True, exist_ok=True)
    (p / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def final_frame():
    return (
        b"data: "
        + encoded(
            dict(choices=[dict(index=0, delta=dict(content="Not saved."), finish_reason="stop")])
        )
        + b"\n\ndata: [DONE]\n\n"
    )


def test_new_raw_hash_does_not_replay_different_unquoted_text(client, monkeypatch):
    runtime, body, _ = bootstrap(client)
    alternate = '한😀 "quoted" \\ path'
    body["text"] = encoded(alternate).decode()
    grant, status = issue(client, runtime, body)
    assert (
        status == 201 and grant["text_sha256"] == hashlib.sha256(body["text"].encode()).hexdigest()
    )
    assert issue(client, runtime, body) == (grant, 200)

    def forbidden(*a, **kw):
        raise AssertionError("replay acquired source")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    outcome = {}
    try:
        replay, code = issue(client, runtime, body | {"text": alternate})
        outcome = {"status": code, "same_grant": replay == grant, "error": None}
    except DraftError as exc:
        outcome = {"error": exc.code}
    record(
        "new-hash-ambiguity",
        dict(original=body["text"], changed=alternate, grant=grant, outcome=outcome),
    )
    assert outcome.get("error") == "CHAT_TOOL_GRANT_CONFLICT", (
        "different raw UTF-8 text replayed by legacy JSON-hash fallback"
    )


def test_old_json_hash_cannot_become_sendable_with_quoted_text(client, monkeypatch):
    runtime, grant, value, transport, _ = legacy_setup_path(client, monkeypatch)
    assert grant["text_sha256"] == digest(value.text)
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_INVALID"):
            await runtime._accept_scenario_tool(grant["session_id"], value)
        altered = value.model_copy(update={"text": encoded(value.text).decode()})
        outcome = {}
        try:
            turn, status = await runtime._accept_scenario_tool(grant["session_id"], altered)
            transcript = await waiting(runtime, turn["id"])
            outcome = {
                "status": status,
                "transcript": transcript,
                "requests": len(transport.requests),
            }
        except DraftError as exc:
            outcome = {"error": exc.code}
        finally:
            if runtime.active:
                await runtime.cancel(runtime.active)
                await runtime.task
        runtime.storage.validate()
        record(
            "historical-hash-send",
            dict(grant=grant, original=value.text, changed=altered.text, outcome=outcome),
        )
        assert runtime.scenarios.path.read_bytes() == before
        assert outcome.get("error") == "CHAT_TOOL_GRANT_INVALID", (
            "historical S1 grant admitted and proposed with JSON-spelled replacement text"
        )

    client.portal.call(exercise)


@pytest.mark.parametrize("loss", ["stop", "deadline"])
def test_read_exchange_overflow_cannot_bypass_final_publication_guard(client, monkeypatch, loss):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_append")
    # Each raw SSE frame remains below 64 KiB. Total text is 48 KiB;
    # JSON escaping makes the native exchange 96 KiB before the actual read result.
    chunks = [
        b"data: "
        + encoded(
            dict(choices=[dict(index=0, delta=dict(content='"' * 16000), finish_reason=None)])
        )
        + b"\n\n"
        for _ in range(3)
    ]
    transport.frames[0] = b"".join(chunks) + transport.frames[0]
    put = runtime.ledger._put
    fired = []
    capture = {}

    def after_accounting(table, key, body, *args):
        result = put(table, key, body, *args)
        if table == "tool_calls" and body["call"]["status"] == "succeeded" and not fired:
            fired.append(True)
            capture.update(
                before_exchange_bytes=len(encoded(runtime.ledger.exchanges(body["turn_id"]))),
                result_bytes=len(encoded(body["call"]["result"])),
            )
            if loss == "stop":
                runtime.stop_signal.set()
            else:
                clock = chat_tool_runtime.monotonic
                monkeypatch.setattr(chat_tool_runtime, "monotonic", lambda: clock() + 121)
        return result

    monkeypatch.setattr(runtime.ledger, "_put", after_accounting)
    before = runtime.scenarios.path.read_bytes()

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        await runtime.task
        transcript = runtime.ledger.transcript(turn["id"])
        runtime.storage.validate()
        capture.update(
            fired=fired,
            transcript=transcript,
            turn=runtime.storage.turn(turn["id"]),
            exchanges=runtime.ledger.exchanges(turn["id"]),
            reservation=runtime.ledger.reservation(turn["id"]),
            requests=len(transport.requests),
            fenced=runtime.storage.fenced,
        )
        record("overflow-" + loss, capture)
        assert fired == [True] and len(transport.requests) == 1
        assert runtime.scenarios.path.read_bytes() == before
        assert transcript["calls"][0]["status"] != "succeeded", (
            "late successful read committed on exchange-limit early return, "
            "bypassing original authority guard"
        )

    client.portal.call(exercise)


def test_deny_publication_uses_captured_stop_after_real_accounting(client, monkeypatch):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create")
    transport.frames.append(final_frame())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        call = (await waiting(runtime, turn["id"]))["calls"][-1]
        captured = runtime.stop_signal
        put = runtime.ledger._put
        fired = []

        def after_accounting(table, key, body, *args):
            result = put(table, key, body, *args)
            if table == "tool_decisions" and not fired:
                fired.append(True)
                captured.set()
                runtime.stop_signal = threading.Event()
            return result

        monkeypatch.setattr(runtime.ledger, "_put", after_accounting)
        body = DecisionInput(
            request_id=str(uuid4()), proposal_digest=call["proposal"]["digest"], decision="deny"
        )
        image = list(runtime.storage.db.iterdump())
        outcome = {}
        try:
            receipt, status = await runtime.decide_tool(call["id"], body)
            outcome = {"status": status, "receipt": receipt}
        except DraftError as exc:
            outcome = {"error": exc.code}
        changed = list(runtime.storage.db.iterdump()) != image
        record(
            "deny-stop-replacement",
            dict(
                fired=fired,
                original_stop=captured.is_set(),
                replacement_stop=runtime.stop_signal.is_set(),
                changed=changed,
                outcome=outcome,
                call=runtime.ledger.call(call["id"]),
            ),
        )
        try:
            assert fired == [True]
            assert outcome.get("error") == "CHAT_TOOL_APPROVAL_CONFLICT" and not changed, (
                "deny committed after captured Stop was set and runtime event was replaced"
            )
        finally:
            if runtime.active:
                await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


# Frozen actual S1 issuer output, base 9b84ca32fcf76f6d5d798a166ba691d11fecb0fb.
# Captured under root-source-only imports before production edits; not generated
# by overriding the new issuer's commitment. Includes original session/raw row.
_S1_BYTES = (
    "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"
)


def legacy_seed(client, monkeypatch, variant="operator"):
    import base64
    import zlib

    from aiddos.api import chat_tool_storage

    frozen = json.loads(zlib.decompress(base64.b64decode(_S1_BYTES)))[variant]
    runtime, _, _ = bootstrap(client)
    for name, data in frozen["files"].items():
        (runtime.storage.path.parent / name).write_bytes(base64.b64decode(data))

    def restore():
        with runtime.storage.transaction():
            for table in reversed(list(frozen["rows"])):
                runtime.storage.db.execute("DELETE FROM " + table)
            for table, rows in frozen["rows"].items():
                for row in rows:
                    runtime.storage.db.execute(
                        "INSERT INTO " + table + " VALUES (" + ",".join("?" for _ in row) + ")",
                        row,
                    )
        raw = runtime.storage.db.execute(
            "SELECT data FROM tool_grants WHERE key=?", (frozen["grant"]["id"],)
        ).fetchone()[0]
        assert raw == frozen["raw_grant"]
        runtime.storage.validate()

    client.portal.call(restore)
    # Preserve producer bytes; select its original time for the sendability probe.
    monkeypatch.setattr(chat_tool_runtime, "now", lambda: frozen["grant"]["created_at"])
    monkeypatch.setattr(chat_tool_storage, "now", lambda: frozen["grant"]["created_at"])
    runtime.grant_deadlines[frozen["grant"]["id"]] = chat_tool_runtime.monotonic() + 300
    return runtime, frozen["body"], frozen["grant"], frozen


def legacy_setup_path(client, monkeypatch):
    from test_chat_scenario_proposal_runtime import NativeBytesTransport, native_bytes

    from aiddos.api import chat_tool_transport
    from aiddos.api.chat_tool_models import ToolTurnInput

    runtime, body, grant, frozen = legacy_seed(client, monkeypatch, "append")
    raw = frozen["native_arguments"]
    transport = NativeBytesTransport(
        [
            native_bytes("configuration_read", '{ "kind" : "scenario_context" }', "read-1", True),
            native_bytes("scenario_append", raw, "write-2", True),
        ],
        True,
    )
    monkeypatch.setattr(chat_tool_transport.httpx2, "AsyncHTTPTransport", lambda **kw: transport)
    value = ToolTurnInput(
        request_id=body["turn_request_id"],
        expected_sequence=0,
        text=body["text"],
        grant_id=grant["id"],
    )
    return runtime, grant, value, transport, raw


@pytest.mark.parametrize("text", ['한😀 "quoted" \\ path', "\\uD55C\\ud83d\\ude00", '"nested"'])
@pytest.mark.parametrize("reverse", [False, True])
def test_raw_replay_chooses_one_encoding(client, monkeypatch, text, reverse):
    runtime, body, _ = bootstrap(client)
    first, second = (text, encoded(text).decode()) if reverse else (encoded(text).decode(), text)
    body["text"] = first
    grant, _ = issue(client, runtime, body)

    def forbidden(*a, **kw):
        raise AssertionError("replay reacquired mutable authority")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    assert issue(client, runtime, body) == (grant, 200)
    with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_CONFLICT"):
        issue(client, runtime, body | {"text": second})


def stored_grant(runtime, identifier):
    return json.loads(
        runtime.storage.db.execute(
            "SELECT data FROM tool_grants WHERE key=?", (identifier,)
        ).fetchone()[0]
    )


def test_private_marker_meter_and_lifecycle(client):
    from aiddos.api.chat_scenario_models import GrantV4
    from aiddos.api.chat_tool_storage import CAPS, TABLES, charge

    runtime, body, _ = bootstrap(client)
    grant, _ = issue(client, runtime, body)

    def exercise():
        stored = stored_grant(runtime, grant["id"])
        assert set(stored) == {"storage_version", "text_encoding", "grant", "authority_digest"}
        assert stored["storage_version"] == 1 and stored["text_encoding"] == "raw-utf8"
        assert stored["grant"] == grant
        assert GrantV4.model_validate(grant).model_dump() == grant
        assert CAPS["tool_grants"] == 8192
        assert len(encoded(stored)) > len(encoded(grant))
        actual = sum(
            charge(k, json.loads(v))
            for table in TABLES
            for k, v in runtime.storage.db.execute("SELECT key, data FROM " + table)
        )
        assert runtime.ledger.usage()["actual"] == actual
        assert actual == charge(grant["id"], stored)
        runtime.storage.close()
        assert runtime.storage.open()
        expired = stored_grant(runtime, grant["id"])
        assert expired == stored | {"grant": grant | {"status": "expired"}}
        runtime.storage.validate()

    client.portal.call(exercise)
    assert issue(client, runtime, body) == (grant | {"status": "expired"}, 200)
    lookup = client.get(f"/api/v1/chat/tool-grants/by-request/{body['request_id']}")
    assert lookup.json() == grant | {"status": "expired"}


@pytest.mark.parametrize(
    "mutation", ["extra", "encoding", "missing", "version", "boolean", "digest", "nested"]
)
def test_closed_private_marker_rejected_before_recovery(client, tmp_path, mutation):
    import sqlite3

    from aiddos.api.chat_storage import ChatStorage

    runtime, body, _ = bootstrap(client)
    grant, _ = issue(client, runtime, body)

    def exercise():
        stored = stored_grant(runtime, grant["id"])
        assert "grant" in stored
        if mutation == "extra":
            stored["unknown"] = None
        elif mutation == "encoding":
            stored["text_encoding"] = "legacy-json"
        elif mutation == "missing":
            del stored["text_encoding"]
        elif mutation == "version":
            stored["storage_version"] = 2
        elif mutation == "boolean":
            stored["storage_version"] = True
        elif mutation == "digest":
            stored["authority_digest"] = "f" * 64
        else:
            stored["grant"]["unknown"] = None
        recovered = ChatStorage(tmp_path / "bad.json")
        with sqlite3.connect(recovered.path) as db:
            runtime.storage.db.backup(db)
            db.execute(
                "UPDATE tool_grants SET data=? WHERE key=?", (encoded(stored).decode(), grant["id"])
            )
        recovered.path.chmod(0o600)
        before = recovered.path.read_bytes()
        with pytest.raises(DraftError, match="CHAT_STORAGE_ERROR"):
            recovered.open()
        assert recovered.path.read_bytes() == before
        recovered.close()

    client.portal.call(exercise)


@pytest.mark.parametrize("mutation", ["loss", "transplant"])
def test_bound_graph_requires_its_marker(client, monkeypatch, tmp_path, mutation):
    import sqlite3

    from aiddos.api.chat_storage import ChatStorage

    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append")

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            await waiting(runtime, turn["id"])
            stored = stored_grant(runtime, grant["id"])
            assert "grant" in stored
            if mutation == "loss":
                stored = stored["grant"]
            else:
                stored["grant"]["request_id"] = str(uuid4())
            recovered = ChatStorage(tmp_path / "tampered.json")
            with sqlite3.connect(recovered.path) as db:
                runtime.storage.db.backup(db)
                db.execute(
                    "UPDATE tool_grants SET data=? WHERE key=?",
                    (encoded(stored).decode(), grant["id"]),
                )
            recovered.path.chmod(0o600)
            before = recovered.path.read_bytes()
            with pytest.raises(DraftError, match="CHAT_STORAGE_ERROR"):
                recovered.open()
            assert recovered.path.read_bytes() == before
            recovered.close()
        finally:
            await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)


def test_new_issuer_independently_checks_actual_raw_text(client, monkeypatch):
    from aiddos.api.chat_tool_storage import ToolLedger

    runtime, body, _ = bootstrap(client)
    original = ToolLedger._grant_commitment
    monkeypatch.setattr(
        ToolLedger,
        "_grant_commitment",
        staticmethod(lambda request: original(request) | {"text_sha256": digest(request["text"])}),
    )
    before = client.portal.call(lambda: list(runtime.storage.db.iterdump()))
    with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_INVALID"):
        issue(client, runtime, body)
    assert client.portal.call(lambda: list(runtime.storage.db.iterdump())) == before


def test_actual_s1_replay_reopen_no_fresh_authority(client, monkeypatch):
    runtime, body, grant, frozen = legacy_seed(client, monkeypatch)

    def forbidden(*a, **kw):
        raise AssertionError("historical replay acquired fresh source")

    monkeypatch.setattr(runtime.worker, "ai_snapshot", forbidden)
    monkeypatch.setattr(runtime.worker, "resolve_scenario_intent", forbidden)
    assert issue(client, runtime, body) == (grant, 200)
    for changed in (body["text"] + "changed", encoded(body["text"]).decode()):
        with pytest.raises(DraftError, match="CHAT_TOOL_GRANT_CONFLICT"):
            issue(client, runtime, body | {"text": changed})

    def reopen():
        assert encoded(stored_grant(runtime, grant["id"])).decode() == frozen["raw_grant"]
        runtime.storage.close()
        assert runtime.storage.open()
        runtime.storage.validate()
        assert stored_grant(runtime, grant["id"]) == grant | {"status": "expired"}

    client.portal.call(reopen)
    clocks = dict(runtime.grant_deadlines)
    assert issue(client, runtime, body) == (grant | {"status": "expired"}, 200)
    assert runtime.grant_deadlines == clocks


def test_ontime_read_overflow_keeps_fact_without_continuation(client, monkeypatch):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_append")
    frame = (
        b"data: "
        + encoded(
            dict(choices=[dict(index=0, delta=dict(content='"' * 16000), finish_reason=None)])
        )
        + b"\n\n"
    )
    transport.frames[0] = frame * 3 + transport.frames[0]

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        await runtime.task
        read = runtime.ledger.transcript(turn["id"])["calls"][0]
        assert read["status"] == "succeeded" and read["result"] is not None
        assert runtime.storage.turn(turn["id"])["error_code"] == "CHAT_TOOL_LIMIT"
        assert len(transport.requests) == 1
        assert runtime.ledger.reservation(turn["id"])["retired"]
        runtime.storage.validate()

    client.portal.call(exercise)


@pytest.mark.parametrize("rollback_failure", [False, True])
@pytest.mark.parametrize("overflow", [False, True])
def test_read_guard_error_identity_and_rollback_truth(
    client, monkeypatch, rollback_failure, overflow
):
    import sqlite3

    from test_chat_tool_storage import admission

    from aiddos.api.chat_models import now

    runtime, grant, value, _, _ = setup_path(client, monkeypatch, "scenario_append")
    marker = RuntimeError("read publication guard marker")
    checked, denied = [], []

    def durable_image():
        with sqlite3.connect(runtime.storage.path.as_uri() + "?mode=ro", uri=True) as db:
            return list(db.iterdump())

    async def exercise():
        session, _ = runtime.storage.session(grant["session_id"])
        advanced, turn, commitment = admission(session, value.request_id)
        commitment["text"] = value.text
        turn.update(user_text=value.text, created_at=now())
        runtime.ledger._admit_scenario(
            grant["id"], advanced, turn, commitment, publication_guard=lambda: None
        )
        native = dict(
            role="assistant",
            content='"' * 48000 if overflow else "read",
            tool_calls=[
                dict(
                    id="read-1",
                    type="function",
                    function=dict(
                        name="configuration_read", arguments='{ "kind" : "scenario_context" }'
                    ),
                )
            ],
        )
        call = runtime.ledger.request_call(turn["id"], native)
        runtime.ledger.start_read(call["id"])
        result = await runtime.worker.read_scenario_configuration(
            grant,
            {"kind": "scenario_context"},
            deadline=chat_tool_runtime.monotonic() + 120,
            stop=threading.Event(),
        )
        before = durable_image()

        def authorizer(action, first, second, database, trigger):
            if rollback_failure and action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK":
                denied.append(True)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def guard():
            # This is after actual successful-call accounting and exchange handling.
            assert runtime.ledger.call(call["id"])["status"] == "succeeded"
            checked.append(True)
            raise marker

        runtime.storage.db.set_authorizer(authorizer)
        try:
            with pytest.raises(RuntimeError) as caught:
                runtime.ledger.finish_call(
                    call["id"], "succeeded", result=result, admission_guard=guard
                )
            assert caught.value is marker and checked == [True]
            assert durable_image() == before
            assert runtime.storage.fenced is rollback_failure
            assert runtime.storage.db.in_transaction is rollback_failure
            assert denied == ([True] if rollback_failure else [])
            if not rollback_failure:
                assert runtime.ledger.call(call["id"])["status"] == "executing"
            else:
                with pytest.raises(DraftError, match="CHAT_COMMIT_UNCERTAIN"):
                    runtime.ledger.grant(grant["id"])
        finally:
            runtime.storage.db.set_authorizer(None)
            runtime.storage.db.rollback()
        assert durable_image() == before

    client.portal.call(exercise)


def test_deny_replay_does_not_renew_current_authority(client, monkeypatch):
    runtime, grant, value, transport, _ = setup_path(client, monkeypatch, "scenario_create")
    transport.frames.append(final_frame())

    async def exercise():
        turn, _ = await runtime._accept_scenario_tool(grant["session_id"], value)
        try:
            call = (await waiting(runtime, turn["id"]))["calls"][-1]
            body = DecisionInput(
                request_id=str(uuid4()), proposal_digest=call["proposal"]["digest"], decision="deny"
            )
            decision, status = await runtime.decide_tool(call["id"], body)
            assert status == 201
            runtime.stop_signal.set()
            runtime.tool_deadline = runtime.tool_grant_deadline = 0
            before = list(runtime.storage.db.iterdump())
            assert await runtime.decide_tool(call["id"], body) == (decision, 200)
            assert list(runtime.storage.db.iterdump()) == before
        finally:
            await runtime.cancel(turn["id"])
            await runtime.task

    client.portal.call(exercise)
