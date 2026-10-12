"""Closed scenario metadata and transport. Registration never enables execution."""

import hashlib
import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BeforeValidator, Field, model_validator
from starlette.responses import Response

from .catalog import PROFILES_V1
from .construction import serialized
from .errors import DraftError
from .models import ClosedModel, LocalizedText, Target, Timestamp
from .validation import Goal, Identifier, Name

MAX_RECORD_BYTES = 8192
MAX_PAGE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def record_digest(record: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "digest"})).hexdigest()


def bounded_output(value: dict, limit: int, code: str = "SCENARIO_STATE_CORRUPT") -> bytes:
    raw = canonical(value)
    if len(raw) > limit:
        raise DraftError(code)
    return raw


def exact_int(value):
    if type(value) is not int:
        raise ValueError("Expected an integer")
    return value


def exact_bool(value):
    if type(value) is not bool:
        raise ValueError("Expected a boolean")
    return value


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Percentage = Annotated[int, Field(ge=0, le=100)]


class PcapAsset(ClosedModel):
    label: Name
    sha256: Digest
    size_bytes: int = Field(ge=1, le=67108864)


class TrafficBudget(ClosedModel):
    max_pps: int = Field(ge=1, le=1000000000)
    max_bps: int = Field(ge=1, le=1000000000000)
    max_packets: int = Field(ge=1, le=1000000000000)
    max_bytes: int = Field(ge=1, le=1000000000000)
    max_connections: int = Field(ge=1, le=1000000)
    duration_seconds: int = Field(ge=1, le=3600)


class SuccessCriteria(ClosedModel):
    minimum_delivery_pct: Percentage
    maximum_delivery_pct: Percentage
    detection_deadline_ms: Annotated[int, Field(ge=1, le=60000)] | None


class StopConditions(ClosedModel):
    max_legitimate_loss_pct: Percentage
    max_service_latency_ms: int = Field(ge=1, le=60000)
    max_cpu_pct: Annotated[int, Field(ge=1, le=100)] | None
    max_memory_pct: Annotated[int, Field(ge=1, le=100)] | None
    max_sessions: Annotated[int, Field(ge=1, le=1000000)] | None
    management_loss: Annotated[Literal[True], BeforeValidator(exact_bool)]


class ScenarioDefinition(ClosedModel):
    name: Name
    objective: Goal
    target_id: Identifier
    sink_id: Identifier
    dut_version: Name
    policy_version: Name
    profile_id: Literal["tcpreplay-policy", "k6-http"]
    protocol: Literal["TCP", "UDP", "DNS", "HTTP"]
    ip_version: Annotated[Literal[4, 6], BeforeValidator(exact_int)]
    expected_action: Literal["ALLOW", "BLOCK", "ALERT"]
    delivery_expectation: Literal["ALLOW", "BLOCK"]
    detection_required: bool
    pcap_asset: PcapAsset | None
    traffic_budget: TrafficBudget
    success_criteria: SuccessCriteria
    stop_conditions: StopConditions
    evidence_requirements: list[
        Literal["ingress_pcap", "egress_pcap", "dut_events", "service_probe", "resource_metrics"]
    ] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def coherent_expectations(self):
        replay = self.profile_id == "tcpreplay-policy"
        if replay == (self.protocol == "HTTP") or (not replay and self.pcap_asset is not None):
            raise ValueError("Profile and traffic metadata disagree")
        if self.expected_action == "ALERT":
            if not self.detection_required:
                raise ValueError("Alert requires detection")
        elif self.delivery_expectation != self.expected_action:
            raise ValueError("Delivery and policy disagree")
        criteria = self.success_criteria
        if (
            criteria.minimum_delivery_pct > criteria.maximum_delivery_pct
            or (self.delivery_expectation == "ALLOW" and criteria.maximum_delivery_pct != 100)
            or (self.delivery_expectation == "BLOCK" and criteria.minimum_delivery_pct != 0)
            or self.detection_required != (criteria.detection_deadline_ms is not None)
        ):
            raise ValueError("Observation criteria disagree")
        required = {"service_probe"}
        if replay:
            required.update(("ingress_pcap", "egress_pcap"))
        if self.detection_required:
            required.add("dut_events")
        stops = self.stop_conditions
        if any(
            v is not None for v in (stops.max_cpu_pct, stops.max_memory_pct, stops.max_sessions)
        ):
            required.add("resource_metrics")
        evidence = set(self.evidence_requirements)
        if len(evidence) != len(self.evidence_requirements) or not required <= evidence:
            raise ValueError("Missing or duplicate evidence role")
        return self


class ScenarioInput(ClosedModel):
    revision: int = Field(ge=0, le=9007199254740990)
    definition: ScenarioDefinition


class ProfileSnapshot(ClosedModel):
    id: Literal["tcpreplay-policy", "k6-http"]
    name: LocalizedText
    description: LocalizedText
    engine: Literal["tcpreplay", "k6"]
    layer: Literal["L2–L4", "L7"]
    status: Literal["template"]


class TargetSnapshot(Target):
    # Existing Target permits an in-memory default; persisted snapshots do not.
    status: Literal["draft"] = Field(...)


class ScenarioVersion(ClosedModel):
    id: Identifier
    version: int = Field(ge=1, le=10)
    created_at: Timestamp
    status: Literal["definition"]
    execution_enabled: Annotated[Literal[False], BeforeValidator(exact_bool)]
    definition: ScenarioDefinition
    target_snapshot: TargetSnapshot
    sink_snapshot: TargetSnapshot
    profile_snapshot: ProfileSnapshot
    catalog_version: Literal["1.0.0"]
    digest: Digest

    @model_validator(mode="after")
    def bound_snapshot(self):
        if (
            self.target_snapshot.id != self.definition.target_id
            or self.sink_snapshot.id != self.definition.sink_id
            or self.target_snapshot.id == self.sink_snapshot.id
            or self.target_snapshot.kind != "DUT"
            or self.sink_snapshot.kind != "SINK"
            or self.profile_snapshot.model_dump()
            != next(p for p in PROFILES_V1 if p["id"] == self.definition.profile_id)
        ):
            raise ValueError("Inconsistent embedded snapshot")
        record = self.model_dump()
        if self.digest != record_digest(record) or len(canonical(record)) > MAX_RECORD_BYTES:
            raise ValueError("Invalid record digest or size")
        return self


class ScenarioIdentity(ClosedModel):
    id: Identifier
    versions: list[ScenarioVersion] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def consecutive_versions(self):
        if any(v.id != self.id or v.version != n for n, v in enumerate(self.versions, 1)):
            raise ValueError("Inconsistent scenario history")
        return self


class ScenarioState(ClosedModel):
    format_version: Annotated[Literal[1], BeforeValidator(exact_int)]
    revision: int = Field(ge=0, le=1000)
    scenarios: list[ScenarioIdentity] = Field(max_length=100)

    @model_validator(mode="after")
    def registry_counts(self):
        if len({s.id for s in self.scenarios}) != len(self.scenarios) or self.revision != sum(
            len(s.versions) for s in self.scenarios
        ):
            raise ValueError("Inconsistent registry count or identity")
        return self


def scenario_router(drafts, *, ticket=None) -> APIRouter:
    # Storage imports the closed types, while wiring supplies the effective draft path.
    from .scenario_store import ScenarioStore

    store = ScenarioStore(drafts, ticket=ticket)
    return _compose_scenarios(store)


@serialized
def _compose_scenarios(store) -> APIRouter:
    router = APIRouter(prefix="/api/v1/scenarios")

    @router.get("")
    def list_scenarios(request: Request):
        query = request.query_params
        if len(query.multi_items()) != len(query) or set(query) - {"offset", "limit"}:
            raise DraftError("VALIDATION_ERROR")
        values = []
        for name, default, minimum in (("offset", "0", 0), ("limit", "50", 1)):
            text = query.get(name, default)
            if not re.fullmatch(r"0|[1-9][0-9]{0,2}", text):
                raise DraftError("VALIDATION_ERROR")
            number = int(text)
            if not minimum <= number <= 100:
                raise DraftError("VALIDATION_ERROR")
            values.append(number)
        offset, limit = values
        return Response(
            bounded_output(store.page(offset, limit), MAX_PAGE_BYTES), media_type="application/json"
        )

    @router.get("/{scenario_id}")
    def history(scenario_id: Identifier):
        return Response(
            bounded_output(store.history(scenario_id), MAX_RESPONSE_BYTES),
            media_type="application/json",
        )

    @router.post("", status_code=201)
    def create(value: ScenarioInput):
        return Response(
            bounded_output(store.save(value), MAX_RESPONSE_BYTES),
            status_code=201,
            media_type="application/json",
        )

    @router.put("/{scenario_id}")
    def append(scenario_id: Identifier, value: ScenarioInput):
        return Response(
            bounded_output(store.save(value, scenario_id), MAX_RESPONSE_BYTES),
            media_type="application/json",
        )

    return router
