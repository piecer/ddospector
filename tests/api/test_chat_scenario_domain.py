"""D01: actual domain publication; no ledger success is inferred here."""

import asyncio
import json
from copy import deepcopy

import pytest
from chat_scenario_support import intent_for, prepare, reference, setup, worker_for
from scenario_producer import digest

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput


def test_actual_create_exact_approval_and_no_preparation_effects(tmp_path, monkeypatch):
    draft, store, value = setup(tmp_path)
    before = draft.path.read_bytes()
    files = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    worker = worker_for(draft, store)

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(worker, draft, store, value)
            assert set(proposal) == {
                "expected_scenario_revision",
                "expected_draft_revision",
                "before",
                "after",
                "snapshots",
                "input_source",
                "inputs_digest",
            }
            assert proposal["before"] is None and proposal["after"] == value
            assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == files
            approved = deepcopy(proposal)
            guards = []

            def approval():
                assert proposal == approved
                guards.append(True)

            result = await worker.save_scenario(grant, args, proposal, approval, settings)
            assert len(guards) == 2
            assert set(result) == {
                "kind",
                "before_scenario_revision",
                "after_scenario_revision",
                "source_draft_revision",
                "scenario",
                "execution_enabled",
            }
            record = result["scenario"]
            assert result == {
                "kind": "scenario_created",
                "before_scenario_revision": 0,
                "after_scenario_revision": 1,
                "source_draft_revision": grant["intent"]["expected_draft_revision"],
                "scenario": record,
                "execution_enabled": False,
            }
            assert record["version"] == 1 and record["definition"] == value
            assert record["digest"] == digest(record)
            assert all(record[k] == v for k, v in proposal["snapshots"].items())
            assert json.loads(store.path.read_bytes())["scenarios"][0]["versions"] == [record]
            assert store.history(record["id"])["versions"] == [record]
            assert draft.path.read_bytes() == before
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_append_old_source_independent_latest_base_and_one_winner(tmp_path):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    changed = deepcopy(value)
    changed["policy_version"] = "new policy"
    second = store.save(ScenarioInput(revision=1, definition=changed), first["id"])["scenario"]
    other = store.save(ScenarioInput(revision=2, definition=value))["scenario"]
    before = draft.path.read_bytes()
    worker = worker_for(draft, store)

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(
                worker,
                draft,
                store,
                value,
                base=reference(second),
                source={"source": "scenario_version", "reference": reference(first)},
            )
            assert proposal["before"] == second and proposal["after"] == value
            result = await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            third = result["scenario"]
            assert result["kind"] == "scenario_appended"
            assert result["before_scenario_revision"] == 3
            assert result["after_scenario_revision"] == 4
            assert third["id"] == first["id"] and third["version"] == 3
            assert store.history(first["id"])["versions"] == [first, second, third]
            assert store.history(other["id"])["versions"] == [other]
            committed = store.path.read_bytes()
            with pytest.raises(DraftError) as exc:
                await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            assert exc.value.code == "CHAT_TOOL_CONFLICT"
            assert store.path.read_bytes() == committed and draft.path.read_bytes() == before
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "field,bad",
    [
        ("expected_scenario_revision", False),
        ("expected_scenario_revision", 0.0),
        ("expected_draft_revision", 2.0),
        ("source_extra", True),
        ("intent_extra", True),
        ("max_pps", True),
        ("max_pps", "10"),
        ("max_pps", 10.0),
    ],
)
def test_literal_intent_rejected_without_effects(tmp_path, field, bad):
    draft, store, value = setup(tmp_path)
    intent = intent_for(draft, store, value)
    if field == "max_pps":
        intent["input_source"]["inputs"]["traffic_budget"][field] = bad
    elif field == "source_extra":
        intent["input_source"]["extra"] = bad
    else:
        intent[field] = bad
    before = draft.path.read_bytes()
    worker = worker_for(draft, store)

    async def exercise():
        try:
            with pytest.raises(DraftError) as exc:
                await worker.resolve_scenario_intent(intent, draft._read().ai_settings.revision)
            assert exc.value.code == "CHAT_INVALID_REQUEST"
            assert not store.path.exists() and not store.receipt_path.exists()
            assert draft.path.read_bytes() == before
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("registry", "CHAT_TOOL_CONFLICT"),
        ("draft", "CHAT_TOOL_CONFLICT"),
        ("settings", "CHAT_TOOL_CONFLICT"),
        ("base_id", "CHAT_NOT_FOUND"),
        ("base_version", "CHAT_TOOL_CONFLICT"),
        ("base_digest", "CHAT_TOOL_CONFLICT"),
        ("source_digest", "CHAT_TOOL_CONFLICT"),
        ("source_missing", "CHAT_NOT_FOUND"),
        ("target_missing", "CHAT_INVALID_REQUEST"),
        ("sink_kind", "CHAT_INVALID_REQUEST"),
    ],
)
def test_independent_stale_tokens_sources_and_references(tmp_path, mutation, code):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    second = store.save(ScenarioInput(revision=1, definition=value), first["id"])["scenario"]
    intent = intent_for(draft, store, value, base=reference(second))
    settings = draft._read().ai_settings.revision
    if mutation == "registry":
        intent["expected_scenario_revision"] -= 1
    elif mutation == "draft":
        intent["expected_draft_revision"] -= 1
    elif mutation == "settings":
        settings += 1
    elif mutation == "base_id":
        intent["base"]["id"] = "absent"
    elif mutation == "base_version":
        intent["base"] = reference(first)
    elif mutation == "base_digest":
        intent["base"]["digest"] = "0" * 64
    elif mutation.startswith("source_"):
        ref = reference(first)
        ref["digest" if mutation == "source_digest" else "id"] = "0" * 64
        intent["input_source"] = {"source": "scenario_version", "reference": ref}
    elif mutation == "target_missing":
        intent["input_source"]["inputs"]["target_id"] = "absent"
    else:
        intent["input_source"]["inputs"]["sink_id"] = value["target_id"]
    before = store.path.read_bytes(), draft.path.read_bytes(), store.receipt_path.read_bytes()
    worker = worker_for(draft, store)

    async def exercise():
        try:
            with pytest.raises(DraftError) as exc:
                await worker.resolve_scenario_intent(intent, settings)
            assert exc.value.code == code
            assert before == (
                store.path.read_bytes(),
                draft.path.read_bytes(),
                store.receipt_path.read_bytes(),
            )
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("args_invalid", "CHAT_INVALID_REQUEST"),
        ("args_protected", "CHAT_INVALID_REQUEST"),
        ("grant_float", "CHAT_TOOL_CONFLICT"),
        ("grant_digest", "CHAT_TOOL_CONFLICT"),
        ("grant_settings", "CHAT_TOOL_CONFLICT"),
        ("proposal_bool", "CHAT_TOOL_CONFLICT"),
        ("proposal_extra", "CHAT_TOOL_CONFLICT"),
        ("proposal_operation", "CHAT_TOOL_CONFLICT"),
        ("snapshot", "CHAT_TOOL_CONFLICT"),
        ("definition", "CHAT_TOOL_CONFLICT"),
    ],
)
def test_execution_revalidates_literal_approval_before_mutation(tmp_path, mutation, code):
    draft, store, value = setup(tmp_path)
    worker = worker_for(draft, store)
    before = draft.path.read_bytes()

    async def exercise():
        try:
            grant, args, proposal, settings = await prepare(worker, draft, store, value)
            if mutation == "args_invalid":
                args["definition"]["ip_version"] = 4.0
            elif mutation == "args_protected":
                args["definition"]["traffic_budget"] = value["traffic_budget"]
            elif mutation == "grant_float":
                grant["resolved_inputs"]["traffic_budget"]["max_pps"] = 10.0
            elif mutation == "grant_digest":
                grant["inputs_digest"] = "0" * 64
            elif mutation == "grant_settings":
                grant["settings_revision"] += 1
            elif mutation == "proposal_bool":
                proposal["expected_scenario_revision"] = False
            elif mutation == "proposal_extra":
                proposal["extra"] = True
            elif mutation == "proposal_operation":
                proposal["operation"] = "scenario_append"
            elif mutation == "snapshot":
                proposal["snapshots"]["target_snapshot"]["name"] = "changed"
            else:
                proposal["after"]["name"] = "changed"
            with pytest.raises(DraftError) as exc:
                await worker.save_scenario(grant, args, proposal, lambda: None, settings)
            assert exc.value.code == code
            assert not store.path.exists() and not store.receipt_path.exists()
            assert not store.pending_path.exists() and not store.coordinator.blocked
            assert draft.path.read_bytes() == before
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
