"""Trusted internal dict fixtures, not v4 wire/ledger authority."""

from copy import deepcopy

from scenario_producer import definition

from aiddos.api.chat_tool_domain import DomainWorker
from aiddos.api.models import TargetInput
from aiddos.api.scenario_store import ScenarioStore
from aiddos.api.store import DraftStore

PROTECTED = {
    "target_id",
    "sink_id",
    "dut_version",
    "policy_version",
    "pcap_asset",
    "traffic_budget",
    "stop_conditions",
}


def setup(tmp_path):
    draft = DraftStore(tmp_path / "draft.json")
    targets = [
        draft.create_target(TargetInput(name=k, address="192.0.2.1", kind=k)).model_dump()
        for k in ("DUT", "SINK")
    ]
    store = ScenarioStore(draft)
    value = definition(targets)
    return draft, store, value


def intent_for(draft, store, value, *, base=None, source=None):
    return {
        "operation": "scenario_create" if base is None else "scenario_append",
        "expected_scenario_revision": store.page()["revision"],
        "expected_draft_revision": draft._read().audit_total,
        "base": deepcopy(base),
        "input_source": source
        or {
            "source": "operator",
            "inputs": {k: deepcopy(v) for k, v in value.items() if k in PROTECTED},
        },
    }


async def prepare(worker, draft, store, value, *, base=None, source=None):
    intent = intent_for(draft, store, value, base=base, source=source)
    settings = draft._read().ai_settings.revision
    resolved = await worker.resolve_scenario_intent(intent, settings)
    grant = {"intent": intent, **resolved, "settings_revision": settings}
    arguments = {k: intent[k] for k in ("expected_scenario_revision", "expected_draft_revision")}
    arguments["definition"] = {k: deepcopy(v) for k, v in value.items() if k not in PROTECTED}
    if base is not None:
        arguments["base"] = deepcopy(base)
    proposal = await worker.prepare_scenario(grant, arguments, settings)
    return grant, arguments, proposal, settings


def reference(record):
    return {k: record[k] for k in ("id", "version", "digest")}


def worker_for(draft, store):
    assert callable(getattr(DomainWorker, "save_scenario", None)), "real scenario worker is missing"
    return DomainWorker(draft, store)
