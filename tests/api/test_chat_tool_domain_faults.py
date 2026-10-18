import asyncio
import os
from uuid import uuid4

import pytest

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.errors import DraftError
from aiddos.api.models import AgentProfileInput, AuditEvent, DraftState
from aiddos.api.store import DraftStore, timestamp


def test_guard_runs_after_file_sync_immediately_before_replace_and_can_refuse(
    tmp_path, monkeypatch
):
    draft = DraftStore(tmp_path / "draft.json")
    draft.save_agent_profile(AgentProfileInput(name="Original", skill_ids=[], mcp_server_ids=[]))
    before = draft.path.read_bytes()
    events = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd):
        events.append("sync")
        return real_sync(fd)

    def replace(*args):
        events.append("replace")
        return real_replace(*args)

    def deny():
        events.append("guard")
        raise DraftError("CHAT_CANCELLED")

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_CANCELLED$"):
                await worker.update_agent_profile(1, "Denied", [], deny)
            assert events == ["sync", "guard"]
            assert draft.path.read_bytes() == before
            assert list(tmp_path.glob(".ui-drafts-*")) == []
            events.clear()
            await worker.update_agent_profile(1, "Allowed", [], lambda: events.append("guard"))
            assert events == ["sync", "guard", "replace", "sync"]
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "seam", ["file_sync", "replace", "directory_sync", "readback", "wrong_readback"]
)
def test_fault_seams_fire_and_distinguish_prepublication_from_uncertainty(
    tmp_path, monkeypatch, seam
):
    draft = DraftStore(tmp_path / "draft.json")
    draft.save_agent_profile(AgentProfileInput(name="Original", skill_ids=[], mcp_server_ids=[]))
    original = draft.path.read_bytes()
    real_sync, real_replace, real_read = os.fsync, os.replace, draft._read
    fired = []
    sync_calls = []
    published = []

    def sync(fd):
        sync_calls.append(fd)
        if (
            seam == "file_sync"
            and len(sync_calls) == 1
            or seam == "directory_sync"
            and len(sync_calls) == 2
        ):
            fired.append(seam)
            raise OSError("private failure text")
        return real_sync(fd)

    def replace(*args):
        if seam == "replace":
            fired.append(seam)
            raise OSError("private failure text")
        result = real_replace(*args)
        published.append(True)
        return result

    def read():
        if published and seam in {"readback", "wrong_readback"}:
            fired.append(seam)
            if seam == "readback":
                raise DraftError("STATE_UNAVAILABLE")
            state = real_read()
            state.audit[-1].id = "foreign-event"
            return state
        return real_read()

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(draft, "_read", read)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            expected = (
                "CHAT_STORAGE_ERROR" if seam in {"file_sync", "replace"} else "CHAT_TOOL_UNCERTAIN"
            )
            with pytest.raises(DraftError, match="^" + expected + "$"):
                await worker.update_agent_profile(1, "Published", [], lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert fired == [seam]
    if seam in {"file_sync", "replace"}:
        assert not published
        assert draft.path.read_bytes() == original
    else:
        assert published == [True]
        assert real_read().agent_profile.name == "Published"
        assert real_read().audit_total == 2
    assert list(tmp_path.glob(".ui-drafts-*")) == []


def test_write_fault_seam_after_publication_is_uncertain_not_a_lost_exception(
    tmp_path, monkeypatch
):
    draft = DraftStore(tmp_path / "draft.json")
    real_write = draft._write
    fired = []

    def write(state, **kwargs):
        real_write(state, **kwargs)
        fired.append(True)
        raise RuntimeError("private failure after actual write")

    monkeypatch.setattr(draft, "_write", write)

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_TOOL_UNCERTAIN$"):
                await worker.update_agent_profile(0, "Actually saved", [], lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert fired == [True]
    assert draft._read().agent_profile.name == "Actually saved"
    assert draft._read().audit_total == 1


def test_exhausted_domain_audit_counter_is_fixed_prepublication_failure(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    state = DraftState(
        audit_total=9007199254740991,
        audit=[
            AuditEvent(
                id=str(uuid4()),
                action="agent_profile.updated",
                entity_id="agent-profile",
                created_at=timestamp(),
            )
            for _ in range(500)
        ],
    )
    draft._write(state)
    original = draft.path.read_bytes()

    async def exercise():
        worker = DomainWorker(draft)
        try:
            with pytest.raises(DraftError, match="^CHAT_INVALID_REQUEST$"):
                await worker.update_agent_profile(state.audit_total, "Not saved", [], lambda: None)
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
    assert draft.path.read_bytes() == original
