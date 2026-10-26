"""Pure v4 contract tests; no routes, stores or runtime admission."""

import importlib
import importlib.util

import pytest


def module():
    name = "aiddos.api.chat_scenario_models"
    assert importlib.util.find_spec(name) is not None, "Missing standalone v4 contract models"
    return importlib.import_module(name)


def definition():
    return dict(
        name="Literal 계획 😀",
        objective="Observe only",
        profile_id="k6-http",
        protocol="HTTP",
        ip_version=4,
        expected_action="ALLOW",
        delivery_expectation="ALLOW",
        detection_required=False,
        success_criteria=dict(
            minimum_delivery_pct=99, maximum_delivery_pct=100, detection_deadline_ms=None
        ),
        evidence_requirements=["service_probe"],
    )


def protected():
    return dict(
        target_id="dut",
        sink_id="sink",
        dut_version="declared",
        policy_version="policy",
        pcap_asset=None,
        traffic_budget=dict(
            max_pps=1, max_bps=2, max_packets=3, max_bytes=4, max_connections=5, duration_seconds=6
        ),
        stop_conditions=dict(
            max_legitimate_loss_pct=0,
            max_service_latency_ms=1,
            max_cpu_pct=None,
            max_memory_pct=None,
            max_sessions=None,
            management_loss=True,
        ),
    )


def test_native_write_model_has_only_model_owned_fields():
    m = module()
    value = dict(expected_scenario_revision=0, expected_draft_revision=0, definition=definition())
    assert m.CreateArgs.model_validate(value).model_dump() == value
    assert set(m.ModelDefinition.model_fields).isdisjoint(protected())
    assert set(m.CreateArgs.model_fields) == set(value)


STAMP = "2026-01-01T00:00:00Z"
EXPIRY = "2026-01-01T00:05:00Z"
IDS = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 9)]


def grant_input():
    return dict(
        schema_version=4,
        scope="scenario_write",
        request_id=IDS[0],
        session_id=IDS[1],
        turn_request_id=IDS[2],
        expected_sequence=0,
        text="Save definition",
        intent=dict(
            operation="scenario_create",
            expected_scenario_revision=0,
            expected_draft_revision=0,
            base=None,
            input_source=dict(source="operator", inputs=protected()),
        ),
    )


def grant():
    import hashlib

    from aiddos.api.scenarios import canonical

    request = grant_input()
    return dict(
        schema_version=4,
        scope="scenario_write",
        id=IDS[3],
        **{
            k: request[k]
            for k in ("request_id", "session_id", "turn_request_id", "expected_sequence", "intent")
        },
        text_sha256=hashlib.sha256(request["text"].encode()).hexdigest(),
        settings_revision=0,
        profile_id="local",
        created_at=STAMP,
        expires_at=EXPIRY,
        status="pending",
        read_scope=["scenario_context", "scenarios", "scenario"],
        proposal_tools=["scenario_create"],
        resolved_inputs=protected(),
        inputs_digest=hashlib.sha256(
            canonical(
                dict(input_source=request["intent"]["input_source"], resolved_inputs=protected())
            )
        ).hexdigest(),
    )


def test_grant_commitment_and_explicit_provenance():
    from copy import deepcopy

    m = module()
    g = grant()
    assert m.GrantV4.model_validate(g).model_dump() == g
    for path, value in [
        (("intent", "base"), dict(id="old", version=1, digest="a" * 64)),
        (("intent", "operation"), "scenario_append"),
        (("resolved_inputs", "dut_version"), "forged"),
        (("inputs_digest",), "b" * 64),
        (("read_scope",), ["scenario"]),
        (("proposal_tools",), ["scenario_append"]),
        (("expires_at",), "2026-01-01T00:04:59Z"),
    ]:
        bad = deepcopy(g)
        obj = bad
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
        with pytest.raises(ValueError):
            m.GrantV4.model_validate(bad)
    assert (
        m.bound_grant(
            g, grant_input(), settings_revision=0, profile_id="local", resolved_inputs=protected()
        )
        == g
    )
    changed = grant_input()
    changed["intent"]["input_source"]["inputs"]["traffic_budget"]["max_pps"] = 2
    with pytest.raises(ValueError):
        m.bound_grant(
            g, changed, settings_revision=0, profile_id="local", resolved_inputs=protected()
        )


EXPECTED_FIELDS = {
    "TrafficBudget": [
        "max_pps",
        "max_bps",
        "max_packets",
        "max_bytes",
        "max_connections",
        "duration_seconds",
    ],
    "StopConditions": [
        "max_legitimate_loss_pct",
        "max_service_latency_ms",
        "max_cpu_pct",
        "max_memory_pct",
        "max_sessions",
        "management_loss",
    ],
    "PcapAsset": ["label", "sha256", "size_bytes"],
    "SuccessCriteria": ["minimum_delivery_pct", "maximum_delivery_pct", "detection_deadline_ms"],
    "ProtectedInputs": [
        "target_id",
        "sink_id",
        "dut_version",
        "policy_version",
        "pcap_asset",
        "traffic_budget",
        "stop_conditions",
    ],
    "ModelDefinition": [
        "name",
        "objective",
        "profile_id",
        "protocol",
        "ip_version",
        "expected_action",
        "delivery_expectation",
        "detection_required",
        "success_criteria",
        "evidence_requirements",
    ],
    "ScenarioDefinition": [
        "name",
        "objective",
        "profile_id",
        "protocol",
        "ip_version",
        "expected_action",
        "delivery_expectation",
        "detection_required",
        "success_criteria",
        "evidence_requirements",
        "target_id",
        "sink_id",
        "dut_version",
        "policy_version",
        "pcap_asset",
        "traffic_budget",
        "stop_conditions",
    ],
    "TargetSnapshot": ["id", "name", "address", "kind", "status", "created_at"],
    "ScenarioVersion": [
        "id",
        "version",
        "created_at",
        "status",
        "execution_enabled",
        "definition",
        "target_snapshot",
        "sink_snapshot",
        "profile_snapshot",
        "catalog_version",
        "digest",
    ],
    "ScenarioRef": ["id", "version", "digest"],
    "OperatorSource": ["source", "inputs"],
    "VersionSource": ["source", "reference"],
    "Intent": [
        "operation",
        "expected_scenario_revision",
        "expected_draft_revision",
        "base",
        "input_source",
    ],
    "GrantInputV4": [
        "schema_version",
        "scope",
        "request_id",
        "session_id",
        "turn_request_id",
        "expected_sequence",
        "text",
        "intent",
    ],
    "GrantV4": [
        "schema_version",
        "id",
        "request_id",
        "session_id",
        "turn_request_id",
        "expected_sequence",
        "text_sha256",
        "settings_revision",
        "profile_id",
        "created_at",
        "expires_at",
        "status",
        "scope",
        "read_scope",
        "proposal_tools",
        "intent",
        "resolved_inputs",
        "inputs_digest",
    ],
    "RuntimeV4": [
        "schema_version",
        "mode",
        "supported",
        "reason",
        "tools",
        "max_calls",
        "max_writes",
        "requires_write_approval",
    ],
    "ContextArgs": ["kind"],
    "ListArgs": ["kind", "offset", "limit"],
    "DetailArgs": ["kind", "id", "version", "digest"],
    "CreateArgs": ["expected_scenario_revision", "expected_draft_revision", "definition"],
    "AppendArgs": ["expected_scenario_revision", "expected_draft_revision", "definition", "base"],
    "Snapshots": ["target_snapshot", "sink_snapshot", "profile_snapshot", "catalog_version"],
    "ContextResult": [
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
    ],
    "ScenarioSummary": ["id", "version", "digest", "name", "profile_id", "target_id", "sink_id"],
    "ListResult": ["kind", "scenario_revision", "total", "offset", "limit", "items", "next_offset"],
    "DetailResult": ["kind", "scenario_revision", "scenario"],
    "ProposalV4": [
        "schema_version",
        "operation",
        "digest",
        "expected_scenario_revision",
        "expected_draft_revision",
        "before",
        "after",
        "snapshots",
        "input_source",
        "inputs_digest",
        "expires_at",
    ],
    "CreatedResult": [
        "kind",
        "before_scenario_revision",
        "after_scenario_revision",
        "source_draft_revision",
        "scenario",
        "execution_enabled",
    ],
    "AppendedResult": [
        "kind",
        "before_scenario_revision",
        "after_scenario_revision",
        "source_draft_revision",
        "scenario",
        "execution_enabled",
    ],
    "DecisionInput": ["request_id", "proposal_digest", "decision"],
    "Decision": [
        "request_id",
        "proposal_digest",
        "decision",
        "schema_version",
        "call_id",
        "accepted_at",
    ],
    "CallV4": [
        "id",
        "index",
        "provider_call_id",
        "tool",
        "arguments",
        "args_digest",
        "grant_id",
        "actor",
        "status",
        "error_code",
        "proposal",
        "decision",
        "result",
        "started_at",
        "finished_at",
    ],
    "TranscriptV4": ["schema_version", "turn_id", "revision", "calls"],
    "ScenarioStateInspection": ["schema_version", "scenario_revision", "registry_write_status"],
    "ReconcileInputV4": [
        "schema_version",
        "request_id",
        "expected_generation",
        "expected_draft_revision",
        "expected_scenario_revision",
        "acknowledge_uncertain",
    ],
    "ReconcileReceiptV4": [
        "schema_version",
        "request_id",
        "acknowledged_call_ids",
        "generation",
        "write_fenced",
        "prior_outcomes",
        "observed_scenario_revision",
        "scenario_recovery",
    ],
    "ToolEnvelopeV4": ["ok", "result", "error_code"],
    "ScenarioExpectation": ["scenario", "after_scenario_revision"],
    "ScenarioSelection": ["id", "version", "expectation"],
    "ScenarioHistoryV4": ["revision", "scenario_id", "versions", "execution_enabled"],
    "ScenarioPageV4": ["revision", "total", "offset", "limit", "items", "execution_enabled"],
}


def test_history_page_and_native_read_semantics():
    from copy import deepcopy

    from tests.chat.scenario_model_wire import history, page, record

    m = module()
    assert m.ScenarioHistoryV4.model_validate(history()).model_dump() == history()
    assert m.ScenarioPageV4.model_validate(page()).model_dump() == page()
    bad = history()
    bad["versions"].reverse()
    with pytest.raises(ValueError):
        m.ScenarioHistoryV4.model_validate(bad)
    for key, value in [("revision", 1), ("total", 2), ("offset", 1)]:
        bad = deepcopy(page())
        bad[key] = value
        with pytest.raises(ValueError):
            m.ScenarioPageV4.model_validate(bad)
    summary = {k: record()[k] for k in ("id", "version", "digest")}
    summary.update(
        {k: record()["definition"][k] for k in ("name", "profile_id", "target_id", "sink_id")}
    )
    value = dict(
        kind="scenarios",
        scenario_revision=1,
        total=1,
        offset=0,
        limit=10,
        items=[summary],
        next_offset=None,
    )
    assert m.ListResult.model_validate(value).model_dump() == value
    value["next_offset"] = 1
    with pytest.raises(ValueError):
        m.ListResult.model_validate(value)
    with pytest.raises(ValueError):
        m.DetailResult.model_validate(
            dict(kind="scenario", scenario_revision=1, scenario=record(version=2))
        )


def test_proposal_binds_disjoint_merge_snapshots_and_provenance():
    from copy import deepcopy

    from tests.chat.scenario_model_wire import proposal

    m = module()
    p = proposal()
    assert m.ProposalV4.model_validate(p).model_dump() == p
    for path, value in [
        (("snapshots", "target_snapshot", "id"), "foreign"),
        (("input_source", "inputs", "dut_version"), "forged"),
        (("inputs_digest",), "f" * 64),
        (("operation",), "scenario_append"),
    ]:
        bad = deepcopy(p)
        obj = bad
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
        with pytest.raises(ValueError):
            m.ProposalV4.model_validate(bad)
    assert m.merge_definition(definition(), protected()) == p["after"]


@pytest.mark.parametrize("operation", ["scenario_create", "scenario_append"])
def test_call_graph_checks_inverse_receipts_state_and_binding(operation):
    from copy import deepcopy

    from tests.chat.scenario_model_wire import call

    m = module()
    c = call(operation)
    assert m.CallV4.model_validate(c).model_dump() == c
    changes = [
        (("args_digest",), "a" * 64),
        (("proposal", "digest"), "b" * 64),
        (("proposal", "expected_draft_revision"), 1),
        (("proposal", "after", "name"), "different"),
        (("decision", "call_id"), IDS[0]),
        (("decision", "proposal_digest"), "c" * 64),
        (("decision", "decision"), "deny"),
        (("decision", "accepted_at"), "2026-01-01T00:02:00Z"),
        (("result", "before_scenario_revision"), 8),
        (("result", "after_scenario_revision"), 9),
        (("result", "source_draft_revision"), 1),
        (("status",), "requested"),
        (("status",), "uncertain"),
        (("error_code",), "CHAT_TIMEOUT"),
        (("finished_at",), None),
        (("finished_at",), "2025-12-31T23:59:59Z"),
        (("proposal",), None),
        (("decision",), None),
    ]
    for path, value in changes:
        bad = deepcopy(c)
        obj = bad
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
        with pytest.raises(ValueError):
            m.CallV4.model_validate(bad)
    if operation == "scenario_create":
        assert m.validate_call_binding(c, grant(), deadline_at="2026-01-01T00:02:00Z") == c
        forged = deepcopy(c)
        forged["proposal"]["input_source"] = dict(
            source="scenario_version", reference=dict(id="old", version=1, digest="a" * 64)
        )
        p = forged["proposal"]
        p["inputs_digest"] = m.inputs_digest(p["input_source"], protected())
        p["digest"] = m.proposal_digest(forged["id"], forged["grant_id"], p)
        forged["decision"]["proposal_digest"] = p["digest"]
        assert m.CallV4.model_validate(forged)  # historical consistency, NOT grant authority
        with pytest.raises(ValueError):
            m.validate_call_binding(forged, grant(), deadline_at="2026-01-01T00:02:00Z")


def test_transcript_counts_attempts_not_only_proposals():
    from copy import deepcopy

    from tests.chat.scenario_model_wire import call

    m = module()
    c = call()
    c.update(
        status="failed",
        error_code="CHAT_INVALID_REQUEST",
        proposal=None,
        decision=None,
        result=None,
    )
    other = deepcopy(c)
    other.update(id=IDS[7], index=1, provider_call_id="second")
    value = dict(schema_version=4, turn_id=IDS[2], revision=2, calls=[c, other])
    with pytest.raises(ValueError):
        m.TranscriptV4.model_validate(value)


def test_context_runtime_envelope_and_selection_invariants():
    from copy import deepcopy

    from aiddos.api.catalog import PROFILES_V1
    from tests.chat.scenario_model_wire import record, snapshots

    m = module()
    context = dict(
        kind="scenario_context",
        scenario_revision=0,
        draft_revision=0,
        operation="scenario_create",
        resolved_inputs=protected(),
        inputs_digest=grant()["inputs_digest"],
        **{k: v for k, v in snapshots().items() if k in ("target_snapshot", "sink_snapshot")},
        profiles=[
            next(p for p in PROFILES_V1 if p["id"] == id) for id in ("tcpreplay-policy", "k6-http")
        ],
        base=None,
    )
    assert m.ContextResult.model_validate(context)
    bad = deepcopy(context)
    bad["profiles"].reverse()
    with pytest.raises(ValueError):
        m.ContextResult.model_validate(bad)
    bad = deepcopy(context)
    bad["target_snapshot"]["kind"] = "SINK"
    with pytest.raises(ValueError):
        m.ContextResult.model_validate(bad)
    runtime = dict(
        schema_version=4,
        mode="operator_approved_settings",
        supported=True,
        reason=None,
        tools=[
            "configuration_read",
            "agent_profile_update",
            "target_create",
            "skill_create",
            "scenario_create",
            "scenario_append",
        ],
        max_calls=3,
        max_writes=1,
        requires_write_approval=True,
    )
    assert m.RuntimeV4.model_validate(runtime)
    for key, value in [("tools", ["scenario_create"]), ("reason", "CHAT_NOT_CONFIGURED")]:
        with pytest.raises(ValueError):
            m.RuntimeV4.model_validate({**runtime, key: value})
    with pytest.raises(ValueError):
        m.ToolEnvelopeV4.model_validate(dict(ok=True, result=None, error_code=None))
    with pytest.raises(ValueError):
        m.ScenarioSelection.model_validate(
            dict(
                id="foreign",
                version=1,
                expectation=dict(scenario=record(), after_scenario_revision=1),
            )
        )
    with pytest.raises(ValueError):
        m.ProfileSnapshot.model_validate({**snapshots()["profile_snapshot"], "layer": "L2–L4"})


def test_pure_version_resolution_requires_the_exact_complete_record():
    from tests.chat.scenario_model_wire import record

    m = module()
    assert hasattr(m, "resolve_inputs"), "Missing pure exact-version projection helper"
    stored = record()
    source = dict(source="scenario_version", reference=m.scenario_ref(stored))
    assert m.resolve_inputs(source, source_record=stored) == protected()
    assert m.resolve_inputs(dict(source="operator", inputs=protected())) == protected()
    with pytest.raises(ValueError):
        m.resolve_inputs(source)
    with pytest.raises(ValueError):
        m.resolve_inputs(source, source_record=record(version=2))
    old_source_intent = dict(
        operation="scenario_append",
        expected_scenario_revision=2,
        expected_draft_revision=0,
        base=m.scenario_ref(record(version=2)),
        input_source=source,
    )
    assert m.Intent.model_validate(old_source_intent).model_dump() == old_source_intent


def test_model_producer_covers_every_shape_and_closed_variant():
    from tests.chat.scenario_model_wire import model_bytes, negative_bytes, variants

    m = module()
    values = model_bytes()
    assert set(values) == set(m.CONTRACT_TYPES)
    for name, raw in values.items():
        assert m.parse_value(name, raw) is not None
    for entry in variants():
        assert m.parse_value(entry["name"], entry["raw"])
    for entry in negative_bytes():
        with pytest.raises(ValueError):
            m.parse_value(entry["name"], entry["raw"])


def test_complete_closed_shape_inventory():
    m = module()
    missing = set(EXPECTED_FIELDS) - set(vars(m))
    assert not missing, f"Missing frozen v4 shapes: {sorted(missing)}"
    for name, fields in EXPECTED_FIELDS.items():
        model = getattr(m, name)
        assert set(model.model_fields) == set(fields), name
        assert all(field.is_required() for field in model.model_fields.values()), name
        assert model.model_config["extra"] == "forbid", name
    for name in ("ReadArgs", "InputSource", "ResultV4"):
        assert hasattr(m, name)


def test_allows_call_rejects_wrong_scope_after_ordinary_model_copy():
    from tests.chat.scenario_model_wire import call

    m = module()
    original = m.GrantV4.model_validate(grant())
    wrong = original.model_copy(update={"scope": "skill_create", "schema_version": 3})
    assert not m.allows_call(wrong.model_dump(), "scenario_create", call()["arguments"])
    assert m.allows_call(wrong, "scenario_create", call()["arguments"]) is False


def test_bound_grant_rejects_boolean_counter_in_reused_model():
    m = module()
    value = m.GrantV4.model_validate(grant())
    value.expected_sequence = False
    for candidate in (value.model_dump(), value):
        with pytest.raises(ValueError):
            m.bound_grant(
                candidate, grant_input(), settings_revision=0,
                profile_id="local", resolved_inputs=protected(),
            )


def test_bound_call_rejects_invalid_provider_identity_in_reused_model():
    from tests.chat.scenario_model_wire import call

    m = module()
    value = m.CallV4.model_validate(call())
    value.provider_call_id = "non-ascii-한"
    for candidate in (value.model_dump(), value):
        with pytest.raises(ValueError):
            m.validate_call_binding(candidate, grant(), deadline_at="2026-01-01T00:02:00Z")


@pytest.mark.parametrize("name", EXPECTED_FIELDS)
def test_model_revalidation_closed_copies_and_detached_positive_controls(name):
    from pydantic import TypeAdapter

    from tests.chat.scenario_model_wire import examples

    m = module()
    model = getattr(m, name)
    original = examples()[name]
    instance = model.model_validate(original)
    routes = (model.model_validate, TypeAdapter(model).validate_python,
              lambda v: m.validate_value(name, v))
    for route in routes:
        result = route(instance)
        assert (result.model_dump() if hasattr(result, "model_dump") else result) == original
        assert result is not instance
        for key in ("unexpected", "_unexpected", "target_id_protected"):
            copied = instance.model_copy(update={key: 1})
            # The ordinary copy retains unknown fields that serialization drops.
            assert key in vars(copied)
            with pytest.raises(ValueError):
                route(copied)
            with pytest.raises(ValueError):
                route({**original, key: 1})


@pytest.mark.parametrize("route", ["named", "adapter", "class", "constructor"])
@pytest.mark.parametrize("mutation", ["provider", "nested_extra", "nested_bool", "nested_legacy"])
def test_model_revalidation_nested_transcript_copies(route, mutation):
    from pydantic import TypeAdapter

    from tests.chat.scenario_model_wire import call

    m = module()
    member = m.CallV4.model_validate(call())
    if mutation == "provider":
        member.provider_call_id = "non-ascii-한"
    elif mutation == "nested_extra":
        member.arguments.definition = member.arguments.definition.model_copy(
            update={"target_id": "dut"}
        )
    elif mutation == "nested_bool":
        member.decision = member.decision.model_copy(update={"schema_version": True})
    else:
        # ScenarioVersion inherits legacy nested models, not just v4 subclasses.
        member.result.scenario.definition.traffic_budget = (
            member.result.scenario.definition.traffic_budget.model_copy(update={"hidden": 0})
        )
    value = dict(schema_version=4, turn_id=IDS[2], revision=1, calls=[member])
    invoke = {
        "named": lambda v: m.validate_value("TranscriptV4", v),
        "adapter": TypeAdapter(m.TranscriptV4).validate_python,
        "class": m.TranscriptV4.model_validate,
        "constructor": lambda v: m.TranscriptV4(**v),
    }[route]
    with pytest.raises(ValueError):
        invoke(value)


@pytest.mark.parametrize("route", [
    "native_schemas", "allows_arguments", "bound_request", "bound_inputs",
    "bound_call_grant", "resolve_operator", "resolve_version", "merge_model", "merge_inputs",
])
def test_model_revalidation_sibling_helpers(route):
    from functools import partial

    from tests.chat.scenario_model_wire import call, record

    m = module()
    g = m.GrantV4.model_validate(grant())
    request = m.GrantInputV4.model_validate(grant_input())
    inputs = m.ProtectedInputs.model_validate(protected())
    proposed = m.ModelDefinition.model_validate(definition())
    if route == "native_schemas":
        g.scope = "skill_create"
        invoke = partial(m.native_schemas, g)
    elif route == "allows_arguments":
        args = m.CreateArgs.model_validate(call()["arguments"])
        args.expected_draft_revision = False
        assert not m.allows_call(g, "scenario_create", args)
        return
    elif route == "bound_request":
        request.expected_sequence = False
        invoke = partial(
            m.bound_grant,
            g, request, settings_revision=0, profile_id="local", resolved_inputs=inputs
        )
    elif route == "bound_inputs":
        inputs.stop_conditions.management_loss = 1
        invoke = partial(
            m.bound_grant,
            g, request, settings_revision=0, profile_id="local", resolved_inputs=inputs
        )
    elif route == "bound_call_grant":
        g.expected_sequence = False
        invoke = partial(m.validate_call_binding, call(), g, deadline_at="2026-01-01T00:02:00Z")
    elif route == "resolve_operator":
        source = m.OperatorSource(source="operator", inputs=inputs)
        source.inputs.stop_conditions.management_loss = 1
        invoke = partial(m.resolve_inputs, source)
    elif route == "resolve_version":
        stored = m.ScenarioVersion.model_validate(record())
        source = m.VersionSource(source="scenario_version", reference=m.scenario_ref(record()))
        stored = stored.model_copy(update={"unexpected": 1})
        invoke = partial(m.resolve_inputs, source, source_record=stored)
    elif route == "merge_model":
        proposed.detection_required = 0
        invoke = partial(m.merge_definition, proposed, inputs)
    else:
        inputs.stop_conditions.management_loss = 1
        invoke = partial(m.merge_definition, proposed, inputs)
    with pytest.raises(ValueError):
        invoke()


def test_model_revalidation_helpers_keep_valid_instances_and_break_aliases():
    from tests.chat.scenario_model_wire import call, record

    m = module()
    g = m.GrantV4.model_validate(grant())
    request = m.GrantInputV4.model_validate(grant_input())
    inputs = m.ProtectedInputs.model_validate(protected())
    g.intent.input_source.inputs = inputs
    g.resolved_inputs = inputs
    bound = m.bound_grant(
        g, request, settings_revision=0, profile_id="local", resolved_inputs=inputs
    )
    assert bound == grant()
    assert m.native_schemas(g) == m.native_schemas(grant())
    c = m.CallV4.model_validate(call())
    assert m.validate_call_binding(c, g, deadline_at="2026-01-01T00:02:00Z") == call()
    assert m.allows_call(g, "scenario_create", c.arguments)
    proposed = m.ModelDefinition.model_validate(definition())
    assert m.merge_definition(proposed, inputs) == {**definition(), **protected()}
    source = m.OperatorSource(source="operator", inputs=inputs)
    resolved = m.resolve_inputs(source)
    stored = m.ScenarioVersion.model_validate(record())
    version = m.VersionSource(source="scenario_version", reference=m.scenario_ref(record()))
    assert m.resolve_inputs(version, source_record=stored) == protected()
    snapshot = m.GrantV4.model_validate(g)
    inputs.traffic_budget.max_pps = 10
    assert bound == grant() and resolved == protected()
    assert snapshot.model_dump() == grant()
    snapshot.resolved_inputs.traffic_budget.max_pps = 20
    assert snapshot.intent.input_source.inputs.traffic_budget.max_pps == 1
    assert inputs.traffic_budget.max_pps == 10
