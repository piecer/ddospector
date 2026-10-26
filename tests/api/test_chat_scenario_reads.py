"""Bounded native projections and effect-free quarantine observation."""

import asyncio

import pytest
from chat_scenario_support import prepare, reference, setup, worker_for

from aiddos.api.errors import DraftError
from aiddos.api.scenarios import ScenarioInput, canonical


def test_context_one_read_then_history_without_current_draft(tmp_path):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    worker = worker_for(draft, store)
    assert callable(getattr(worker, "read_scenario_configuration", None)), (
        "bounded scenario reads missing"
    )

    async def exercise():
        try:
            grant, _, _, _ = await prepare(worker, draft, store, value, base=reference(first))
            context = await worker.read_scenario_configuration(grant, {"kind": "scenario_context"})
            assert set(context) == {
                "kind",
                "scenario_revision",
                "draft_revision",
                "operation",
                "resolved_inputs",
                "inputs_digest",
                "target_snapshot",
                "sink_snapshot",
                "profiles",
                "base",
            }
            assert context["base"] == first
            assert [p["id"] for p in context["profiles"]] == ["tcpreplay-policy", "k6-http"]
            assert context["resolved_inputs"] == grant["resolved_inputs"]
            assert len(canonical(context)) <= 32768
            draft.path.write_bytes(b"corrupt current draft")
            detail = await worker.read_scenario_configuration(
                grant, {"kind": "scenario", **reference(first)}
            )
            assert detail == {"kind": "scenario", "scenario_revision": 1, "scenario": first}
            for offset in (0, 99, 100):
                page = await worker.read_scenario_configuration(
                    grant, {"kind": "scenarios", "offset": offset, "limit": 10}
                )
                summary = {k: first[k] for k in ("id", "version", "digest")}
                summary.update(
                    {
                        k: first["definition"][k]
                        for k in ("name", "profile_id", "target_id", "sink_id")
                    }
                )
                assert page == {
                    "kind": "scenarios",
                    "scenario_revision": 1,
                    "total": 1,
                    "offset": offset,
                    "limit": 10,
                    "items": [summary] if offset == 0 else [],
                    "next_offset": None,
                }
            assert await worker.scenario_state() == {
                "schema_version": 4,
                "scenario_revision": 1,
                "registry_write_status": "available",
            }
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["blocked", "io", "corrupt"])
def test_state_distinguishes_quarantine_from_unreadable(tmp_path, monkeypatch, failure):
    from aiddos.api import scenario_persistence as persistence

    draft, store, value = setup(tmp_path)
    store.save(ScenarioInput(revision=0, definition=value))
    worker = worker_for(draft, store)
    assert callable(getattr(worker, "scenario_state", None)), "state observation missing"
    if failure == "blocked":
        store.coordinator.blocked = True
    elif failure == "corrupt":
        store.path.write_bytes(b"not json")
    else:
        real = persistence.read_bytes

        def fail(path, *args, **kwargs):
            if path == store.receipt_path:
                raise OSError("receipt read")
            return real(path, *args, **kwargs)

        monkeypatch.setattr(persistence, "read_bytes", fail)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}

    async def exercise():
        try:
            if failure == "blocked":
                assert await worker.scenario_state() == {
                    "schema_version": 4,
                    "scenario_revision": 1,
                    "registry_write_status": "quarantined",
                }
                grant = {
                    "operation": "scenario_create",
                    "expected_scenario_revision": 1,
                    "expected_draft_revision": draft._read().audit_total,
                    "base": None,
                    "input_source": {"source": "operator", "inputs": {}},
                }
                with pytest.raises(DraftError) as exc:
                    await worker.resolve_scenario_intent(grant, draft._read().ai_settings.revision)
                assert exc.value.code == "CHAT_SCENARIO_WRITE_FENCED"
            else:
                with pytest.raises(DraftError) as exc:
                    await worker.scenario_state()
                assert exc.value.code == "CHAT_STORAGE_ERROR"
            assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
        finally:
            await worker.shutdown()

    asyncio.run(exercise())


def test_summary_bounds_and_exact_detail_errors(tmp_path):
    draft, store, value = setup(tmp_path)
    first = store.save(ScenarioInput(revision=0, definition=value))["scenario"]
    second = store.save(ScenarioInput(revision=1, definition=value))["scenario"]
    worker = worker_for(draft, store)

    async def exercise():
        try:
            page = await worker.read_scenario_configuration(
                {}, {"kind": "scenarios", "offset": 0, "limit": 1}
            )
            assert page["total"] == 2 and page["next_offset"] == 1
            assert [r["id"] for r in page["items"]] == [first["id"]]
            page = await worker.read_scenario_configuration(
                {}, {"kind": "scenarios", "offset": 1, "limit": 10}
            )
            assert page["next_offset"] is None and [r["id"] for r in page["items"]] == [
                second["id"]
            ]
            for args, code in [
                ({"kind": "scenarios", "offset": 0, "limit": 11}, "CHAT_INVALID_REQUEST"),
                ({"kind": "scenarios", "offset": False, "limit": 1}, "CHAT_INVALID_REQUEST"),
                (
                    {"kind": "scenario", **reference(first), "digest": "0" * 64},
                    "CHAT_TOOL_CONFLICT",
                ),
                ({"kind": "scenario", **reference(first), "version": 2}, "CHAT_NOT_FOUND"),
                ({"kind": "scenario", **reference(first), "id": "missing"}, "CHAT_NOT_FOUND"),
                ({"kind": "scenario", **reference(first), "version": 1.0}, "CHAT_INVALID_REQUEST"),
            ]:
                with pytest.raises(DraftError) as exc:
                    await worker.read_scenario_configuration({}, args)
                assert exc.value.code == code
        finally:
            await worker.shutdown()

    asyncio.run(exercise())
