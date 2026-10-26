"""D06-D10: finite real persistence boundaries and native ownership."""

import asyncio
import threading
from time import monotonic

import pytest
from chat_scenario_support import prepare, reference, setup, worker_for
from test_scenario_retention import SAVE_FAULTS, IOFault

from aiddos.api import scenario_persistence as persistence
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput, canonical, record_digest


@pytest.mark.parametrize("gate", [1, 2])
@pytest.mark.parametrize("reason", ["stop", "deadline", "expiry", "revoke"])
def test_final_guard_retains_prepared_and_never_replaces(tmp_path, monkeypatch, gate, reason):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    old = store.path.read_bytes(), draft.path.read_bytes()
    worker = worker_for(draft, store)
    calls, replacements = [], []
    actual_replace = persistence.os.replace

    def replace(*args):
        replacements.append(args)
        return actual_replace(*args)

    monkeypatch.setattr(persistence.os, "replace", replace)

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(
                worker, draft, store, value, base=reference(first)
            )
            code = {
                "stop": "CHAT_CANCELLED",
                "deadline": "CHAT_TIMEOUT",
                "expiry": "CHAT_TIMEOUT",
                "revoke": "CHAT_TOOL_DENIED",
            }[reason]

            def guard():
                calls.append(True)
                if len(calls) == gate:
                    if gate == 2:
                        assert (store.pending_path / "publish").stat().st_ino == (
                            store.pending_path / "candidate"
                        ).stat().st_ino
                        assert (
                            persistence.decode_frame(store.receipt_path.read_bytes())["phase"]
                            == "PREPARED"
                        )
                    raise DraftError(code)

            with pytest.raises(DraftError) as exc:
                await worker.save_scenario(grant, args, proposal, guard, settings)
            assert exc.value.code == code and len(calls) == gate and replacements == []
            assert old == (store.path.read_bytes(), draft.path.read_bytes())
            assert store.coordinator.blocked is (gate == 2)
            assert {p.name for p in store.pending_path.iterdir()} == (
                {"candidate", "publish"} if gate == 2 else set()
            )
            assert persistence.decode_frame(store.receipt_path.read_bytes())["phase"] == (
                "PREPARED" if gate == 2 else "CLEAN"
            )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("role,operation", SAVE_FAULTS)
def test_chat_syscall_fault_matrix(tmp_path, monkeypatch, role, operation):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    old = store.path.read_bytes(), draft.path.read_bytes()
    worker = worker_for(draft, store)

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(
                worker, draft, store, value, base=reference(first)
            )
            with monkeypatch.context() as scope:
                fault = IOFault(scope, store.path, role, operation)
                with pytest.raises(DraftError) as exc:
                    await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            uncertain = (
                role in {"PUBLISHED", "CLEAN", "slot-published", "parent-published", "slot-retired"}
                or operation == "retire"
            )
            assert fault.fired == [(role, operation)] and not fault.fds
            assert fault.published is uncertain
            assert exc.value.code == ("CHAT_TOOL_UNCERTAIN" if uncertain else "CHAT_STORAGE_ERROR")
            assert store.coordinator.blocked and not worker.busy
            assert draft.path.read_bytes() == old[1]
            if not uncertain:
                assert store.path.read_bytes() == old[0]
            else:
                assert store.history(first["id"])["versions"][0] == first
                assert store.page()["revision"] == 2
            retained = {
                p: p.read_bytes()
                for p in [store.path, store.receipt_path, *store.pending_path.iterdir()]
            }
            state = await worker.scenario_state()
            assert state["registry_write_status"] == "quarantined"
            assert all(p.read_bytes() == raw for p, raw in retained.items())
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("damage", ["io", "prior", "other", "selected", "revision", "domain_error"])
def test_postpublication_full_readback_before_retirement(tmp_path, monkeypatch, damage):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    other = store.save(ScenarioInput(revision=1, definition=value))["scenario"]
    worker = worker_for(draft, store)
    real_read = persistence.read_registry
    real_frame = persistence.write_frame
    published, fired = [], []

    def frame(path, raw, **kwargs):
        result = real_frame(path, raw, **kwargs)
        if persistence.decode_frame(raw)["phase"] == "PUBLISHED":
            published.append(True)
        return result

    def read(path):
        if published and not fired:
            fired.append(True)
            assert (store.pending_path / "candidate").exists()
            if damage == "io":
                raise OSError("readback failure")
            if damage == "domain_error":
                raise DraftError("CHAT_CANCELLED")
            raw, state = real_read(path)
            if damage == "revision":
                # Valid but wrong whole state: omit the appended record.
                state["scenarios"][0]["versions"].pop()
                state["revision"] -= 1
            else:
                index, version = {"prior": (0, 0), "other": (1, 0), "selected": (0, 1)}[damage]
                record = state["scenarios"][index]["versions"][version]
                record["definition"]["name"] = "valid recomputed different record"
                record["digest"] = record_digest(record)
            path.write_bytes(canonical(state))
            return real_read(path)
        return real_read(path)

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(
                worker, draft, store, value, base=reference(first)
            )
            with monkeypatch.context() as scope:
                scope.setattr(persistence, "write_frame", frame)
                scope.setattr(persistence, "read_registry", read)
                with pytest.raises(DraftError) as exc:
                    await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            assert fired == [True] and published == [True]
            assert exc.value.code == "CHAT_TOOL_UNCERTAIN"
            assert store.coordinator.blocked
            assert (store.pending_path / "candidate").exists()
            assert persistence.decode_frame(store.receipt_path.read_bytes())["phase"] == "PUBLISHED"
            assert other["id"] != first["id"]
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("boundary", ["candidate", "replaced"])
@pytest.mark.parametrize("signal", ["cancel", "deadline", "shutdown"])
def test_blocked_native_owner_drains_and_late_signal_cannot_rollback(
    tmp_path, monkeypatch, boundary, signal
):
    from aiddos.api import chat_tool_domain

    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    old = store.path.read_bytes()
    worker = worker_for(draft, store)
    entered, release = threading.Event(), threading.Event()
    clock = [0.0]
    monkeypatch.setattr(chat_tool_domain, "monotonic", lambda: clock[0])
    real_fsync, real_replace = persistence.os.fsync, persistence.os.replace

    def barrier():
        entered.set()
        assert release.wait(5), "test release deadline"

    def fsync(fd):
        if (
            boundary == "candidate"
            and not entered.is_set()
            and persistence.os.readlink(f"/proc/self/fd/{fd}")
            == str(store.pending_path / "candidate")
        ):
            barrier()
        return real_fsync(fd)

    def replace(*args):
        result = real_replace(*args)
        if boundary == "replaced":
            barrier()
        return result

    async def exercise():
        shutdown = None
        try:
            grant, args, proposal, settings = await prepare(
                worker, draft, store, value, base=reference(first)
            )
            monkeypatch.setattr(persistence.os, "fsync", fsync)
            monkeypatch.setattr(persistence.os, "replace", replace)
            task = asyncio.create_task(
                worker.save_scenario(grant, args, proposal, lambda: None, settings, deadline=10.0)
            )
            end = monotonic() + 4
            while not entered.is_set() and monotonic() < end:
                await asyncio.sleep(0.001)
            assert entered.is_set() and worker.busy
            if signal == "cancel":
                task.cancel()
            elif signal == "deadline":
                clock[0] = 20.0
            else:
                shutdown = asyncio.create_task(worker.shutdown())
            await asyncio.sleep(0)
            assert worker.busy and not task.done()
            with pytest.raises(DraftError) as busy:
                await worker.scenario_state()
            assert busy.value.code == "CHAT_BUSY"
            release.set()
            if boundary == "candidate":
                with pytest.raises(DraftError) as exc:
                    await task
                assert exc.value.code == (
                    "CHAT_TIMEOUT" if signal == "deadline" else "CHAT_CANCELLED"
                )
                assert store.path.read_bytes() == old
                assert store.coordinator.blocked
                assert (store.pending_path / "candidate").exists()
            else:
                result = await task
                assert result["kind"] == "scenario_appended"
                assert result["scenario"] == store.history(first["id"])["versions"][1]
                assert not store.coordinator.blocked
                assert persistence.decode_frame(store.receipt_path.read_bytes())["phase"] == "CLEAN"
            if shutdown is not None:
                await shutdown
            assert not worker.busy
        finally:
            release.set()
            await worker.shutdown()

    asyncio.run(exercise())
