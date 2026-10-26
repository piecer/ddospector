"""Model/schema-produced synthetic wire fixtures, NOT native HTTP captures.

No ScenarioStore, ledger, provider, DNS or transport is exercised here.
"""

import json
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from aiddos.api import chat_scenario_models as m
from aiddos.api.catalog import PROFILES_V1
from aiddos.api.scenarios import ScenarioVersion, record_digest
from tests.chat.test_chat_scenario_models import IDS, STAMP, definition, grant, protected


def snapshots():
    def target(id, kind):
        return dict(
            id=id, name=id, address="lab.example", kind=kind, status="draft", created_at=STAMP
        )

    return dict(
        target_snapshot=target("dut", "DUT"),
        sink_snapshot=target("sink", "SINK"),
        profile_snapshot=next(p for p in PROFILES_V1 if p["id"] == "k6-http"),
        catalog_version="1.0.0",
    )


def record(id="legacy-scenario", version=1):
    content = dict(
        id=id,
        version=version,
        created_at=STAMP,
        status="definition",
        execution_enabled=False,
        definition={**definition(), **protected()},
        **snapshots(),
    )
    return ScenarioVersion.model_validate(
        {**content, "digest": record_digest(content)}
    ).model_dump()


def history():
    return dict(
        revision=2,
        scenario_id="legacy-scenario",
        versions=[record(), record(version=2)],
        execution_enabled=False,
    )


def page():
    return dict(
        revision=2, total=1, offset=0, limit=50, items=[record(version=2)], execution_enabled=False
    )


def proposal(operation="scenario_create"):
    source = grant()["intent"]["input_source"]
    p = dict(
        schema_version=4,
        operation=operation,
        expected_scenario_revision=0 if operation == "scenario_create" else 1,
        expected_draft_revision=0,
        before=None if operation == "scenario_create" else record(),
        after={**definition(), **protected()},
        snapshots=snapshots(),
        input_source=source,
        inputs_digest=m.inputs_digest(source, protected()),
        expires_at="2026-01-01T00:02:00Z",
    )
    return {**p, "digest": m.digest(dict(call_id=IDS[4], grant_id=IDS[3], **p))}


def call(operation="scenario_create"):
    p = proposal(operation)
    args = dict(
        expected_scenario_revision=p["expected_scenario_revision"],
        expected_draft_revision=0,
        definition=definition(),
    )
    if operation == "scenario_append":
        args["base"] = {k: p["before"][k] for k in ("id", "version", "digest")}
    result = dict(
        kind="scenario_created" if operation == "scenario_create" else "scenario_appended",
        before_scenario_revision=p["expected_scenario_revision"],
        after_scenario_revision=p["expected_scenario_revision"] + 1,
        source_draft_revision=0,
        execution_enabled=False,
        scenario=record(IDS[5]) if operation == "scenario_create" else record(version=2),
    )
    return dict(
        id=IDS[4],
        index=0,
        provider_call_id="provider-call",
        tool=operation,
        arguments=args,
        args_digest=m.digest(args),
        grant_id=IDS[3],
        actor="operator_authorized_model",
        status="succeeded",
        error_code=None,
        proposal=p,
        decision=dict(
            schema_version=1,
            request_id=IDS[6],
            call_id=IDS[4],
            proposal_digest=p["digest"],
            decision="approve",
            accepted_at=STAMP,
        ),
        result=result,
        started_at=STAMP,
        finished_at="2026-01-01T00:00:01Z",
    )


def model_bytes():
    assert (
        Path(m.__file__).resolve()
        == Path(__file__).resolve().parents[2] / "src/aiddos/api/chat_scenario_models.py"
    )
    output = {}
    for name, value in examples().items():
        m.validate_value(name, value)
        adapter = TypeAdapter(m.CONTRACT_TYPES[name])
        model = adapter.validate_python(value)
        output[name] = (
            model.model_dump_json()
            if isinstance(model, BaseModel)
            else adapter.dump_json(model).decode()
        )
    return output


def negative_bytes():
    """Synthetic derivatives of real model output; independently rejected by Python."""
    from copy import deepcopy

    specs = {
        "GrantV4": [
            (("resolved_inputs", "dut_version"), "forged"),
            (("inputs_digest",), "f" * 64),
            (("proposal_tools",), ["scenario_append"]),
            (("read_scope",), ["scenario"]),
            (("expires_at",), "2026-01-01T00:04:59Z"),
        ],
        "Intent": [
            (("base",), dict(id="old", version=1, digest="a" * 64)),
            (("operation",), "scenario_append"),
        ],
        "ModelDefinition": [(("evidence_requirements",), ["service_probe", "service_probe"])],
        "ProtectedInputs": [(("sink_id",), "dut")],
        "ScenarioDefinition": [
            (("protocol",), "TCP"),
            (("success_criteria", "maximum_delivery_pct"), 99),
            (("evidence_requirements",), ["dut_events"]),
        ],
        "ProfileSnapshot": [(("layer",), "L2–L4")],
        "TargetSnapshot": [(("address",), "https://foreign")],
        "ScenarioVersion": [(("digest",), "a" * 64)],
        "RuntimeV4": [(("supported",), False), (("tools",), ["scenario_create"])],
        "ContextResult": [
            (("target_snapshot", "kind"), "SINK"),
            (("operation",), "scenario_append"),
        ],
        "ListResult": [(("scenario_revision",), 2), (("next_offset",), 1)],
        "DetailResult": [(("scenario_revision",), 0)],
        "ProposalV4": [
            (("snapshots", "target_snapshot", "id"), "foreign"),
            (("inputs_digest",), "f" * 64),
            (("input_source", "inputs", "dut_version"), "forged"),
            (("operation",), "scenario_append"),
        ],
        "CreatedResult": [(("after_scenario_revision",), 2)],
        "AppendedResult": [(("source_draft_revision",), True)],
        "CallV4": [
            (("args_digest",), "a" * 64),
            (("proposal", "digest"), "a" * 64),
            (("proposal", "expected_draft_revision"), 1),
            (("proposal", "after", "name"), "foreign"),
            (("decision", "call_id"), IDS[0]),
            (("decision", "proposal_digest"), "a" * 64),
            (("decision", "decision"), "deny"),
            (("decision", "accepted_at"), "2026-01-01T00:02:00Z"),
            (("result", "source_draft_revision"), 1),
            (("proposal",), None),
            (("decision",), None),
            (("finished_at",), None),
            (("status",), "uncertain"),
            (("error_code",), "CHAT_TIMEOUT"),
        ],
        "TranscriptV4": [(("calls", 0, "index"), 1)],
        "ToolEnvelopeV4": [(("ok",), False)],
        "ScenarioExpectation": [(("after_scenario_revision",), 0)],
        "ScenarioSelection": [
            (("expectation",), dict(scenario=record(id="foreign"), after_scenario_revision=1))
        ],
        "ScenarioHistoryV4": [
            (("revision",), 1),
            (("versions", 0, "definition", "name"), "foreign"),
        ],
        "ScenarioPageV4": [(("revision",), 1), (("total",), 2), (("offset",), 1)],
    }
    result = []
    for name, changes in specs.items():
        for path, replacement in changes:
            value = deepcopy(examples()[name])
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            try:
                m.parse_value(name, raw)
            except ValueError:
                result.append(dict(name=name, path=list(path), raw=raw))
            else:
                raise AssertionError(f"Negative oracle unexpectedly accepted {name} {path}")
    for name in ("CreateArgs", "AppendArgs"):
        for location in ((), ("definition",)):
            for key, item in protected().items():
                value = deepcopy(examples()[name])
                target = value if not location else value["definition"]
                target[key] = item
                raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                try:
                    m.parse_value(name, raw)
                except ValueError:
                    result.append(dict(name=name, path=[*location, key], raw=raw))
                else:
                    raise AssertionError("Protected native extra accepted")
    result.extend(numeric_bytes())
    for description, c in inverse_negatives():
        raw = json.dumps(c, ensure_ascii=False, separators=(",", ":"))
        try:
            m.parse_value("CallV4", raw)
        except ValueError:
            result.append(dict(name="CallV4", path=[description], raw=raw))
        else:
            raise AssertionError(f"Inverse oracle unexpectedly accepted {description}")
    return result


def numeric_bytes():
    from copy import deepcopy

    def paths(value, path=()):
        if type(value) is int:
            yield path
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from paths(item, (*path, key))
        elif isinstance(value, list):
            for key, item in enumerate(value):
                yield from paths(item, (*path, key))

    result = []
    for name in ("GrantInputV4", "CreateArgs", "AppendArgs", "RuntimeV4", "ReconcileInputV4"):
        original = examples()[name]
        for path in paths(original):
            value = deepcopy(original)
            target = value
            for key in path[:-1]:
                target = target[key]
            number = target[path[-1]]
            target[path[-1]] = "NUMERIC_TOKEN"
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            for token in (f"{number}.0", f"{number}e0", "true", json.dumps(str(number))):
                raw = body.replace('"NUMERIC_TOKEN"', token)
                try:
                    m.parse_value(name, raw)
                except ValueError:
                    result.append(dict(name=name, path=[*path, token], raw=raw))
                else:
                    raise AssertionError(f"Noninteger raw token admitted: {name} {path}")
    return result


def inverse_negatives():
    from copy import deepcopy

    values = []
    for operation in ("scenario_create", "scenario_append"):
        for key in ("definition", "target_snapshot"):
            c = call(operation)
            saved = c["result"]["scenario"]
            saved[key]["name"] = "valid foreign stored value"
            saved["digest"] = record_digest(saved)
            ScenarioVersion.model_validate(saved)  # genuinely coherent full-record negative
            values.append((f"{operation}: saved {key} differs from approval", c))
        c = call(operation)
        c["proposal"]["after"]["name"] = "coherent foreign proposal"
        c["proposal"]["digest"] = m.proposal_digest(c["id"], c["grant_id"], c["proposal"])
        c["decision"]["proposal_digest"] = c["proposal"]["digest"]
        values.append((f"{operation}: rehashed proposal differs from native", c))
    c = call("scenario_append")
    c["result"]["scenario"]["id"] = "foreign"
    c["result"]["scenario"]["digest"] = record_digest(c["result"]["scenario"])
    values.append(("append: coherent foreign stored ID", c))
    return deepcopy(values)


def variants():
    from copy import deepcopy

    result = [("append", "CallV4", call("scenario_append"))]
    for status, code in (
        ("requested", None),
        ("awaiting_approval", None),
        ("executing", None),
        ("denied", "CHAT_TOOL_DENIED"),
        ("conflict", "CHAT_TOOL_CONFLICT"),
        ("failed", "CHAT_STORAGE_ERROR"),
        ("uncertain", "CHAT_TOOL_UNCERTAIN"),
        ("cancelled", "CHAT_CANCELLED"),
    ):
        c = call()
        c.update(status=status, error_code=code, result=None)
        if status in {"requested", "awaiting_approval", "executing"}:
            c["finished_at"] = None
        if status in {"requested", "awaiting_approval"}:
            c["decision"] = None
        if status == "requested":
            c["proposal"] = None
        if status == "denied":
            c["decision"]["decision"] = "deny"
        result.append((status, "CallV4", c))
    for args_name, result_name in (
        ("ContextArgs", "ContextResult"),
        ("ListArgs", "ListResult"),
        ("DetailArgs", "DetailResult"),
    ):
        c = call()
        c.update(
            tool="configuration_read",
            proposal=None,
            decision=None,
            arguments=examples()[args_name],
            result=examples()[result_name],
        )
        c["args_digest"] = m.digest(c["arguments"])
        result.append((args_name, "CallV4", c))
    result.append(
        ("empty", "TranscriptV4", dict(schema_version=4, turn_id=IDS[2], revision=0, calls=[]))
    )
    g = deepcopy(grant())
    g["intent"]["input_source"] = dict(
        source="scenario_version", reference=m.scenario_ref(record())
    )
    g["inputs_digest"] = m.inputs_digest(g["intent"]["input_source"], g["resolved_inputs"])
    result.append(("version-source", "GrantV4", g))
    replay = record()
    replay["definition"].update(
        profile_id="tcpreplay-policy",
        protocol="TCP",
        expected_action="ALERT",
        detection_required=True,
        evidence_requirements=[
            "ingress_pcap",
            "egress_pcap",
            "dut_events",
            "service_probe",
            "resource_metrics",
        ],
    )
    replay["definition"]["success_criteria"]["detection_deadline_ms"] = 100
    replay["definition"]["stop_conditions"]["max_cpu_pct"] = 80
    replay["profile_snapshot"] = next(p for p in PROFILES_V1 if p["id"] == "tcpreplay-policy")
    replay["digest"] = record_digest(replay)
    result.append(("replay-null-pcap-with-detection-and-resource-stops", "ScenarioVersion", replay))
    c = call()
    c["started_at"] = "2026-01-01T00:00:00.000001+00:00"
    c["decision"]["accepted_at"] = "2026-01-01T00:00:00.000002Z"
    c["finished_at"] = "2026-01-01T00:00:00.000003Z"
    c["proposal"]["expires_at"] = "2026-01-01T00:00:00.000004Z"
    c["proposal"]["digest"] = m.proposal_digest(c["id"], c["grant_id"], c["proposal"])
    c["decision"]["proposal_digest"] = c["proposal"]["digest"]
    result.append(("microsecond-state-times", "CallV4", c))
    return [
        dict(label=label, name=name, raw=getattr(m, name).model_validate(value).model_dump_json())
        for label, name, value in result
    ]


def examples():
    g, c, r, sn = grant(), call(), record(), snapshots()
    source = g["intent"]["input_source"]
    ref = m.scenario_ref(r)
    context = dict(
        kind="scenario_context",
        scenario_revision=0,
        draft_revision=0,
        operation="scenario_create",
        resolved_inputs=protected(),
        inputs_digest=g["inputs_digest"],
        base=None,
        **{k: sn[k] for k in ("target_snapshot", "sink_snapshot")},
        profiles=[
            next(p for p in PROFILES_V1 if p["id"] == id) for id in ("tcpreplay-policy", "k6-http")
        ],
    )
    summary = {
        **ref,
        **{k: r["definition"][k] for k in ("name", "profile_id", "target_id", "sink_id")},
    }
    listing = dict(
        kind="scenarios",
        scenario_revision=1,
        total=1,
        offset=0,
        limit=10,
        items=[summary],
        next_offset=None,
    )
    decision = c["decision"]
    from tests.chat.test_chat_scenario_models import grant_input

    values = dict(
        Identifier="legacy-scenario",
        ChatID=IDS[0],
        Digest="a" * 64,
        Name="계획 😀",
        Goal="Goal\nline",
        Timestamp=STAMP,
        ChatTime=STAMP,
        UserText="save",
        TrafficBudget=protected()["traffic_budget"],
        StopConditions=protected()["stop_conditions"],
        PcapAsset=dict(label="operator", sha256="a" * 64, size_bytes=1),
        SuccessCriteria=definition()["success_criteria"],
        ProtectedInputs=protected(),
        ModelDefinition=definition(),
        ScenarioDefinition=r["definition"],
        TargetSnapshot=sn["target_snapshot"],
        ProfileSnapshot=sn["profile_snapshot"],
        ScenarioVersion=r,
        ScenarioRef=ref,
        OperatorSource=source,
        VersionSource=dict(source="scenario_version", reference=ref),
        InputSource=source,
        Intent=g["intent"],
        GrantInputV4=grant_input(),
        GrantV4=g,
        RuntimeV4=dict(
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
        ),
        ContextArgs=dict(kind="scenario_context"),
        ListArgs=dict(kind="scenarios", offset=0, limit=10),
        DetailArgs=dict(kind="scenario", **ref),
        ReadArgs=dict(kind="scenario_context"),
        CreateArgs=c["arguments"],
        AppendArgs=call("scenario_append")["arguments"],
        Snapshots=sn,
        ContextResult=context,
        ScenarioSummary=summary,
        ListResult=listing,
        DetailResult=dict(kind="scenario", scenario_revision=1, scenario=r),
        ProposalV4=c["proposal"],
        CreatedResult=c["result"],
        AppendedResult=call("scenario_append")["result"],
        ResultV4=context,
        DecisionInput={k: decision[k] for k in ("request_id", "proposal_digest", "decision")},
        Decision=decision,
        CallV4=c,
        TranscriptV4=dict(schema_version=4, turn_id=IDS[2], revision=1, calls=[c]),
        ScenarioStateInspection=dict(
            schema_version=4, scenario_revision=0, registry_write_status="available"
        ),
        ReconcileInputV4=dict(
            schema_version=4,
            request_id=IDS[0],
            expected_generation=0,
            expected_draft_revision=0,
            expected_scenario_revision=0,
            acknowledge_uncertain=True,
        ),
        ReconcileReceiptV4=dict(
            schema_version=4,
            request_id=IDS[0],
            acknowledged_call_ids=[IDS[4]],
            generation=1,
            write_fenced=False,
            prior_outcomes="remain_uncertain",
            observed_scenario_revision=0,
            scenario_recovery="not_performed",
        ),
        ToolEnvelopeV4=dict(ok=True, result=context, error_code=None),
        ScenarioExpectation=dict(scenario=r, after_scenario_revision=1),
        ScenarioSelection=dict(id=r["id"], version=1, expectation=None),
        ScenarioHistoryV4=history(),
        ScenarioPageV4=page(),
    )
    assert set(values) == set(m.CONTRACT_TYPES)
    return values


if __name__ == "__main__":
    print(
        json.dumps(
            dict(
                origin="model/schema-produced synthetic fixture; not native HTTP capture",
                module=str(Path(m.__file__).resolve()),
                bodies=model_bytes(),
                negatives=negative_bytes(),
                variants=variants(),
            ),
            ensure_ascii=False,
        )
    )
