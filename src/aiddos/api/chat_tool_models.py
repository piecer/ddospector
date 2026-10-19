"""Closed CHAT02A companions. No domain I/O or model-granted authority."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, RootModel, TypeAdapter, model_validator

from .ai_settings import AIIdentifier
from .catalog import SAFETY_RULES, SKILLS_V1
from .chat_models import ChatID, ChatTime, Counter, TurnInput, encoded, user_text, valid_text
from .encoding import strict_json
from .models import AuditEvent, ClosedModel, Skill, SkillInput, Target, TargetInput
from .validation import Description, Identifier, Instructions, Name, unique_ids

POOL_BYTES = 2 * 1024 * 1024
TURN_RESERVATION = 1024 * 1024
RECONCILE_HOLD = 8192
CALL_BYTES = 256 * 1024
EXCHANGE_BYTES = 96 * 1024
RESULT_BYTES = 32 * 1024
ARGUMENT_BYTES = 16 * 1024
PAYLOAD_BYTES = 128 * 1024
TERMINAL = {"succeeded", "denied", "conflict", "failed", "uncertain", "cancelled"}
CODES = {
    "denied": {"CHAT_TOOL_DENIED", "CHAT_TOOL_WRITE_FENCED"},
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
ToolName = Literal["configuration_read", "agent_profile_update", "target_create", "skill_create"]
WRITE_TOOLS = frozenset({"agent_profile_update", "target_create", "skill_create"})


def allows_call(grant, tool, arguments):
    version = grant["schema_version"]
    if type(version) is not int or version not in (1, 2, 3):
        return False
    if version in (2, 3) and grant.get("scope") != {2: "target_create", 3: "skill_create"}[version]:
        return False
    if tool == "configuration_read":
        return arguments["kind"] in grant["read_scope"]
    return tool == {1: "agent_profile_update", 2: "target_create", 3: "skill_create"}[version]


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ProviderID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[\x00-\x7f]+$")]
SkillIDs = Annotated[list[Identifier], Field(max_length=103), AfterValidator(unique_ids)]


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=True
        ).encode()
    ).hexdigest()


def instant(value):
    return datetime.fromisoformat(value)


class ToolModel(ClosedModel):
    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if (
            isinstance(value, dict)
            and "schema_version" in value
            and type(value["schema_version"]) is not int
        ):
            raise ValueError("Integer schema version required")
        return value


class AgentConfig(ToolModel):
    resource_id: Literal["agent-profile"]
    name: Name
    skill_ids: SkillIDs


class ToolRuntime(ToolModel):
    schema_version: Literal[1]
    mode: Literal["operator_approved_settings"]
    supported: bool
    reason: (
        Literal["CHAT_NOT_CONFIGURED", "CHAT_UNSUPPORTED_PROFILE", "CHAT_UNSUPPORTED_OPTIONS"]
        | None
    )
    tools: list[ToolName]
    max_calls: Literal[3]
    max_writes: Literal[1]
    requires_write_approval: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def strict_limits(cls, value):
        if isinstance(value, dict) and (
            type(value.get("max_calls")) is not int
            or type(value.get("max_writes")) is not int
            or value.get("requires_write_approval") is not True
        ):
            raise ValueError("Invalid runtime limits")
        return value

    @model_validator(mode="after")
    def support(self):
        if (
            self.supported != (self.reason is None)
            or self.tools
            != [
                "configuration_read",
                "agent_profile_update",
            ]
            + {1: [], 2: ["target_create"], 3: ["target_create", "skill_create"]}[
                self.schema_version
            ]
        ):
            raise ValueError("Invalid runtime support")
        return self


class ToolRuntimeV2(ToolRuntime):
    schema_version: Literal[2]


class ToolRuntimeV3(ToolRuntime):
    schema_version: Literal[3]


class AgentRead(ToolModel):
    kind: Literal["agent_profile"]


class SkillsRead(ToolModel):
    kind: Literal["skills"]
    offset: int = Field(ge=0, le=103)
    limit: int = Field(ge=1, le=10)


class SkillRead(ToolModel):
    kind: Literal["skill"]
    id: Identifier


ReadArguments = Annotated[AgentRead | SkillsRead | SkillRead, Field(discriminator="kind")]
SkillReadArguments = Annotated[SkillsRead | SkillRead, Field(discriminator="kind")]


class TargetsRead(ToolModel):
    kind: Literal["targets"]
    offset: int = Field(ge=0, le=100)
    limit: int = Field(ge=1, le=10)


class TargetRead(ToolModel):
    kind: Literal["target"]
    id: Identifier


TargetReadArguments = Annotated[TargetsRead | TargetRead, Field(discriminator="kind")]
IngressReadArguments = Annotated[
    AgentRead | SkillsRead | SkillRead | TargetsRead | TargetRead, Field(discriminator="kind")
]


class TargetCreateArguments(TargetInput):
    expected_draft_revision: Counter


class SkillCreateArguments(SkillInput):
    expected_draft_revision: Counter


class UpdateArguments(ToolModel):
    expected_draft_revision: Counter
    name: Name
    skill_ids: SkillIDs


def validate_arguments(tool, value):
    if tool == "configuration_read":
        return TypeAdapter(IngressReadArguments).validate_python(value).model_dump()
    if tool == "agent_profile_update":
        return UpdateArguments.model_validate(value).model_dump()
    if tool == "target_create":
        return TargetCreateArguments.model_validate(value).model_dump()
    if tool == "skill_create":
        return SkillCreateArguments.model_validate(value).model_dump()
    raise ValueError("Unknown tool")


def parse_arguments(tool, raw):
    if not isinstance(raw, str) or len(raw.encode()) > ARGUMENT_BYTES:
        raise ValueError("Native argument limit")
    return validate_arguments(tool, strict_json(raw.encode()))


class SkillSummary(ToolModel):
    id: Identifier
    name: Name
    category: Literal["planning", "measurement", "analysis"]
    status: Literal["template", "draft"]
    version: Literal["1.0.0"]


class SkillDetail(SkillSummary):
    description: Description
    instructions: Instructions


class AgentResult(ToolModel):
    kind: Literal["agent_profile"]
    draft_revision: Counter
    agent_profile: AgentConfig


class SkillsResult(ToolModel):
    kind: Literal["skills"]
    draft_revision: Counter
    items: list[SkillSummary] = Field(max_length=10)
    next_offset: Annotated[int, Field(ge=0, le=103)] | None


class SkillResult(ToolModel):
    kind: Literal["skill"]
    draft_revision: Counter
    skill: SkillDetail


class UpdateAudit(AuditEvent):
    action: Literal["agent_profile.updated"]
    origin: Literal["local_operator"]


class UpdateResult(ToolModel):
    kind: Literal["agent_profile_updated"]
    before_revision: Counter
    after_revision: Counter
    agent_profile: AgentConfig
    audit: UpdateAudit

    @model_validator(mode="after")
    def revision(self):
        if (
            self.after_revision != self.before_revision + 1
            or self.audit.entity_id != "agent-profile"
        ):
            raise ValueError("Invalid write receipt")
        return self


class ToolTarget(Target):
    # Domain defaults are not optional fields on the closed wire.
    status: Literal["draft"]


class TargetsInspection(ToolModel):
    schema_version: Literal[1]
    draft_revision: Counter
    targets: list[ToolTarget] = Field(max_length=100)

    @model_validator(mode="after")
    def bounded(self):
        if len({t.id for t in self.targets}) != len(self.targets):
            raise ValueError("Duplicate target identity")
        if len(encoded(self.model_dump())) > 128 * 1024:
            raise ValueError("Target inspection byte limit")
        return self


class TargetsResult(ToolModel):
    kind: Literal["targets"]
    draft_revision: Counter
    items: list[ToolTarget] = Field(max_length=10)
    next_offset: Annotated[int, Field(ge=0, le=100)] | None


class TargetResult(ToolModel):
    kind: Literal["target"]
    draft_revision: Counter
    target: ToolTarget


class TargetAudit(AuditEvent):
    action: Literal["target.created"]
    origin: Literal["local_operator"]


class TargetCreatedResult(ToolModel):
    kind: Literal["target_created"]
    before_revision: Counter
    after_revision: Counter
    target: ToolTarget
    audit: TargetAudit

    @model_validator(mode="after")
    def revision(self):
        if (
            self.after_revision != self.before_revision + 1
            or self.audit.entity_id != self.target.id
            or self.audit.created_at != self.target.created_at
        ):
            raise ValueError("Invalid target creation receipt")
        return self


class CompleteDraftSkill(Skill):
    # All ten domain fields are required on the wire, including domain defaults.
    version: Literal["1.0.0"]
    status: Literal["draft"]

    @model_validator(mode="after")
    def draft_policy(self):
        if (
            self.id in {s["id"] for s in SKILLS_V1}
            or self.allowed_operations != []
            or self.required_capabilities != []
            or [r.model_dump() for r in self.safety_rules] != SAFETY_RULES
            or any(
                getattr(self, k).en != getattr(self, k).ko
                for k in ("name", "description", "instructions")
            )
        ):
            raise ValueError("Invalid complete draft Skill")
        SkillInput.model_validate(
            {
                **{k: getattr(self, k).en for k in ("name", "description", "instructions")},
                "category": self.category,
            }
        )
        return self


class CompleteTemplateSkill(Skill):
    version: Literal["1.0.0"]
    status: Literal["template"]

    @model_validator(mode="after")
    def catalog_identity(self):
        if self.model_dump() not in SKILLS_V1:
            raise ValueError("Unknown or altered catalog Skill")
        return self


CompleteActualSkill = Annotated[
    CompleteDraftSkill | CompleteTemplateSkill, Field(discriminator="status")
]


class SkillInspection(ToolModel):
    schema_version: Literal[1]
    draft_revision: Counter
    skill: CompleteActualSkill

    @model_validator(mode="after")
    def bounded(self):
        if len(encoded(self.model_dump())) > 131072:
            raise ValueError("Skill inspection byte limit")
        return self


class SkillName(ToolModel):
    en: Name
    ko: Name


class SkillInspectionSummary(ToolModel):
    id: Identifier
    name: SkillName
    category: Literal["planning", "measurement", "analysis"]
    status: Literal["template", "draft"]
    version: Literal["1.0.0"]

    @model_validator(mode="after")
    def identity(self):
        if self.status == "draft":
            if self.id in {s["id"] for s in SKILLS_V1} or self.name.en != self.name.ko:
                raise ValueError("Invalid draft Skill summary")
        elif self.model_dump() not in [
            {k: s[k] for k in ("id", "name", "category", "status", "version")} for s in SKILLS_V1
        ]:
            raise ValueError("Invalid template Skill summary")
        return self


class SkillsInspection(ToolModel):
    schema_version: Literal[1]
    draft_revision: Counter
    skills: list[SkillInspectionSummary] = Field(min_length=3, max_length=103)

    @model_validator(mode="after")
    def bounded(self):
        if (
            [s.id for s in self.skills[:3]] != [s["id"] for s in SKILLS_V1]
            or len({s.id for s in self.skills}) != len(self.skills)
            or any(s.status != "draft" for s in self.skills[3:])
            or len(encoded(self.model_dump())) > 131072
        ):
            raise ValueError("Invalid bounded Skill inventory")
        return self


class SkillAudit(AuditEvent):
    action: Literal["skill.created"]
    origin: Literal["local_operator"]


class SkillCreatedResult(ToolModel):
    kind: Literal["skill_created"]
    before_revision: Counter
    after_revision: Counter
    skill: CompleteDraftSkill
    audit: SkillAudit

    @model_validator(mode="after")
    def revision(self):
        if (
            self.after_revision != self.before_revision + 1
            or self.audit.entity_id != self.skill.id
            or self.audit.id == self.skill.id
        ):
            raise ValueError("Invalid Skill creation receipt")
        return self


Result = Annotated[
    AgentResult
    | SkillsResult
    | SkillResult
    | UpdateResult
    | TargetsResult
    | TargetResult
    | TargetCreatedResult
    | SkillCreatedResult,
    Field(discriminator="kind"),
]


def validate_result(value):
    result = TypeAdapter(Result).validate_python(value).model_dump()
    if len(encoded(result)) > RESULT_BYTES:
        raise ValueError("Result byte limit")
    return result


class GrantInput(ToolModel):
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Counter
    text: Annotated[str, AfterValidator(user_text)]


class TargetGrantInput(GrantInput):
    schema_version: Literal[2]
    scope: Literal["target_create"]


class SkillGrantInput(GrantInput):
    schema_version: Literal[3]
    scope: Literal["skill_create"]


class GrantRequest(RootModel[GrantInput | TargetGrantInput | SkillGrantInput]):
    """Closed body union; legacy explicit schema_version=1 remains forbidden."""


class Grant(ToolModel):
    schema_version: Literal[1]
    id: ChatID
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Counter
    text_sha256: Digest
    settings_revision: Counter
    profile_id: AIIdentifier
    created_at: ChatTime
    expires_at: ChatTime
    status: Literal["pending", "consumed", "revoked", "expired"]
    read_scope: list[Literal["agent_profile", "skills", "skill"]]
    proposal_fields: list[Literal["name", "skill_ids"]]

    @model_validator(mode="after")
    def authority(self):
        if (
            self.read_scope != ["agent_profile", "skills", "skill"]
            or self.proposal_fields != ["name", "skill_ids"]
            or (instant(self.expires_at) - instant(self.created_at)).total_seconds() != 300
        ):
            raise ValueError("Invalid grant scope or expiry")
        return self


class TargetGrant(ToolModel):
    schema_version: Literal[2]
    id: ChatID
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Counter
    text_sha256: Digest
    settings_revision: Counter
    profile_id: AIIdentifier
    created_at: ChatTime
    expires_at: ChatTime
    status: Literal["pending", "consumed", "revoked", "expired"]
    scope: Literal["target_create"]
    read_scope: list[Literal["targets", "target"]]
    proposal_tools: list[Literal["target_create"]]

    @model_validator(mode="after")
    def authority(self):
        if (
            self.read_scope != ["targets", "target"]
            or self.proposal_tools != ["target_create"]
            or (instant(self.expires_at) - instant(self.created_at)).total_seconds() != 300
        ):
            raise ValueError("Invalid grant scope or expiry")
        return self


class SkillGrant(ToolModel):
    schema_version: Literal[3]
    id: ChatID
    request_id: ChatID
    session_id: ChatID
    turn_request_id: ChatID
    expected_sequence: Counter
    text_sha256: Digest
    settings_revision: Counter
    profile_id: AIIdentifier
    created_at: ChatTime
    expires_at: ChatTime
    status: Literal["pending", "consumed", "revoked", "expired"]
    scope: Literal["skill_create"]
    read_scope: list[Literal["skills", "skill"]]
    proposal_tools: list[Literal["skill_create"]]

    @model_validator(mode="after")
    def authority(self):
        if (
            self.read_scope != ["skills", "skill"]
            or self.proposal_tools != ["skill_create"]
            or (instant(self.expires_at) - instant(self.created_at)).total_seconds() != 300
        ):
            raise ValueError("Invalid grant scope or expiry")
        return self


GrantRecord = Annotated[Grant | TargetGrant | SkillGrant, Field(discriminator="schema_version")]


class ToolTurnInput(TurnInput):
    grant_id: ChatID


class DecisionInput(ToolModel):
    request_id: ChatID
    proposal_digest: Digest
    decision: Literal["approve", "deny"]


class Decision(DecisionInput):
    schema_version: Literal[1]
    call_id: ChatID
    accepted_at: ChatTime


class Proposal(ToolModel):
    digest: Digest
    expected_draft_revision: Counter
    before: AgentConfig
    after: AgentConfig
    expires_at: ChatTime


class TargetCreateProposal(ToolModel):
    operation: Literal["target_create"]
    digest: Digest
    expected_draft_revision: Counter
    before: None
    after: TargetInput
    expires_at: ChatTime


class SkillCreateProposal(ToolModel):
    operation: Literal["skill_create"]
    digest: Digest
    expected_draft_revision: Counter
    before: None
    after: SkillInput
    expires_at: ChatTime


ProposalRecord = Proposal | TargetCreateProposal | SkillCreateProposal


def proposal_digest(call_id, grant_id, proposal):
    return digest(
        {
            "call_id": call_id,
            "grant_id": grant_id,
            **({"operation": proposal["operation"]} if "operation" in proposal else {}),
            **{
                key: proposal[key]
                for key in ("expected_draft_revision", "before", "after", "expires_at")
            },
        }
    )


class ToolCall(ToolModel):
    id: ChatID
    index: int = Field(ge=0, le=2)
    provider_call_id: ProviderID
    tool: ToolName
    arguments: IngressReadArguments | UpdateArguments | TargetCreateArguments | SkillCreateArguments
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
    error_code: str | None
    proposal: ProposalRecord | None
    decision: Decision | None
    result: Result | None
    started_at: ChatTime
    finished_at: ChatTime | None

    @model_validator(mode="after")
    def state(self):
        arguments = self.arguments.model_dump()
        validate_arguments(self.tool, arguments)
        if self.args_digest != digest(arguments):
            raise ValueError("Argument digest mismatch")
        if self.status not in TERMINAL:
            if any(v is not None for v in (self.result, self.error_code, self.finished_at)):
                raise ValueError("Nonterminal outcome")
        elif self.finished_at is None or instant(self.finished_at) < instant(self.started_at):
            raise ValueError("Invalid terminal time")
        elif self.status == "succeeded":
            if self.result is None or self.error_code is not None:
                raise ValueError("Missing success receipt")
            result = validate_result(self.result.model_dump())
            expected = {
                "agent_profile_update": "agent_profile_updated",
                "target_create": "target_created",
                "skill_create": "skill_created",
            }.get(self.tool, arguments.get("kind"))
            if result["kind"] != expected:
                raise ValueError("Wrong result kind")
            if expected == "skill" and result["skill"]["id"] != arguments["id"]:
                raise ValueError("Wrong skill receipt")
            if expected == "target" and result["target"]["id"] != arguments["id"]:
                raise ValueError("Wrong target receipt")
            if expected == "targets":
                count = len(result["items"])
                end = arguments["offset"] + count
                if (
                    count > arguments["limit"]
                    or end > 100
                    or len({item["id"] for item in result["items"]}) != count
                    or (
                        result["next_offset"] is not None
                        and (
                            count != arguments["limit"]
                            or result["next_offset"] != end
                            or end >= 100
                        )
                    )
                ):
                    raise ValueError("Wrong target page receipt")
        elif self.result is not None or self.error_code not in CODES[self.status]:
            raise ValueError("Invalid terminal code")
        if self.error_code == "CHAT_TOOL_DENIED" and (
            self.decision is None or self.decision.decision != "deny"
        ):
            raise ValueError("Explicit denial requires a deny decision")
        if self.tool == "configuration_read":
            if (
                self.proposal is not None
                or self.decision is not None
                or self.status in {"awaiting_approval", "uncertain"}
            ):
                raise ValueError("Read authority")
        elif self.tool in WRITE_TOOLS:
            if self.status == "requested" and self.proposal is not None:
                raise ValueError("Requested call has no proposal yet")
            if self.proposal is not None:
                p = self.proposal.model_dump()
                if (
                    type(self.proposal)
                    is not {
                        "agent_profile_update": Proposal,
                        "target_create": TargetCreateProposal,
                        "skill_create": SkillCreateProposal,
                    }[self.tool]
                ):
                    raise ValueError("Wrong proposal operation")
                fields = {
                    "agent_profile_update": ("name", "skill_ids"),
                    "target_create": ("name", "address", "kind"),
                    "skill_create": ("name", "description", "instructions", "category"),
                }[self.tool]
                if (
                    p["digest"] != proposal_digest(self.id, self.grant_id, p)
                    or p["expected_draft_revision"] != arguments["expected_draft_revision"]
                    or any(p["after"][key] != arguments[key] for key in fields)
                ):
                    raise ValueError("Proposal mismatch")
            if self.status == "awaiting_approval" and (
                self.proposal is None or self.decision is not None
            ):
                raise ValueError("Invalid waiting state")
            if self.status in {"executing", "succeeded", "uncertain"} and (
                self.proposal is None
                or self.decision is None
                or self.decision.decision != "approve"
            ):
                raise ValueError("Missing approved intent")
            if self.decision is not None and (
                self.proposal is None
                or self.decision.call_id != self.id
                or self.decision.proposal_digest != self.proposal.digest
                or (
                    self.decision.decision == "deny"
                    and (self.status != "denied" or self.error_code != "CHAT_TOOL_DENIED")
                )
                or self.status in {"requested", "awaiting_approval"}
                or instant(self.decision.accepted_at) < instant(self.started_at)
                or (
                    self.finished_at is not None
                    and instant(self.finished_at) < instant(self.decision.accepted_at)
                )
                or instant(self.decision.accepted_at) >= instant(self.proposal.expires_at)
            ):
                raise ValueError("Decision mismatch")
            if self.status == "succeeded":
                if self.tool == "target_create":
                    saved = {
                        key: getattr(self.result.target, key) for key in ("name", "address", "kind")
                    }
                elif self.tool == "skill_create":
                    saved = {
                        **{
                            key: getattr(self.result.skill, key).en
                            for key in ("name", "description", "instructions")
                        },
                        "category": self.result.skill.category,
                    }
                else:
                    saved = self.result.agent_profile.model_dump()
                if (
                    self.result.before_revision != self.proposal.expected_draft_revision
                    or saved != self.proposal.after.model_dump()
                ):
                    raise ValueError("Receipt differs from approval")
        if len(encoded(self.model_dump())) > CALL_BYTES:
            raise ValueError("Call byte limit")
        return self


class ToolTranscript(ToolModel):
    schema_version: Literal[1]
    turn_id: ChatID
    revision: Counter
    calls: list[ToolCall] = Field(max_length=3)

    @model_validator(mode="after")
    def ordered(self):
        if (
            [c.index for c in self.calls] != list(range(len(self.calls)))
            or len({c.id for c in self.calls}) != len(self.calls)
            or len({c.provider_call_id for c in self.calls}) != len(self.calls)
            or sum(c.proposal is not None for c in self.calls) > 1
        ):
            raise ValueError("Invalid call cardinality")
        if len(encoded(self.model_dump())) > 1024 * 1024:
            raise ValueError("Companion byte limit")
        return self


class Fence(ToolModel):
    schema_version: Literal[1]
    generation: Counter
    fenced: bool
    call_ids: list[ChatID] = Field(max_length=1)
    current_draft_revision: Counter | None

    @model_validator(mode="after")
    def consistency(self):
        if self.fenced != bool(self.call_ids):
            raise ValueError("Fence mismatch")
        return self


class ReconcileInput(ToolModel):
    request_id: ChatID
    expected_generation: Counter
    expected_draft_revision: Counter
    acknowledge_uncertain: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def true_only(cls, value):
        if isinstance(value, dict) and value.get("acknowledge_uncertain") is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class ReconcileReceipt(ToolModel):
    schema_version: Literal[1]
    request_id: ChatID
    acknowledged_call_ids: list[ChatID] = Field(min_length=1, max_length=1)
    generation: Counter
    write_fenced: Literal[False]
    prior_outcomes: Literal["remain_uncertain"]

    @model_validator(mode="before")
    @classmethod
    def false_only(cls, value):
        if isinstance(value, dict) and value.get("write_fenced") is not False:
            raise ValueError("Boolean required")
        return value


class Function(ToolModel):
    name: ToolName
    arguments: str

    @model_validator(mode="after")
    def native(self):
        parse_arguments(self.name, self.arguments)
        return self


class NativeCall(ToolModel):
    id: ProviderID
    type: Literal["function"]
    function: Function


class AssistantCall(ToolModel):
    role: Literal["assistant"]
    content: Annotated[str, AfterValidator(lambda s: valid_text(s, 65536))]
    tool_calls: list[NativeCall] = Field(min_length=1, max_length=1)


class AssistantFinal(ToolModel):
    role: Literal["assistant"]
    content: Annotated[str, AfterValidator(lambda s: valid_text(s, 65536, nonblank=True))]


class ToolEnvelope(ToolModel):
    ok: bool
    result: Result | None
    error_code: str | None

    @model_validator(mode="after")
    def outcome(self):
        if self.ok:
            if self.result is None or self.error_code is not None:
                raise ValueError("Invalid success envelope")
            validate_result(self.result.model_dump())
        elif self.result is not None or self.error_code not in set().union(*CODES.values()):
            raise ValueError("Invalid failure envelope")
        return self


class ToolMessage(ToolModel):
    role: Literal["tool"]
    tool_call_id: ProviderID
    content: str

    @model_validator(mode="after")
    def envelope(self):
        value = ToolEnvelope.model_validate(strict_json(self.content.encode())).model_dump()
        if encoded(value).decode() != self.content:
            raise ValueError("Noncanonical tool envelope")
        return self


def validate_exchange(messages):
    if not isinstance(messages, list) or len(encoded(messages)) > EXCHANGE_BYTES:
        raise ValueError("Exchange byte limit")
    pending = None
    seen = set()
    for index, message in enumerate(messages):
        if pending is not None:
            parsed = ToolMessage.model_validate(message)
            if parsed.tool_call_id != pending:
                raise ValueError("Wrong provider linkage")
            pending = None
        elif "tool_calls" in message:
            parsed = AssistantCall.model_validate(message)
            pending = parsed.tool_calls[0].id
            if pending in seen or len(seen) >= 3:
                raise ValueError("Repeated provider call")
            seen.add(pending)
        else:
            AssistantFinal.model_validate(message)
            if index != len(messages) - 1:
                raise ValueError("Final must be last")
    return messages
