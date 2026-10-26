"""Closed standalone B3 v4 models; no runtime, ledger or route activation.

Shapes follow contract revision 2. Semantic validation is deliberately separate
from external authority/source resolution: a consistent record is not a grant.
"""

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, TypeAdapter, model_validator

from . import scenarios as legacy
from .chat_models import ChatID, user_text
from .encoding import strict_json
from .models import ClosedModel, Timestamp
from .scenarios import canonical, exact_bool, exact_int
from .validation import Goal, Identifier, Name

Digest = legacy.Digest
UserText = Annotated[str, AfterValidator(user_text)]


def chat_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC required")
    return value


ChatTime = Annotated[
    str,
    AfterValidator(chat_time),
    Field(
        max_length=40,
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)$",
    ),
]


def json_value(value, depth=0):
    """Snapshot exact JSON data, retaining model-copy extras for closed validation."""
    if isinstance(value, BaseModel):
        # Serialization can omit unknown model_copy(update=...) fields and does
        # not validate reused instances. Preserve their actual data instead,
        # including nested legacy models, without changing legacy configuration.
        value = {**vars(value), **(value.model_extra or {})}
    if type(value) in (dict, list):
        if depth >= 32:
            raise ValueError("JSON nesting limit exceeded")
        if type(value) is dict:
            snapshot = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError("String keys required")
                key.encode("utf-8", errors="strict")
                snapshot[key] = json_value(item, depth + 1)
            return snapshot
        else:
            return [json_value(item, depth + 1) for item in value]
    elif type(value) is str:
        value.encode("utf-8", errors="strict")
    elif type(value) is int:
        if abs(value) > 9007199254740991:
            raise ValueError("Unsafe integer")
    elif value is not None and type(value) is not bool:
        raise ValueError("Only exact JSON integers are supported")
    return value


class ScenarioModel(ClosedModel):
    @classmethod
    def model_validate_json(cls, json_data, **kwargs):
        # Pydantic's JSON entrypoint otherwise discards duplicate-key evidence.
        return cls.model_validate(decode_raw(cls.__name__, json_data), **kwargs)

    @model_validator(mode="wrap")
    @classmethod
    def exact_json(cls, value, handler):
        # Wrap the model node: a before-validator inside it is skipped when
        # Pydantic accepts an existing instance without field revalidation.
        return handler(json_value(value))

    @model_validator(mode="after")
    def semantic(self):
        semantic(type(self).__name__, self.model_dump())
        return self


class TrafficBudget(ScenarioModel, legacy.TrafficBudget):
    pass


class StopConditions(ScenarioModel, legacy.StopConditions):
    pass


class PcapAsset(ScenarioModel, legacy.PcapAsset):
    pass


class SuccessCriteria(ScenarioModel, legacy.SuccessCriteria):
    pass


class ProtectedInputs(ScenarioModel):
    target_id: Identifier
    sink_id: Identifier
    dut_version: Name
    policy_version: Name
    pcap_asset: PcapAsset | None
    traffic_budget: TrafficBudget
    stop_conditions: StopConditions


class ModelDefinition(ScenarioModel):
    name: Name
    objective: Goal
    profile_id: Literal["tcpreplay-policy", "k6-http"]
    protocol: Literal["TCP", "UDP", "DNS", "HTTP"]
    ip_version: Annotated[Literal[4, 6], BeforeValidator(exact_int)]
    expected_action: Literal["ALLOW", "BLOCK", "ALERT"]
    delivery_expectation: Literal["ALLOW", "BLOCK"]
    detection_required: bool
    success_criteria: SuccessCriteria
    evidence_requirements: Annotated[
        list[
            Literal[
                "ingress_pcap", "egress_pcap", "dut_events", "service_probe", "resource_metrics"
            ]
        ],
        Field(min_length=1, max_length=5, json_schema_extra={"uniqueItems": True}),
    ]


class ScenarioDefinition(ScenarioModel, legacy.ScenarioDefinition):
    pass


class TargetSnapshot(ScenarioModel, legacy.TargetSnapshot):
    pass


class ProfileSnapshot(ScenarioModel, legacy.ProfileSnapshot):
    pass


class ScenarioVersion(ScenarioModel, legacy.ScenarioVersion):
    pass


class ScenarioRef(ScenarioModel):
    id: Identifier
    version: Annotated[int, Field(ge=1, le=10, strict=True)]
    digest: Digest


class OperatorSource(ScenarioModel):
    source: Literal["operator"]
    inputs: ProtectedInputs


class VersionSource(ScenarioModel):
    source: Literal["scenario_version"]
    reference: ScenarioRef


InputSource = OperatorSource | VersionSource


class Intent(ScenarioModel):
    operation: Literal["scenario_create", "scenario_append"]
    expected_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    expected_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    base: ScenarioRef | None
    input_source: InputSource


class GrantInputV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    scope: Literal["scenario_write"]
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    text: UserText
    intent: Intent


class GrantV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    id: ChatID
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    text_sha256: Digest
    settings_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    profile_id: Annotated[str, Field(pattern="^[a-z][a-z0-9_-]{0,63}$")]
    created_at: ChatTime
    expires_at: ChatTime
    status: Literal["pending", "consumed", "revoked", "expired"]
    scope: Literal["scenario_write"]
    read_scope: Annotated[
        list[str], Field(json_schema_extra={"const": ["scenario_context", "scenarios", "scenario"]})
    ]
    proposal_tools: Annotated[
        list[Literal["scenario_create", "scenario_append"]], Field(min_length=1, max_length=1)
    ]
    intent: Intent
    resolved_inputs: ProtectedInputs
    inputs_digest: Digest


class RuntimeV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    mode: Literal["operator_approved_settings"]
    supported: bool
    reason: (
        Literal["CHAT_NOT_CONFIGURED", "CHAT_UNSUPPORTED_PROFILE", "CHAT_UNSUPPORTED_OPTIONS"]
        | None
    )
    tools: Annotated[
        list[str],
        Field(
            json_schema_extra={
                "const": [
                    "configuration_read",
                    "agent_profile_update",
                    "target_create",
                    "skill_create",
                    "scenario_create",
                    "scenario_append",
                ]
            }
        ),
    ]
    max_calls: Annotated[Literal[3], BeforeValidator(exact_int)]
    max_writes: Annotated[Literal[1], BeforeValidator(exact_int)]
    requires_write_approval: Annotated[Literal[True], BeforeValidator(exact_bool)]


class ContextArgs(ScenarioModel):
    kind: Literal["scenario_context"]


class ListArgs(ScenarioModel):
    kind: Literal["scenarios"]
    offset: Annotated[int, Field(ge=0, le=100, strict=True)]
    limit: Annotated[int, Field(ge=1, le=10, strict=True)]


class DetailArgs(ScenarioModel):
    kind: Literal["scenario"]
    id: Identifier
    version: Annotated[int, Field(ge=1, le=10, strict=True)]
    digest: Digest


ReadArgs = ContextArgs | ListArgs | DetailArgs


class CreateArgs(ScenarioModel):
    expected_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    expected_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    definition: ModelDefinition


class AppendArgs(ScenarioModel):
    expected_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    expected_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    definition: ModelDefinition
    base: ScenarioRef


class Snapshots(ScenarioModel):
    target_snapshot: TargetSnapshot
    sink_snapshot: TargetSnapshot
    profile_snapshot: ProfileSnapshot
    catalog_version: Literal["1.0.0"]


class ContextResult(ScenarioModel):
    kind: Literal["scenario_context"]
    scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    operation: Literal["scenario_create", "scenario_append"]
    resolved_inputs: ProtectedInputs
    inputs_digest: Digest
    target_snapshot: TargetSnapshot
    sink_snapshot: TargetSnapshot
    profiles: Annotated[list[ProfileSnapshot], Field(min_length=2, max_length=2)]
    base: ScenarioVersion | None


class ScenarioSummary(ScenarioModel):
    id: Identifier
    version: Annotated[int, Field(ge=1, le=10, strict=True)]
    digest: Digest
    name: Name
    profile_id: Literal["tcpreplay-policy", "k6-http"]
    target_id: Identifier
    sink_id: Identifier


class ListResult(ScenarioModel):
    kind: Literal["scenarios"]
    scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    total: Annotated[int, Field(ge=0, le=100, strict=True)]
    offset: Annotated[int, Field(ge=0, le=100, strict=True)]
    limit: Annotated[int, Field(ge=1, le=10, strict=True)]
    items: Annotated[list[ScenarioSummary], Field(min_length=0, max_length=10)]
    next_offset: Annotated[int, Field(ge=1, le=99, strict=True)] | None


class DetailResult(ScenarioModel):
    kind: Literal["scenario"]
    scenario_revision: Annotated[int, Field(ge=1, le=1000, strict=True)]
    scenario: ScenarioVersion


class ProposalV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    operation: Literal["scenario_create", "scenario_append"]
    digest: Digest
    expected_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    expected_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    before: ScenarioVersion | None
    after: ScenarioDefinition
    snapshots: Snapshots
    input_source: InputSource
    inputs_digest: Digest
    expires_at: ChatTime


class CreatedResult(ScenarioModel):
    kind: Literal["scenario_created"]
    before_scenario_revision: Annotated[int, Field(ge=0, le=999, strict=True)]
    after_scenario_revision: Annotated[int, Field(ge=1, le=1000, strict=True)]
    source_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    scenario: ScenarioVersion
    execution_enabled: Annotated[Literal[False], BeforeValidator(exact_bool)]


class AppendedResult(ScenarioModel):
    kind: Literal["scenario_appended"]
    before_scenario_revision: Annotated[int, Field(ge=0, le=999, strict=True)]
    after_scenario_revision: Annotated[int, Field(ge=1, le=1000, strict=True)]
    source_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    scenario: ScenarioVersion
    execution_enabled: Annotated[Literal[False], BeforeValidator(exact_bool)]


ResultV4 = ContextResult | ListResult | DetailResult | CreatedResult | AppendedResult


class DecisionInput(ScenarioModel):
    request_id: ChatID
    proposal_digest: Digest
    decision: Literal["approve", "deny"]


class Decision(ScenarioModel):
    request_id: ChatID
    proposal_digest: Digest
    decision: Literal["approve", "deny"]
    schema_version: Annotated[Literal[1], BeforeValidator(exact_int)]
    call_id: ChatID
    accepted_at: ChatTime


class CallV4(ScenarioModel):
    id: ChatID
    index: Annotated[int, Field(ge=0, le=2, strict=True)]
    provider_call_id: Annotated[
        str, Field(min_length=1, max_length=128, pattern="^[\\x00-\\x7f]+$")
    ]
    tool: Literal["configuration_read", "scenario_create", "scenario_append"]
    arguments: ContextArgs | ListArgs | DetailArgs | CreateArgs | AppendArgs
    args_digest: Digest
    grant_id: ChatID
    actor: Literal["operator_authorized_model"]
    status: Literal[
        "requested",
        "awaiting_approval",
        "executing",
        "succeeded",
        "denied",
        "conflict",
        "failed",
        "uncertain",
        "cancelled",
    ]
    error_code: (
        Literal[
            "CHAT_TOOL_DENIED",
            "CHAT_TOOL_WRITE_FENCED",
            "CHAT_SCENARIO_WRITE_FENCED",
            "CHAT_TOOL_CONFLICT",
            "CHAT_TIMEOUT",
            "CHAT_INVALID_REQUEST",
            "CHAT_NOT_FOUND",
            "CHAT_TOOL_LIMIT",
            "CHAT_STORAGE_ERROR",
            "CHAT_TOOL_UNCERTAIN",
            "CHAT_CANCELLED",
        ]
        | None
    )
    proposal: ProposalV4 | None
    decision: Decision | None
    result: ResultV4 | None
    started_at: ChatTime
    finished_at: ChatTime | None


class TranscriptV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    turn_id: ChatID
    revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    calls: Annotated[list[CallV4], Field(min_length=0, max_length=3)]


class ScenarioStateInspection(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    registry_write_status: Literal["available", "quarantined"]


class ReconcileInputV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    request_id: ChatID
    expected_generation: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    expected_draft_revision: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    expected_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    acknowledge_uncertain: Annotated[Literal[True], BeforeValidator(exact_bool)]


class ReconcileReceiptV4(ScenarioModel):
    schema_version: Annotated[Literal[4], BeforeValidator(exact_int)]
    request_id: ChatID
    acknowledged_call_ids: Annotated[list[ChatID], Field(min_length=1, max_length=1)]
    generation: Annotated[int, Field(ge=0, le=9007199254740991, strict=True)]
    write_fenced: Annotated[Literal[False], BeforeValidator(exact_bool)]
    prior_outcomes: Literal["remain_uncertain"]
    observed_scenario_revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    scenario_recovery: Literal["not_performed"]


class ToolEnvelopeV4(ScenarioModel):
    ok: bool
    result: ResultV4 | None
    error_code: (
        Literal[
            "CHAT_TOOL_DENIED",
            "CHAT_TOOL_WRITE_FENCED",
            "CHAT_SCENARIO_WRITE_FENCED",
            "CHAT_TOOL_CONFLICT",
            "CHAT_TIMEOUT",
            "CHAT_INVALID_REQUEST",
            "CHAT_NOT_FOUND",
            "CHAT_TOOL_LIMIT",
            "CHAT_STORAGE_ERROR",
            "CHAT_TOOL_UNCERTAIN",
            "CHAT_CANCELLED",
        ]
        | None
    )


class ScenarioExpectation(ScenarioModel):
    scenario: ScenarioVersion
    after_scenario_revision: Annotated[int, Field(ge=1, le=1000, strict=True)]


class ScenarioSelection(ScenarioModel):
    id: Identifier
    version: Annotated[int, Field(ge=1, le=10, strict=True)]
    expectation: ScenarioExpectation | None


class ScenarioHistoryV4(ScenarioModel):
    revision: Annotated[int, Field(ge=1, le=1000, strict=True)]
    scenario_id: Identifier
    versions: Annotated[list[ScenarioVersion], Field(min_length=1, max_length=10)]
    execution_enabled: Annotated[Literal[False], BeforeValidator(exact_bool)]


class ScenarioPageV4(ScenarioModel):
    revision: Annotated[int, Field(ge=0, le=1000, strict=True)]
    total: Annotated[int, Field(ge=0, le=100, strict=True)]
    offset: Annotated[int, Field(ge=0, le=100, strict=True)]
    limit: Annotated[int, Field(ge=1, le=100, strict=True)]
    items: Annotated[list[ScenarioVersion], Field(min_length=0, max_length=100)]
    execution_enabled: Annotated[Literal[False], BeforeValidator(exact_bool)]


def validate_arguments(tool, value):
    model = {
        "configuration_read": ReadArgs,
        "scenario_create": CreateArgs,
        "scenario_append": AppendArgs,
    }.get(tool)
    if model is None:
        raise ValueError("Unknown v4 tool")
    value = json_value(value)
    return TypeAdapter(model).validate_python(value).model_dump()


def native_parameters(model):
    """Export the actual ingress model with all refs local by full expansion."""
    schema = TypeAdapter(model).json_schema()
    definitions = schema.get("$defs", {})

    def inline(node):
        if isinstance(node, list):
            return [inline(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return inline(definitions[node["$ref"].removeprefix("#/$defs/")])
        return {k: inline(v) for k, v in node.items() if k not in {"title", "$defs"}}

    return inline(schema)


def native_schemas(grant):
    g = GrantV4.model_validate(grant)
    branches = [native_parameters(model) for model in (ContextArgs, ListArgs, DetailArgs)]
    properties = {}
    for branch in branches:
        properties.update(branch["properties"])
    properties["kind"] = {"type": "string", "enum": ["scenario_context", "scenarios", "scenario"]}
    read = dict(
        type="object",
        properties=properties,
        required=["kind"],
        additionalProperties=False,
        oneOf=branches,
    )
    operation = g.intent.operation
    write = native_parameters(CreateArgs if operation == "scenario_create" else AppendArgs)
    return [
        dict(type="function", function=dict(name=name, parameters=parameters))
        for name, parameters in (("configuration_read", read), (operation, write))
    ]


def parse_arguments(tool, raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="strict")
    if type(raw) is not bytes or len(raw) > 16384:
        raise ValueError("Argument byte limit")
    return validate_arguments(tool, strict_json(raw))


CONTRACT_TYPES = {
    "Identifier": Identifier,
    "ChatID": ChatID,
    "Digest": Digest,
    "Name": Name,
    "Goal": Goal,
    "Timestamp": Timestamp,
    "ChatTime": ChatTime,
    "UserText": UserText,
    "TrafficBudget": TrafficBudget,
    "StopConditions": StopConditions,
    "PcapAsset": PcapAsset,
    "SuccessCriteria": SuccessCriteria,
    "ProtectedInputs": ProtectedInputs,
    "ModelDefinition": ModelDefinition,
    "ScenarioDefinition": ScenarioDefinition,
    "TargetSnapshot": TargetSnapshot,
    "ProfileSnapshot": ProfileSnapshot,
    "ScenarioVersion": ScenarioVersion,
    "ScenarioRef": ScenarioRef,
    "OperatorSource": OperatorSource,
    "VersionSource": VersionSource,
    "InputSource": InputSource,
    "Intent": Intent,
    "GrantInputV4": GrantInputV4,
    "GrantV4": GrantV4,
    "RuntimeV4": RuntimeV4,
    "ContextArgs": ContextArgs,
    "ListArgs": ListArgs,
    "DetailArgs": DetailArgs,
    "ReadArgs": ReadArgs,
    "CreateArgs": CreateArgs,
    "AppendArgs": AppendArgs,
    "Snapshots": Snapshots,
    "ContextResult": ContextResult,
    "ScenarioSummary": ScenarioSummary,
    "ListResult": ListResult,
    "DetailResult": DetailResult,
    "ProposalV4": ProposalV4,
    "CreatedResult": CreatedResult,
    "AppendedResult": AppendedResult,
    "ResultV4": ResultV4,
    "DecisionInput": DecisionInput,
    "Decision": Decision,
    "CallV4": CallV4,
    "TranscriptV4": TranscriptV4,
    "ScenarioStateInspection": ScenarioStateInspection,
    "ReconcileInputV4": ReconcileInputV4,
    "ReconcileReceiptV4": ReconcileReceiptV4,
    "ToolEnvelopeV4": ToolEnvelopeV4,
    "ScenarioExpectation": ScenarioExpectation,
    "ScenarioSelection": ScenarioSelection,
    "ScenarioHistoryV4": ScenarioHistoryV4,
    "ScenarioPageV4": ScenarioPageV4,
}

RAW_LIMITS = {
    "ScenarioHistoryV4": 262144,
    "ScenarioPageV4": 1048576,
    "CallV4": 262144,
    "TranscriptV4": 1048576,
    "CreateArgs": 16384,
    "AppendArgs": 16384,
    "ReadArgs": 16384,
}


def decode_raw(name, raw):
    if name not in CONTRACT_TYPES:
        raise ValueError("Unknown v4 contract")
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="strict")
    if type(raw) is not bytes or len(raw) > RAW_LIMITS.get(name, 32768):
        raise ValueError("Raw companion byte limit")
    return json_value(strict_json(raw))


def validate_value(name, value):
    if name not in CONTRACT_TYPES:
        raise ValueError("Unknown v4 contract")
    value = json_value(value)
    result = TypeAdapter(CONTRACT_TYPES[name]).validate_python(value)
    result = result.model_dump() if isinstance(result, BaseModel) else result
    if name == "ResultV4":
        require(len(canonical(result)) <= 32768)
    return result


def parse_value(name, raw):
    """Use for untrusted bytes; direct object validation cannot recover tokens."""
    return validate_value(name, decode_raw(name, raw))


def require(condition, message="Inconsistent v4 contract"):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def inputs_digest(input_source, resolved_inputs):
    return digest(dict(input_source=input_source, resolved_inputs=resolved_inputs))


def protected_projection(definition):
    return {k: definition[k] for k in ProtectedInputs.model_fields}


def model_projection(definition):
    return {k: definition[k] for k in ModelDefinition.model_fields}


def resolve_inputs(input_source, *, source_record=None):
    """Validate a caller-resolved immutable source; never performs a lookup.

    Storage owners must supply the actual exact stored version, not a model
    assertion or a latest alias. Missing/wrong records fail without defaults.
    """
    source = validate_value("InputSource", input_source)
    if source["source"] == "operator":
        require(source_record is None)
        return source["inputs"]
    require(source_record is not None)
    record = ScenarioVersion.model_validate(source_record).model_dump()
    require(scenario_ref(record) == source["reference"])
    return protected_projection(record["definition"])


def merge_definition(definition, resolved_inputs):
    proposed = ModelDefinition.model_validate(definition).model_dump()
    protected = ProtectedInputs.model_validate(resolved_inputs).model_dump()
    return ScenarioDefinition.model_validate({**proposed, **protected}).model_dump()


def snapshot_binding(definition, snapshots):
    for field, role, key in (
        ("target_snapshot", "DUT", "target_id"),
        ("sink_snapshot", "SINK", "sink_id"),
    ):
        require(snapshots[field]["id"] == definition[key] and snapshots[field]["kind"] == role)
    require(definition["target_id"] != definition["sink_id"])
    require(
        snapshots["profile_snapshot"]
        == next(p for p in legacy.PROFILES_V1 if p["id"] == definition["profile_id"])
    )


def semantic(name, value):
    """Pure consistency, never a lookup or proof of retained server authority."""
    v = value
    canonical_limits = {
        "GrantV4": 8192,
        "ScenarioVersion": 8192,
        "CallV4": 262144,
        "TranscriptV4": 1048576,
    }
    if name in canonical_limits:
        require(len(canonical(v)) <= canonical_limits[name])
    if name in {
        "ContextResult",
        "ListResult",
        "DetailResult",
        "CreatedResult",
        "AppendedResult",
        "ScenarioExpectation",
        "ScenarioStateInspection",
    }:
        require(len(canonical(v)) <= 32768)
    if name == "ModelDefinition":
        require(len(v["evidence_requirements"]) == len(set(v["evidence_requirements"])))
    elif name == "ProtectedInputs":
        require(v["target_id"] != v["sink_id"])
    elif name == "ProfileSnapshot":
        require(v == next(p for p in legacy.PROFILES_V1 if p["id"] == v["id"]))
    elif name == "ContextResult":
        require([p["id"] for p in v["profiles"]] == ["tcpreplay-policy", "k6-http"])
        require((v["operation"] == "scenario_create") == (v["base"] is None))
        if v["base"] is not None:
            require(v["base"]["version"] <= 9 and v["scenario_revision"] >= v["base"]["version"])
        for field, role, key in (
            ("target_snapshot", "DUT", "target_id"),
            ("sink_snapshot", "SINK", "sink_id"),
        ):
            require(v[field]["id"] == v["resolved_inputs"][key] and v[field]["kind"] == role)
    elif name == "RuntimeV4":
        require(v["supported"] == (v["reason"] is None))
        require(
            v["tools"]
            == [
                "configuration_read",
                "agent_profile_update",
                "target_create",
                "skill_create",
                "scenario_create",
                "scenario_append",
            ]
        )
    elif name == "ToolEnvelopeV4":
        require(
            (v["result"] is not None and v["error_code"] is None)
            if v["ok"]
            else (v["result"] is None and v["error_code"] is not None)
        )
    elif name == "ScenarioExpectation":
        require(v["after_scenario_revision"] >= v["scenario"]["version"])
    elif name == "ScenarioSelection" and v["expectation"] is not None:
        require(all(v[k] == v["expectation"]["scenario"][k] for k in ("id", "version")))
    elif name == "CallV4":
        call_consistency(v)
    elif name == "TranscriptV4":
        calls = v["calls"]
        require([c["index"] for c in calls] == list(range(len(calls))))
        require(len({c["id"] for c in calls}) == len(calls))
        require(len({c["provider_call_id"] for c in calls}) == len(calls))
        require(len({c["grant_id"] for c in calls}) <= 1)
        require(sum(c["tool"] != "configuration_read" for c in calls) <= 1)
        require(len(canonical(v)) <= 1048576)
    elif name in {"CreatedResult", "AppendedResult"}:
        require(v["after_scenario_revision"] == v["before_scenario_revision"] + 1)
        require(v["after_scenario_revision"] >= v["scenario"]["version"])
        if name == "CreatedResult":
            TypeAdapter(ChatID).validate_python(v["scenario"]["id"])
            require(v["scenario"]["version"] == 1)
        else:
            require(v["scenario"]["version"] >= 2)
    elif name == "ProposalV4":
        require((v["operation"] == "scenario_create") == (v["before"] is None))
        if v["before"] is not None:
            require(
                v["before"]["version"] <= 9
                and v["expected_scenario_revision"] >= v["before"]["version"]
            )
        snapshot_binding(v["after"], v["snapshots"])
        projected = protected_projection(v["after"])
        if v["input_source"]["source"] == "operator":
            require(v["input_source"]["inputs"] == projected)
        require(v["inputs_digest"] == inputs_digest(v["input_source"], projected))
    elif name == "ScenarioDefinition":
        require(v["target_id"] != v["sink_id"])
    elif name == "ScenarioHistoryV4":
        require(v["revision"] >= len(v["versions"]))
        require(
            all(
                r["id"] == v["scenario_id"] and r["version"] == i
                for i, r in enumerate(v["versions"], 1)
            )
        )
    elif name in {"ScenarioPageV4", "ListResult"}:
        revision = v["revision"] if name == "ScenarioPageV4" else v["scenario_revision"]
        items, total = v["items"], v["total"]
        require(len(items) == max(0, min(v["limit"], total - v["offset"])))
        require(len({r["id"] for r in items}) == len(items))
        count, outside = sum(r["version"] for r in items), total - len(items)
        require(total <= revision <= total * 10)
        require(count + outside <= revision <= count + outside * 10)
        if name == "ListResult":
            end = v["offset"] + len(items)
            require(v["next_offset"] == (end if end < total else None))
    elif name == "DetailResult":
        require(v["scenario_revision"] >= v["scenario"]["version"])
    elif name == "Intent":
        require((v["operation"] == "scenario_create") == (v["base"] is None))
        if v["base"] is not None:
            require(v["base"]["version"] <= 9)
    elif name == "GrantV4":
        intent = v["intent"]
        require(v["read_scope"] == ["scenario_context", "scenarios", "scenario"])
        require(v["proposal_tools"] == [intent["operation"]])
        require(
            (
                datetime.fromisoformat(v["expires_at"]) - datetime.fromisoformat(v["created_at"])
            ).total_seconds()
            == 300
        )
        source = intent["input_source"]
        if source["source"] == "operator":
            require(source["inputs"] == v["resolved_inputs"])
        require(v["inputs_digest"] == inputs_digest(source, v["resolved_inputs"]))
        require(len(canonical(v)) <= 8192)


def proposal_digest(call_id, grant_id, proposal):
    return digest(
        dict(
            call_id=call_id,
            grant_id=grant_id,
            **{k: v for k, v in proposal.items() if k != "digest"},
        )
    )


def scenario_ref(record):
    return {k: record[k] for k in ("id", "version", "digest")}


TERMINAL_CODES = {
    "denied": {"CHAT_TOOL_DENIED", "CHAT_TOOL_WRITE_FENCED", "CHAT_SCENARIO_WRITE_FENCED"},
    "conflict": {"CHAT_TOOL_CONFLICT"},
    "failed": {
        "CHAT_TIMEOUT",
        "CHAT_INVALID_REQUEST",
        "CHAT_NOT_FOUND",
        "CHAT_TOOL_LIMIT",
        "CHAT_STORAGE_ERROR",
    },
    "uncertain": {"CHAT_TOOL_UNCERTAIN"},
    "cancelled": {"CHAT_CANCELLED"},
}


def call_consistency(c):
    a = validate_arguments(c["tool"], c["arguments"])
    require(c["args_digest"] == digest(a))
    status, result, p, decision = c["status"], c["result"], c["proposal"], c["decision"]
    instant = datetime.fromisoformat
    terminal = status == "succeeded" or status in TERMINAL_CODES
    if not terminal:
        require(result is None and c["error_code"] is None and c["finished_at"] is None)
    else:
        require(
            c["finished_at"] is not None and instant(c["finished_at"]) >= instant(c["started_at"])
        )
        if status == "succeeded":
            require(result is not None and c["error_code"] is None)
            expected = {
                "scenario_create": "scenario_created",
                "scenario_append": "scenario_appended",
            }.get(c["tool"], a.get("kind"))
            require(result["kind"] == expected)
        else:
            require(result is None and c["error_code"] in TERMINAL_CODES[status])
    if c["error_code"] == "CHAT_TOOL_DENIED":
        require(decision is not None and decision["decision"] == "deny")
    if c["tool"] == "configuration_read":
        require(p is None and decision is None and status not in {"awaiting_approval", "uncertain"})
        if result is not None:
            if a["kind"] == "scenario":
                require(
                    scenario_ref(result["scenario"])
                    == {k: a[k] for k in ("id", "version", "digest")}
                )
            elif a["kind"] == "scenarios":
                require(all(result[k] == a[k] for k in ("offset", "limit")))
    else:
        if status == "requested":
            require(p is None)
        if p is not None:
            require(
                p["operation"] == c["tool"]
                and p["digest"] == proposal_digest(c["id"], c["grant_id"], p)
            )
            require(
                all(p[k] == a[k] for k in ("expected_scenario_revision", "expected_draft_revision"))
            )
            require(model_projection(p["after"]) == a["definition"])
            if c["tool"] == "scenario_append":
                require(scenario_ref(p["before"]) == a["base"])
        if status == "awaiting_approval":
            require(p is not None and decision is None)
        if status in {"executing", "succeeded", "uncertain"}:
            require(p is not None and decision is not None and decision["decision"] == "approve")
        if decision is not None:
            require(
                p is not None
                and decision["call_id"] == c["id"]
                and decision["proposal_digest"] == p["digest"]
            )
            require(status not in {"requested", "awaiting_approval"})
            if decision["decision"] == "deny":
                require(status == "denied" and c["error_code"] == "CHAT_TOOL_DENIED")
            accepted = instant(decision["accepted_at"])
            require(instant(c["started_at"]) <= accepted < instant(p["expires_at"]))
            require(c["finished_at"] is None or accepted <= instant(c["finished_at"]))
        if result is not None:
            saved = result["scenario"]
            require(result["before_scenario_revision"] == p["expected_scenario_revision"])
            require(result["source_draft_revision"] == p["expected_draft_revision"])
            require(saved["definition"] == p["after"])
            require(all(saved[k] == v for k, v in p["snapshots"].items()))
            if c["tool"] == "scenario_append":
                require(
                    saved["id"] == p["before"]["id"]
                    and saved["version"] == p["before"]["version"] + 1
                )
    require(len(canonical(c)) <= 262144)


def allows_call(grant, tool, arguments):
    """Effect-free scope/binding check for admission BEFORE Call allocation."""
    try:
        g = GrantV4.model_validate(grant).model_dump()
        a = validate_arguments(tool, arguments)
        if tool == "configuration_read":
            return a["kind"] in g["read_scope"]
        intent = g["intent"]
        return (
            tool == intent["operation"]
            and all(
                a[k] == intent[k] for k in ("expected_scenario_revision", "expected_draft_revision")
            )
            and (tool == "scenario_create" or a["base"] == intent["base"])
        )
    except (ValueError, TypeError):
        return False


def validate_call_binding(value, grant, *, deadline_at):
    """Pure link validation with a supplied retained/captured grant.

    The caller still owns session/turn/exchange/replay graph validation and
    original deadline acquisition. This function performs no storage lookup.
    """
    c = CallV4.model_validate(value).model_dump()
    g = GrantV4.model_validate(grant).model_dump()
    require(c["grant_id"] == g["id"] and allows_call(g, c["tool"], c["arguments"]))
    if c["proposal"] is not None:
        p = c["proposal"]
        require(p["input_source"] == g["intent"]["input_source"])
        require(p["inputs_digest"] == g["inputs_digest"])
        require(protected_projection(p["after"]) == g["resolved_inputs"])
        deadline = TypeAdapter(ChatTime).validate_python(deadline_at)
        require(
            datetime.fromisoformat(p["expires_at"])
            == min(datetime.fromisoformat(g["expires_at"]), datetime.fromisoformat(deadline))
        )
    result = c["result"]
    if result is not None and result["kind"] == "scenario_context":
        require(
            result["resolved_inputs"] == g["resolved_inputs"]
            and result["inputs_digest"] == g["inputs_digest"]
        )
        intent = g["intent"]
        require(result["operation"] == intent["operation"])
        require(
            result["scenario_revision"] == intent["expected_scenario_revision"]
            and result["draft_revision"] == intent["expected_draft_revision"]
        )
        require(
            (None if result["base"] is None else scenario_ref(result["base"])) == intent["base"]
        )
    return c


def bound_grant(value, request, *, settings_revision, profile_id, resolved_inputs):
    """Bind live POST/recovery to captured inputs, never current UI state.

    For version sources the caller supplies the independently validated selected
    immutable version projection. This helper does not resolve storage.
    """
    g = GrantV4.model_validate(value).model_dump()
    r = GrantInputV4.model_validate(request).model_dump()
    expected = ProtectedInputs.model_validate(resolved_inputs).model_dump()
    require(
        all(
            g[k] == r[k]
            for k in (
                "schema_version",
                "scope",
                "request_id",
                "session_id",
                "turn_request_id",
                "expected_sequence",
                "intent",
            )
        )
    )
    require(g["text_sha256"] == hashlib.sha256(r["text"].encode("utf-8")).hexdigest())
    require(g["settings_revision"] == settings_revision and g["profile_id"] == profile_id)
    require(g["resolved_inputs"] == expected)
    return g
