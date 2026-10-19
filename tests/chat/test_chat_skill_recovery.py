"""Real SQLite restart/closed graph tests. No worker dispatched on recovery."""

import pytest

from aiddos.api.chat_models import encoded
from aiddos.api.chat_storage import ChatStorage
from aiddos.api.chat_tool_storage import ToolLedger
from aiddos.api.errors import DraftError
from tests.chat.test_chat_skill_ledger import admitted, approved
from tests.chat.test_chat_skill_models import arguments, receipt
from tests.chat.test_chat_target_ledger import native
from tests.chat.test_chat_tool_storage import STAMP, uid
from tests.chat.test_chat_tool_storage_limits import terminal


def test_executing_restart_is_uncertain_without_redispatch(tmp_path):
    storage, ledger, turn, grant = admitted(tmp_path)
    call = approved(ledger, turn)
    storage.close()
    reopened = ChatStorage(tmp_path / "draft.json")
    try:
        assert reopened.open()
        recovered = ToolLedger(reopened)
        assert recovered.call(call["id"])["status"] == "uncertain"
        assert recovered.call(call["id"])["result"] is None
        assert recovered.fence()["call_ids"] == [call["id"]]
        assert recovered.reservation(turn["id"])["remaining"] == 8192
        assert recovered.grant(grant["id"])["schema_version"] == 3
        assert not (tmp_path / "draft.json").exists()
        reopened.validate()
    finally:
        reopened.close()


def test_v3_graph_rejects_second_write_attempt(tmp_path):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = ledger.request_call(turn["id"], native("skill_create", arguments()), timestamp=STAMP)
        ledger.finish_call(call["id"], "failed", error_code="CHAT_INVALID_REQUEST", timestamp=STAMP)
        with pytest.raises(DraftError) as exc:
            ledger.request_call(
                turn["id"], native("skill_create", arguments(), "second"), timestamp=STAMP
            )
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        # A corrupt stored graph must also fail, not only the new-request guard.
        with storage.transaction():
            ledger._append(turn["id"], native("skill_create", arguments(), "forged-second"))
            ledger._save_call(
                turn["id"], call | dict(id=uid(), index=1, provider_call_id="forged-second")
            )
        with pytest.raises(ValueError, match="attempt count"):
            ledger.validate()
    finally:
        storage.close()


def test_saved_fact_survives_late_exchange_failure_and_restart(tmp_path):
    storage, ledger, turn, _ = admitted(tmp_path)
    try:
        call = approved(ledger, turn)
        result = receipt(call["arguments"])
        saved, retained = ledger.finish_call(
            call["id"], "succeeded", result=result, timestamp=STAMP
        )
        assert retained and saved["result"] == result
        with pytest.raises(DraftError) as exc:
            ledger.append_final(turn["id"], "\x01" * 65536)
        assert exc.value.code == "CHAT_TOOL_LIMIT"
        terminal(storage, turn)
        ledger.retire(turn["id"], owner_idle=True)
        saved_bytes = encoded(ledger.call(call["id"]))
        storage.validate()
    finally:
        storage.close()
    reopened = ChatStorage(tmp_path / "draft.json")
    try:
        assert reopened.open()
        assert encoded(ToolLedger(reopened).call(call["id"])) == saved_bytes
    finally:
        reopened.close()
