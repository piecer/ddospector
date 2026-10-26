"""D04: distinct raw-read, record, and controlled writer-cap boundaries."""

import asyncio
from copy import deepcopy

import pytest
from chat_scenario_support import intent_for, prepare, reference, setup, worker_for

from aiddos.api import scenario_persistence as persistence
from aiddos.api import scenario_store
from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput, ScenarioState, canonical, record_digest

FIXED_TIME = "2026-10-25T12:00:00.123456+00:00"


def test_record_8192_plus_one_rejected_before_identity_or_time(tmp_path, monkeypatch):
    draft, store, value = setup(tmp_path)
    monkeypatch.setattr(scenario_store, "timestamp", lambda: FIXED_TIME)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    sizing = deepcopy(first)
    sizing["definition"]["objective"] = ""
    available = 8192 - len(canonical(sizing))
    value["objective"] = "😀" * (available // 4) + "a" * (available % 4)
    worker = worker_for(draft, store)

    def forbidden():
        pytest.fail("preparation allocated generated domain fields")

    async def exercise():
        try:
            with monkeypatch.context() as scope:
                scope.setattr(scenario_store, "uuid4", forbidden)
                scope.setattr(scenario_store, "timestamp", forbidden)
                grant, args, proposal, settings = await prepare(
                    worker, draft, store, value, base=reference(first)
                )
                too_large = deepcopy(args)
                too_large["definition"]["objective"] += "a"
                with pytest.raises(DraftError) as exc:
                    await worker.prepare_scenario(grant, too_large, settings)
                assert exc.value.code == "CHAT_INVALID_REQUEST"
            result = await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            assert len(canonical(result["scenario"])) == 8192
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("delta", [0, 1])
def test_production_raw_registry_limit_with_whitespace(tmp_path, delta):
    draft, store, value = setup(tmp_path)
    store.save(ScenarioInput(revision=0, definition=value))
    raw = store.path.read_bytes()
    store.path.write_bytes(raw + b" " * (16777216 + delta - len(raw)))
    if delta:
        with pytest.raises(DraftError) as exc:
            store.page()
        assert exc.value.code == "SCENARIO_STATE_CORRUPT"
    else:
        assert store.page()["revision"] == 1
    assert store.path.stat().st_size == 16777216 + delta


@pytest.mark.parametrize("delta", [0, -1])
def test_controlled_writer_cap_exact_canonical_candidate(tmp_path, monkeypatch, delta):
    draft, store, value = setup(tmp_path)
    monkeypatch.setattr(scenario_store, "timestamp", lambda: FIXED_TIME)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    candidate = store._read()
    record = deepcopy(first)
    record["version"] = 2
    record["digest"] = record_digest(record)
    candidate["scenarios"][0]["versions"].append(record)
    candidate["revision"] = 2
    cap = len(canonical(candidate))
    monkeypatch.setattr(scenario_store, "MAX_STATE_BYTES", cap + delta)
    before = store.path.read_bytes(), store.receipt_path.read_bytes()
    worker = worker_for(draft, store)

    async def exercise():
        try:
            if delta:
                with pytest.raises(DraftError) as exc:
                    await prepare(worker, draft, store, value, base=reference(first))
                assert exc.value.code == "CHAT_INVALID_REQUEST"
                assert before == (store.path.read_bytes(), store.receipt_path.read_bytes())
            else:
                grant, args, proposal, settings = await prepare(
                    worker, draft, store, value, base=reference(first)
                )
                await worker.save_scenario(grant, args, proposal, lambda: None, settings)
                assert len(store.path.read_bytes()) == cap
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_controlled_valid_100_by_10_quota_fixture_not_write_reachability(tmp_path):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    state = {"format_version": 1, "revision": 1000, "scenarios": []}
    for index in range(100):
        identity = {"id": "synthetic-" + str(index), "versions": []}
        for version in range(1, 11):
            record = deepcopy(first)
            record.update(id=identity["id"], version=version)
            record["digest"] = record_digest(record)
            identity["versions"].append(record)
        state["scenarios"].append(identity)
    ScenarioState.model_validate(state)
    raw = canonical(state)
    store.path.write_bytes(raw)
    frame = persistence.decode_frame(store.receipt_path.read_bytes())
    frame.update(post=persistence.digest(raw), size=len(raw))
    store.receipt_path.write_bytes(persistence.encode_frame(frame))
    worker = worker_for(draft, store)

    async def exercise():
        try:
            for base in (None, reference(state["scenarios"][0]["versions"][-1])):
                intent = intent_for(draft, store, value, base=base)
                with pytest.raises(DraftError) as exc:
                    await worker.resolve_scenario_intent(intent, draft._read().ai_settings.revision)
                assert exc.value.code == "CHAT_TOOL_LIMIT"
            assert store.path.read_bytes() == raw
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
