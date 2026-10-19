"""Prospective real encoder/ledger tests; runtime cases use labelled worker seams."""

import json
from uuid import uuid4

import pytest
from provider_fixture import Scenario
from test_chat_integration import wait_turn
from test_chat_tool_native_transport import frame, native_wire
from test_chat_tool_routes_runtime import companion
from test_chat_tool_runtime_lifecycle import world

from aiddos.api.chat_models import SAFE_INT, encoded
from aiddos.api.chat_tool_models import (
    EXCHANGE_BYTES,
    RESULT_BYTES,
    SkillCreatedResult,
    parse_arguments,
)
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_ledger import admitted, proposal_for
from tests.chat.test_chat_skill_models import arguments, receipt
from tests.chat.test_chat_skill_runtime import grant_turn, install_interface
from tests.chat.test_chat_target_ledger import native
from tests.chat.test_chat_tool_storage import STAMP


def sized_receipt(args):
    """Independent synthetic producer envelope, not an executed Skill receipt."""
    value = receipt(args)
    value["skill"]["id"] = "s" * 64
    value["audit"].update(
        id="a" * 64, entity_id="s" * 64, created_at="9999-12-31T23:59:59.99999999999999+00:00"
    )
    return SkillCreatedResult.model_validate(value).model_dump()


def large_arguments(revision=0):
    args = arguments(
        expected_draft_revision=revision,
        name="n",
        description="d",
        instructions="x",
        category="planning",
    )
    overhead = len(encoded(args)) - 1
    # Domain-valid UTF8 sized to the unchanged raw-native cap, not a raised field limit.
    size = 16384 - overhead
    return args | dict(instructions="🌍" * (size // 4) + "x" * (size % 4))


def test_full_receipt_overflow_rejected_before_proposal(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        args = large_arguments(before["audit_total"])
        raw = encoded(args).decode()
        assert len(raw.encode()) == 16384 and parse_arguments("skill_create", raw) == args
        assert len(encoded(sized_receipt(args))) > RESULT_BYTES
        provider.scenarios = (
            Scenario((native_wire(raw, name="skill_create"),)),
            Scenario.text("must not send"),
        )
        _, turn = grant_turn(product, saved)
        final = wait_turn(product, turn)
        call = companion(product, turn)["calls"][0]
        assert call["status"] == "failed" and call["error_code"] == "CHAT_TOOL_LIMIT", call
        assert call["proposal"] is call["decision"] is call["result"] is None
        assert final["error_code"] == "CHAT_TOOL_LIMIT"
        assert len(interface.preparations) == 1 and interface.writes == []
        assert len(provider.requests) == 1
        assert json.loads(product.state.read_text()) == before


def escaped_arguments(revision):
    args = arguments(
        expected_draft_revision=revision,
        name="n",
        description="d",
        instructions="x",
        category="planning",
    )
    # Two locales add four bytes per backslash, two per ordinary ASCII character.
    budget = RESULT_BYTES - len(encoded(sized_receipt(args)))
    return args | dict(instructions="x" + "\\" * (budget // 4) + "x" * ((budget % 4) // 2))


@pytest.mark.parametrize("layer", ["nested", "provider"])
def test_nested_exchange_and_full_provider_payload_admission(tmp_path, monkeypatch, layer):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        if layer == "nested":
            args = escaped_arguments(before["audit_total"])
            raw = encoded(args).decode()
            raw += " " * (16384 - len(raw.encode()))
            identifier = "\x01" * 128
            narrative = ""
        else:
            args = arguments(expected_draft_revision=before["audit_total"])
            raw, identifier, narrative = encoded(args).decode(), "provider", "N" * 60000
            original = product.runtime.context

            def history(*values):
                payload = original(*values)
                payload["messages"].insert(1, dict(role="user", content="H" * 74000))
                return payload

            monkeypatch.setattr(product.runtime, "context", history)
        projected = sized_receipt(args)
        assert len(encoded(projected)) <= RESULT_BYTES
        assistant = native("skill_create", args, identifier)
        assistant["content"] = narrative
        assistant["tool_calls"][0]["function"]["arguments"] = raw
        message = dict(
            role="tool",
            tool_call_id=identifier,
            content=encoded(dict(ok=True, result=projected, error_code=None)).decode(),
        )
        if layer == "nested":
            assert len(encoded([assistant, message])) > EXCHANGE_BYTES
        wire = (frame(dict(content=narrative)) if narrative else b"") + native_wire(
            raw, name="skill_create", identifier=identifier
        )
        provider.scenarios = (Scenario((wire,)), Scenario.text("must not send"))
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda t: bool(t["calls"]) and t["calls"][0]["status"] != "requested"
        )["calls"][0]
        try:
            assert call["status"] == "failed" and call["error_code"] == "CHAT_TOOL_LIMIT", call
            assert call["proposal"] is None and interface.writes == []
            assert wait_turn(product, turn)["error_code"] == "CHAT_TOOL_LIMIT"
            assert len(provider.requests) == 1
        finally:
            if call["status"] == "awaiting_approval":
                product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})


def test_projection_repeated_before_decision_with_current_history(tmp_path, monkeypatch):
    with world(tmp_path) as (product, provider, saved, before):
        interface = install_interface(monkeypatch, product, before)
        args = arguments(expected_draft_revision=before["audit_total"])
        provider.scenarios = (
            Scenario((native_wire(encoded(args).decode(), name="skill_create"),)),
            Scenario.text("unused"),
        )
        _, turn = grant_turn(product, saved)
        call = companion(
            product, turn, lambda t: bool(t["calls"]) and t["calls"][0]["status"] != "requested"
        )["calls"][0]
        assert call["status"] == "awaiting_approval"
        original = product.runtime.context

        def history(*values):
            payload = original(*values)
            payload["messages"].append(dict(role="user", content="H" * 131072))
            return payload

        monkeypatch.setattr(product.runtime, "context", history)
        try:
            status, failure = product.request(
                f"/api/v1/chat/tool-calls/{call['id']}/decision",
                "POST",
                dict(
                    request_id=str(uuid4()),
                    proposal_digest=call["proposal"]["digest"],
                    decision="approve",
                ),
            )
            assert status != 201 and failure["code"] == "CHAT_TOOL_LIMIT", (status, failure)
            assert companion(product, turn)["calls"][0] == call
            assert interface.writes == []
            assert product.on_loop(
                lambda: product.runtime.storage.db.execute(
                    "SELECT count(*) FROM tool_decisions"
                ).fetchone()
            ) == (0,)
            assert len(provider.requests) == 1
        finally:
            product.request(f"/api/v1/chat/turns/{turn['id']}/cancel", "POST", {})


def test_projection_uses_real_revision_and_no_domain_allocations(tmp_path, monkeypatch):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(
            turn["id"],
            native("skill_create", arguments(expected_draft_revision=SAFE_INT)),
            timestamp=STAMP,
        )

        def forbidden():
            pytest.fail("projection allocated domain identity/time")

        monkeypatch.setattr("aiddos.api.store.uuid4", forbidden)
        monkeypatch.setattr("aiddos.api.store.timestamp", forbidden)
        with pytest.raises(DraftError) as exc:
            ledger.propose(call["id"], proposal_for(call, ledger, turn), timestamp=STAMP)
        assert exc.value.code == "CHAT_INVALID_REQUEST"
        assert ledger.call(call["id"]) == call
        projected = call | dict(arguments=arguments(expected_draft_revision=SAFE_INT - 1))
        projected["proposal"] = proposal_for(projected, ledger, turn)
        result = ToolLedger.projected_receipt(projected)
        assert result["before_revision"] == SAFE_INT - 1 and result["after_revision"] == SAFE_INT
    finally:
        storage.close()


def test_exact_result_limit_and_one_byte_over_are_real_encoder_boundaries():
    from aiddos.api.chat_tool_models import validate_result

    value = sized_receipt(escaped_arguments(0))
    # Reserve one valid timestamp byte; adjust the independently valid ID/text.
    value["audit"]["id"] = "a" * 63
    value["skill"]["name"] = dict(en="nx", ko="nx")
    value["audit"]["created_at"] = value["audit"]["created_at"].replace("9+00:00", "+00:00")
    assert len(encoded(value)) == RESULT_BYTES
    assert validate_result(value) == value
    # Restore the 40th timestamp byte without violating its domain bound.
    value["audit"]["created_at"] = value["audit"]["created_at"].replace("+00:00", "9+00:00")
    assert len(encoded(value)) == RESULT_BYTES + 1
    assert SkillCreatedResult.model_validate(value)
    with pytest.raises(ValueError, match="Result byte limit"):
        validate_result(value)


@pytest.mark.parametrize("extra", [0, 1])
def test_exact_nested_exchange_boundary_before_proposal(tmp_path, extra):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        args = escaped_arguments(0)
        message = native("skill_create", args, "\x01" * 128)
        anticipated = dict(
            role="tool",
            tool_call_id="\x01" * 128,
            content=encoded(dict(ok=True, result=sized_receipt(args), error_code=None)).decode(),
        )
        remaining = EXCHANGE_BYTES - len(encoded([message, anticipated]))
        assert 0 <= remaining < 65536
        message["content"] = "N" * (remaining + extra)
        assert len(encoded([message, anticipated])) == EXCHANGE_BYTES + extra
        call = ledger.request_call(turn["id"], message, timestamp=STAMP)
        proposal = proposal_for(call, ledger, turn)
        if extra:
            with pytest.raises(DraftError) as exc:
                ledger.propose(call["id"], proposal, timestamp=STAMP)
            assert exc.value.code == "CHAT_TOOL_LIMIT"
            assert ledger.call(call["id"]) == call
        else:
            ledger.propose(call["id"], proposal, timestamp=STAMP)
            assert (
                len(encoded(ledger.exchanges(turn["id"])))
                + ledger.reservation(turn["id"])["exchange_hold"]
                == EXCHANGE_BYTES
            )
    finally:
        storage.close()


def test_complete_provider_meter_exact_and_one_byte_over():
    from aiddos.api.chat_tool_models import PAYLOAD_BYTES
    from aiddos.api.chat_tool_runtime import schemas, tool_prompt

    grant = dict(schema_version=3, scope="skill_create")
    args = arguments()
    payload = dict(
        model="owned-local",
        stream=True,
        messages=[
            dict(role="system", content=tool_prompt(grant)),
            dict(role="user", content=""),
            native("skill_create", args, 'escaped"\\'),
            dict(
                role="tool",
                tool_call_id='escaped"\\',
                content=encoded(
                    dict(ok=True, result=sized_receipt(args), error_code=None)
                ).decode(),
            ),
        ],
        tools=schemas(grant),
    )
    payload["messages"][1]["content"] = "H" * (PAYLOAD_BYTES - len(encoded(payload)))
    assert len(ToolLedger.check_payload(payload)) == PAYLOAD_BYTES
    payload["messages"][1]["content"] += "H"
    with pytest.raises(DraftError) as exc:
        ToolLedger.check_payload(payload)
    assert exc.value.code == "CHAT_CONTEXT_LIMIT"


@pytest.mark.parametrize("phase", ["proposal", "decision"])
def test_reservation_copies_are_rechecked_before_publication(tmp_path, phase):
    from tests.chat.test_chat_tool_storage import uid

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(turn["id"], native("skill_create", arguments()), timestamp=STAMP)
        proposal = proposal_for(call, ledger, turn)
        if phase == "decision":
            ledger.propose(call["id"], proposal, timestamp=STAMP)
        with storage.transaction():
            reservation = ledger.reservation(turn["id"])
            reservation["remaining"] = reservation["exchange_hold"]
            ledger._raw_put("tool_reservations", turn["id"], reservation)
        before = ledger.call(call["id"])
        with pytest.raises(DraftError) as exc:
            if phase == "proposal":
                ledger.propose(call["id"], proposal, timestamp=STAMP)
            else:
                ledger.decide(
                    call["id"],
                    dict(request_id=uid(), proposal_digest=proposal["digest"], decision="approve"),
                    active_turn_id=turn["id"],
                    timestamp=STAMP,
                )
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        assert ledger.call(call["id"]) == before
        assert not ledger.binding(turn["id"])["write_slot"]
        assert storage.db.execute("SELECT count(*) FROM tool_decisions").fetchone() == (0,)
    finally:
        storage.close()


def test_actual_charged_copies_and_projection_bounds(tmp_path):
    from aiddos.api.chat_tool_models import CALL_BYTES, TURN_RESERVATION
    from aiddos.api.chat_tool_storage import TABLES, charge
    from tests.chat.test_chat_skill_ledger import approved

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        args = arguments(instructions="🌍" * 3000 + '"\\\r\n\t' * 100)
        call = approved(ledger, turn, args)
        projected = ToolLedger.projected_receipt(call)
        assert projected == sized_receipt(args)
        before = len(encoded(ledger.exchanges(turn["id"])))
        hold = ledger.reservation(turn["id"])["exchange_hold"]
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=projected, timestamp=STAMP
        )
        assert retained
        assert len(encoded(ledger.exchanges(turn["id"]))) - before <= hold
        assert len(encoded(saved)) < CALL_BYTES
        assert len(encoded(dict(turn_id=turn["id"], call=saved))) < CALL_BYTES
        assert len(encoded(ledger.transcript(turn["id"]))) < TURN_RESERVATION
        assert ledger.usage()["actual"] == sum(
            charge(k, v) for table in TABLES for k, v in ledger._rows(table)
        )
        storage.validate()
    finally:
        storage.close()


@pytest.mark.parametrize("table,cap", [("tool_calls", 262144), ("tool_exchanges", 98304)])
def test_record_meter_exact_and_one_byte_over_not_a_valid_graph(tmp_path, table, cap):
    """Meter-only: strings exercise SQL record caps, NOT valid Call/transcript shapes."""
    storage, ledger, _, _ = admitted(tmp_path)

    class Rollback(Exception):
        pass

    try:
        for extra in (0, 1):
            value = "M" * (cap - 2 + extra)
            assert len(encoded(value)) == cap + extra
            if extra:
                with pytest.raises(DraftError) as exc, storage.transaction():
                    ledger._put(table, "meter-only", value)
                assert exc.value.code == "CHAT_TOOL_LIMIT"
            else:
                with pytest.raises(Rollback), storage.transaction():
                    ledger._put(table, "meter-only", value)
                    assert ledger._get(table, "meter-only") == value
                    raise Rollback
        assert ledger._get(table, "meter-only") is None
    finally:
        storage.close()


def test_pool_meter_exact_and_one_byte_over_not_a_valid_graph(tmp_path):
    """Meter-only raw SQL values; independent charge includes keys and JSON wrappers."""
    from aiddos.api.chat_tool_storage import POOL_BYTES, charge
    from tests.chat.test_chat_tool_storage import setup_store

    storage, _ = setup_store(tmp_path)
    ledger = ToolLedger(storage)

    class Rollback(Exception):
        pass

    try:
        with pytest.raises(Rollback), storage.transaction():
            budget = POOL_BYTES - charge("last", "")
            index = 0
            while budget:
                key = f"meter-{index}"
                overhead = charge(key, "")
                width = min(250000, budget - overhead)
                assert width >= 0
                value = "x" * width
                ledger._raw_put("tool_calls", key, value)
                budget -= charge(key, value)
                index += 1
            ledger._put("tool_calls", "last", "")
            assert ledger.usage()["actual"] == POOL_BYTES
            with pytest.raises(DraftError) as exc:
                ledger._put("tool_calls", "last", "x")
            assert exc.value.code == "CHAT_TOOL_LIMIT"
            raise Rollback
        storage.validate()
    finally:
        storage.close()


def test_physical_sqlite_exact_and_one_byte_over(tmp_path):
    """Real owned DB; padding is a physical-size witness, not logical Skill data."""
    from aiddos.api.chat_storage import ChatStorage
    from tests.chat.test_chat_tool_storage import setup_store

    storage, _ = setup_store(tmp_path)
    path = storage.path
    storage.close()
    with path.open("r+b") as handle:
        handle.truncate(16777216)
    exact = ChatStorage(tmp_path / "draft.json")
    try:
        assert exact.open()
        assert path.stat().st_size == 16777216
        page_size = exact.db.execute("PRAGMA page_size").fetchone()[0]
        assert exact.db.execute("PRAGMA max_page_count").fetchone()[0] * page_size == 16777216
    finally:
        exact.close()
    with path.open("ab") as handle:
        handle.write(b"\x00")
    over = ChatStorage(tmp_path / "draft.json")
    try:
        with pytest.raises(DraftError) as exc:
            over.open()
        assert exc.value.code == "CHAT_STORAGE_ERROR"
        assert path.stat().st_size == 16777217
    finally:
        over.close()
