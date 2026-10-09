"""Closed draft schemas. User text is data, not execution configuration."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .catalog import PROFILES_V1, SAFETY_RULES, SKILLS_V1
from .validation import (
    Address,
    Description,
    Endpoint,
    Goal,
    Identifier,
    Instructions,
    Name,
    endpoint_literal,
    unique_ids,
)


def valid_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return value


Timestamp = Annotated[str, Field(min_length=20, max_length=40), AfterValidator(valid_timestamp)]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TargetInput(ClosedModel):
    name: Name
    address: Address
    kind: Literal["DUT", "SINK"]


class Target(TargetInput):
    id: Identifier
    status: Literal["draft"] = "draft"
    created_at: Timestamp


class McpServerInput(ClosedModel):
    name: Name
    endpoint: Endpoint
    transport: Literal["streamable_http", "stdio"]
    usage_instructions: Instructions

    @model_validator(mode="after")
    def endpoint_matches_transport(self):
        endpoint_literal(self.endpoint, self.transport)
        return self


class McpServer(McpServerInput):
    id: Identifier
    status: Literal["draft"] = "draft"
    tools_count: Literal[0] = 0
    created_at: Timestamp


class LocalizedText(ClosedModel):
    en: str
    ko: str


class SkillInput(ClosedModel):
    name: Name
    description: Description
    instructions: Instructions
    category: Literal["planning", "measurement", "analysis"]


class Skill(ClosedModel):
    id: Identifier
    name: LocalizedText
    description: LocalizedText
    instructions: LocalizedText
    version: Literal["1.0.0"] = "1.0.0"
    category: Literal["planning", "measurement", "analysis"]
    status: Literal["template", "draft"]
    allowed_operations: list[str]
    required_capabilities: list[str]
    safety_rules: list[LocalizedText]


class CampaignInput(ClosedModel):
    name: Name
    objective: Goal
    target_id: Identifier
    profile_id: Identifier


class Campaign(CampaignInput):
    id: Identifier
    status: Literal["draft"] = "draft"
    created_at: Timestamp


class AuditEvent(ClosedModel):
    id: Identifier
    action: Literal[
        "target.created",
        "mcp_server.created",
        "skill.created",
        "campaign.created",
        "agent_profile.updated",
    ]
    entity_id: str
    created_at: Timestamp
    origin: Literal["local_operator"] = "local_operator"


class AgentProfileInput(ClosedModel):
    name: Name
    skill_ids: Annotated[list[Identifier], Field(max_length=103), AfterValidator(unique_ids)]
    mcp_server_ids: Annotated[list[Identifier], Field(max_length=100), AfterValidator(unique_ids)]


class AgentProfile(AgentProfileInput):
    autonomy: Literal["REVIEW_ONLY"] = "REVIEW_ONLY"
    execution_enabled: Literal[False] = False


class PreviewInput(ClosedModel):
    goal: Goal
    locale: Literal["en", "ko"]


class ContextPreview(ClosedModel):
    origin: Literal["deterministic_context_preview"] = "deterministic_context_preview"
    execution_enabled: Literal[False] = False
    prompt: str
    skill_ids: Annotated[list[Identifier], Field(max_length=103), AfterValidator(unique_ids)]
    mcp_server_ids: Annotated[list[Identifier], Field(max_length=100), AfterValidator(unique_ids)]


class DraftState(ClosedModel):
    format_version: Literal[1] = 1
    catalog_version: Literal["1.0.0"] = "1.0.0"
    targets: list[Target] = Field(default_factory=list, max_length=100)
    mcp_servers: list[McpServer] = Field(default_factory=list, max_length=100)
    skills: list[Skill] = Field(default_factory=list, max_length=100)
    agent_profile: AgentProfile = Field(
        default_factory=lambda: AgentProfile(
            name="Review agent",
            skill_ids=[],
            mcp_server_ids=[],
        )
    )
    campaigns: list[Campaign] = Field(default_factory=list, max_length=100)
    audit: list[AuditEvent] = Field(default_factory=list, max_length=500)
    audit_total: int = Field(default=0, ge=0, le=9007199254740991)

    @model_validator(mode="after")
    def validate_integrity(self):
        groups = (self.targets, self.mcp_servers, self.skills, self.campaigns, self.audit)
        identifiers = [item.id for group in groups for item in group]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate state identity")
        skills = {s["id"] for s in SKILLS_V1} | {s.id for s in self.skills}
        servers = {s.id for s in self.mcp_servers}
        targets = {t.id for t in self.targets}
        profiles = {p["id"] for p in PROFILES_V1}
        if (
            not set(self.agent_profile.skill_ids) <= skills
            or not set(self.agent_profile.mcp_server_ids) <= servers
        ):
            raise ValueError("Invalid assignment reference")
        if any(c.target_id not in targets or c.profile_id not in profiles for c in self.campaigns):
            raise ValueError("Invalid campaign reference")
        for skill in self.skills:
            if (
                skill.status != "draft"
                or skill.id in {s["id"] for s in SKILLS_V1}
                or skill.allowed_operations
                or skill.required_capabilities
                or [rule.model_dump() for rule in skill.safety_rules] != SAFETY_RULES
            ):
                raise ValueError("Invalid draft skill policy")
            for field in ("name", "description", "instructions"):
                text = getattr(skill, field)
                if text.en != text.ko:
                    raise ValueError("Draft text cannot contain an invented translation")
            SkillInput(
                name=skill.name.en,
                description=skill.description.en,
                instructions=skill.instructions.en,
                category=skill.category,
            )
        action_entities = {
            "target.created": targets,
            "mcp_server.created": servers,
            "skill.created": {s.id for s in self.skills},
            "campaign.created": {c.id for c in self.campaigns},
            "agent_profile.updated": {"agent-profile"},
        }
        if any(event.entity_id not in action_entities[event.action] for event in self.audit):
            raise ValueError("Invalid audit reference")
        if len(self.audit) != min(self.audit_total, 500):
            raise ValueError("Inconsistent audit retention")
        return self
