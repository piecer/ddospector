"""Real SQLite restart/graph proofs, no domain replay implementation."""

import pytest

from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from tests.chat.test_chat_target_ledger import admitted, approved, native
from tests.chat.test_chat_tool_storage import STAMP


def test_executing_target_restart_is_uncertain_and_fenced(tmp_path):
    storage, ledger, turn, grant = admitted(tmp_path)
    call = approved(ledger, turn)
    storage.close()
    reopened = ChatStorage(tmp_path / "draft.json")
    try:
        assert reopened.open()
        recovered = ToolLedger(reopened)
        assert recovered.call(call["id"])["status"] == "uncertain"
        assert recovered.fence()["call_ids"] == [call["id"]]
        assert recovered.grant(grant["id"])["schema_version"] == 2
        assert recovered.reservation(turn["id"])["remaining"] == 8192
        reopened.validate()
    finally:
        reopened.close()


def test_cross_scope_stored_graph_rejected(tmp_path):
    storage, ledger, turn, grant = admitted(tmp_path)
    try:
        ledger.request_call(
            turn["id"], native("configuration_read", dict(kind="agent_profile")), timestamp=STAMP
        )
    except DraftError as exc:
        assert exc.code == "CHAT_TOOL_DENIED"
    # Forge a complete otherwise valid Agent graph under a target grant.
    try:
        legacy = {k: v for k, v in grant.items() if k not in ("scope", "proposal_tools")}
        legacy.update(
            schema_version=1,
            status="consumed",
            read_scope=["agent_profile", "skills", "skill"],
            proposal_fields=["name", "skill_ids"],
        )
        with storage.transaction():
            ledger._raw_put("tool_grants", grant["id"], legacy)
        ledger.request_call(
            turn["id"], native("configuration_read", dict(kind="agent_profile")), timestamp=STAMP
        )
        with storage.transaction():
            ledger._raw_put("tool_grants", grant["id"], grant | {"status": "consumed"})
        with pytest.raises(ValueError, match="scope"):
            ledger.validate()
    finally:
        storage.close()


def test_failed_target_attempt_consumes_the_only_write_opportunity(tmp_path):
    storage, ledger, turn, _ = admitted(tmp_path)
    args = dict(expected_draft_revision=0, name="new", address="host", kind="DUT")
    try:
        call = ledger.request_call(turn["id"], native("target_create", args), timestamp=STAMP)
        ledger.finish_call(call["id"], "failed", error_code="CHAT_INVALID_REQUEST", timestamp=STAMP)
        with pytest.raises(DraftError) as exc:
            ledger.request_call(
                turn["id"], native("target_create", args, "second"), timestamp=STAMP
            )
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        assert len(ledger.transcript(turn["id"])["calls"]) == 1
    finally:
        storage.close()


def test_successful_target_fact_survives_later_exchange_overflow_and_restart(tmp_path):
    from aiddos.api.chat_models import encoded
    from tests.chat.test_chat_target_ledger import receipt_for
    from tests.chat.test_chat_tool_storage_limits import terminal

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = approved(ledger, turn)
        # A later final-text envelope failure cannot relabel the receipt.
        result = receipt_for(call)
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=result, timestamp=STAMP
        )
        assert retained
        with pytest.raises(DraftError) as exc:
            ledger.append_final(turn["id"], "\x01" * 65536)
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        terminal(storage, turn)
        ledger.retire(turn["id"], owner_idle=True)
        saved_bytes = encoded(ledger.call(call["id"]))
        assert saved["result"] == result
        storage.validate()
    finally:
        storage.close()
    reopened = ChatStorage(tmp_path / "draft.json")
    try:
        assert reopened.open()
        assert encoded(ToolLedger(reopened).call(call["id"])) == saved_bytes
    finally:
        reopened.close()


def test_v2_graph_cannot_retain_a_second_target_attempt(tmp_path):
    from tests.chat.test_chat_tool_storage import uid

    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        args = dict(expected_draft_revision=0, name="x", address="host", kind="DUT")
        call = ledger.request_call(turn["id"], native("target_create", args), timestamp=STAMP)
        ledger.finish_call(call["id"], "failed", error_code="CHAT_INVALID_REQUEST", timestamp=STAMP)
        second = call | dict(id=uid(), index=1, provider_call_id="forged-second")
        with storage.transaction():
            ledger._append(turn["id"], native("target_create", args, "forged-second"))
            ledger._save_call(turn["id"], second)
        with pytest.raises(ValueError, match="attempt count"):
            ledger.validate()
    finally:
        storage.close()
