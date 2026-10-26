import { validAddress } from "../lab/validation";
import { scenarioProfiles } from "../scenarios/catalog";
import { canonical, digest, parseJSON, utf8Length } from "../scenarios/json";
import { timestamp } from "../scenarios/timestamp";
import {
  denseArray,
  exact,
  identifier,
  integer,
  scenarioText,
  sha256,
  validDefinition,
} from "../scenarios/validation";
import type {
  ScenarioHistory,
  ScenarioPage,
  ScenarioVersion,
} from "../scenarios/types";
import type { ContractName, ContractTypes } from "./chat-scenario-types";
import type * as T from "./chat-scenario-types";
import { pythonSpace } from "../ai-settings/unicode-text";

function check(ok: unknown): asserts ok {
  if (!ok) throw new Error("Invalid B3 scenario contract.");
}
function target(value: unknown, id: string, kind: string): boolean {
  return (
    exact(value, ["id", "name", "address", "kind", "status", "created_at"]) &&
    value.id === id &&
    identifier(value.id) &&
    scenarioText(value.name, 120) &&
    typeof value.address === "string" &&
    validAddress(value.address) &&
    value.kind === kind &&
    value.status === "draft" &&
    timestamp(value.created_at)
  );
}
function profile(value: unknown, id: "tcpreplay-policy" | "k6-http"): boolean {
  return (
    exact(value, ["id", "name", "description", "engine", "layer", "status"]) &&
    exact(value.name, ["en", "ko"]) &&
    exact(value.description, ["en", "ko"]) &&
    canonical(value) === canonical(scenarioProfiles[id])
  );
}
/** Identifier-compatible immutable record. Does not call the manual UUID codec. */
async function recordValue(value: unknown): Promise<ScenarioVersion> {
  check(
    exact(value, [
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
    ]),
  );
  check(
    identifier(value.id) &&
      integer(value.version, 1, 10) &&
      timestamp(value.created_at),
  );
  check(
    value.status === "definition" &&
      value.execution_enabled === false &&
      value.catalog_version === "1.0.0",
  );
  check(sha256(value.digest) && validDefinition(value.definition));
  check(
    target(value.target_snapshot, value.definition.target_id, "DUT") &&
      target(value.sink_snapshot, value.definition.sink_id, "SINK"),
  );
  check(profile(value.profile_snapshot, value.definition.profile_id));
  check(utf8Length(canonical(value)) <= 8192);
  const { digest: expected, ...content } = value;
  check((await digest(content)) === expected);
  return value as ScenarioVersion;
}

async function historyValue(
  value: unknown,
  id: string,
): Promise<ScenarioHistory> {
  check(
    identifier(id) &&
      exact(value, [
        "revision",
        "scenario_id",
        "versions",
        "execution_enabled",
      ]),
  );
  check(
    value.scenario_id === id &&
      value.execution_enabled === false &&
      integer(value.revision, 1, 1000),
  );
  check(
    denseArray(value.versions, 1, 10) &&
      value.revision >= value.versions.length,
  );
  for (let i = 0; i < value.versions.length; i++) {
    const record = await recordValue(value.versions[i]);
    check(record.id === id && record.version === i + 1);
  }
  return value as ScenarioHistory;
}

async function pageValue(
  value: unknown,
  offset: number,
  limit: number,
): Promise<ScenarioPage> {
  check(integer(offset, 0, 100) && integer(limit, 1, 100));
  check(
    exact(value, [
      "revision",
      "total",
      "offset",
      "limit",
      "items",
      "execution_enabled",
    ]),
  );
  check(
    value.offset === offset &&
      value.limit === limit &&
      value.execution_enabled === false,
  );
  check(
    integer(value.revision, 0, 1000) &&
      integer(value.total, 0, 100) &&
      denseArray(value.items, 0, 100),
  );
  check(
    value.items.length === Math.max(0, Math.min(limit, value.total - offset)),
  );
  const records = await Promise.all(value.items.map(recordValue));
  check(new Set(records.map((r) => r.id)).size === records.length);
  const count = records.reduce((n, r) => n + r.version, 0),
    outside = value.total - records.length;
  check(value.total <= value.revision && value.revision <= value.total * 10);
  check(
    count + outside <= value.revision && value.revision <= count + outside * 10,
  );
  return value as ScenarioPage;
}

/** Frozen structural vocabulary. Cross-record invariants are not JSON Schema. */
type Shape = {
  $ref?: string;
  type?: string;
  const?: unknown;
  enum?: unknown[];
  oneOf?: Shape[];
  anyOf?: Shape[];
  properties?: Record<string, Shape>;
  required?: string[];
  additionalProperties?: boolean;
  items?: Shape;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
  pattern?: string;
};
const shapes: Record<ContractName, Shape> = {
  Identifier: {
    type: "string",
    minLength: 1,
    maxLength: 64,
    pattern: "^[a-z0-9-]+$",
  },
  ChatID: {
    type: "string",
    pattern:
      "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
  },
  Digest: { type: "string", pattern: "^[0-9a-f]{64}$" },
  Name: { type: "string", minLength: 1, maxLength: 120 },
  Goal: { type: "string", minLength: 1, maxLength: 2000 },
  Timestamp: { type: "string", minLength: 20, maxLength: 40 },
  ChatTime: {
    type: "string",
    maxLength: 40,
    pattern:
      "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?(?:Z|\\+00:00)$",
  },
  UserText: { type: "string", minLength: 1 },
  TrafficBudget: {
    type: "object",
    additionalProperties: false,
    properties: {
      max_pps: { type: "integer", minimum: 1, maximum: 1000000000 },
      max_bps: { type: "integer", minimum: 1, maximum: 1000000000000 },
      max_packets: { type: "integer", minimum: 1, maximum: 1000000000000 },
      max_bytes: { type: "integer", minimum: 1, maximum: 1000000000000 },
      max_connections: { type: "integer", minimum: 1, maximum: 1000000 },
      duration_seconds: { type: "integer", minimum: 1, maximum: 3600 },
    },
    required: [
      "max_pps",
      "max_bps",
      "max_packets",
      "max_bytes",
      "max_connections",
      "duration_seconds",
    ],
  },
  StopConditions: {
    type: "object",
    additionalProperties: false,
    properties: {
      max_legitimate_loss_pct: { type: "integer", minimum: 0, maximum: 100 },
      max_service_latency_ms: { type: "integer", minimum: 1, maximum: 60000 },
      max_cpu_pct: {
        anyOf: [
          { type: "integer", minimum: 1, maximum: 100 },
          { type: "null" },
        ],
      },
      max_memory_pct: {
        anyOf: [
          { type: "integer", minimum: 1, maximum: 100 },
          { type: "null" },
        ],
      },
      max_sessions: {
        anyOf: [
          { type: "integer", minimum: 1, maximum: 1000000 },
          { type: "null" },
        ],
      },
      management_loss: { const: true, type: "boolean" },
    },
    required: [
      "max_legitimate_loss_pct",
      "max_service_latency_ms",
      "max_cpu_pct",
      "max_memory_pct",
      "max_sessions",
      "management_loss",
    ],
  },
  PcapAsset: {
    type: "object",
    additionalProperties: false,
    properties: {
      label: { $ref: "#/$defs/Name" },
      sha256: { $ref: "#/$defs/Digest" },
      size_bytes: { type: "integer", minimum: 1, maximum: 67108864 },
    },
    required: ["label", "sha256", "size_bytes"],
  },
  SuccessCriteria: {
    type: "object",
    additionalProperties: false,
    properties: {
      minimum_delivery_pct: { type: "integer", minimum: 0, maximum: 100 },
      maximum_delivery_pct: { type: "integer", minimum: 0, maximum: 100 },
      detection_deadline_ms: {
        anyOf: [
          { type: "integer", minimum: 1, maximum: 60000 },
          { type: "null" },
        ],
      },
    },
    required: [
      "minimum_delivery_pct",
      "maximum_delivery_pct",
      "detection_deadline_ms",
    ],
  },
  ProtectedInputs: {
    type: "object",
    additionalProperties: false,
    properties: {
      target_id: { $ref: "#/$defs/Identifier" },
      sink_id: { $ref: "#/$defs/Identifier" },
      dut_version: { $ref: "#/$defs/Name" },
      policy_version: { $ref: "#/$defs/Name" },
      pcap_asset: { anyOf: [{ $ref: "#/$defs/PcapAsset" }, { type: "null" }] },
      traffic_budget: { $ref: "#/$defs/TrafficBudget" },
      stop_conditions: { $ref: "#/$defs/StopConditions" },
    },
    required: [
      "target_id",
      "sink_id",
      "dut_version",
      "policy_version",
      "pcap_asset",
      "traffic_budget",
      "stop_conditions",
    ],
  },
  ModelDefinition: {
    type: "object",
    additionalProperties: false,
    properties: {
      name: { $ref: "#/$defs/Name" },
      objective: { $ref: "#/$defs/Goal" },
      profile_id: { type: "string", enum: ["tcpreplay-policy", "k6-http"] },
      protocol: { type: "string", enum: ["TCP", "UDP", "DNS", "HTTP"] },
      ip_version: { type: "integer", enum: [4, 6] },
      expected_action: { type: "string", enum: ["ALLOW", "BLOCK", "ALERT"] },
      delivery_expectation: { type: "string", enum: ["ALLOW", "BLOCK"] },
      detection_required: { type: "boolean" },
      success_criteria: { $ref: "#/$defs/SuccessCriteria" },
      evidence_requirements: {
        type: "array",
        items: {
          type: "string",
          enum: [
            "ingress_pcap",
            "egress_pcap",
            "dut_events",
            "service_probe",
            "resource_metrics",
          ],
        },
        minItems: 1,
        maxItems: 5,
        uniqueItems: true,
      },
    },
    required: [
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
  },
  ScenarioDefinition: {
    type: "object",
    additionalProperties: false,
    properties: {
      name: { $ref: "#/$defs/Name" },
      objective: { $ref: "#/$defs/Goal" },
      profile_id: { type: "string", enum: ["tcpreplay-policy", "k6-http"] },
      protocol: { type: "string", enum: ["TCP", "UDP", "DNS", "HTTP"] },
      ip_version: { type: "integer", enum: [4, 6] },
      expected_action: { type: "string", enum: ["ALLOW", "BLOCK", "ALERT"] },
      delivery_expectation: { type: "string", enum: ["ALLOW", "BLOCK"] },
      detection_required: { type: "boolean" },
      success_criteria: { $ref: "#/$defs/SuccessCriteria" },
      evidence_requirements: {
        type: "array",
        items: {
          type: "string",
          enum: [
            "ingress_pcap",
            "egress_pcap",
            "dut_events",
            "service_probe",
            "resource_metrics",
          ],
        },
        minItems: 1,
        maxItems: 5,
        uniqueItems: true,
      },
      target_id: { $ref: "#/$defs/Identifier" },
      sink_id: { $ref: "#/$defs/Identifier" },
      dut_version: { $ref: "#/$defs/Name" },
      policy_version: { $ref: "#/$defs/Name" },
      pcap_asset: { anyOf: [{ $ref: "#/$defs/PcapAsset" }, { type: "null" }] },
      traffic_budget: { $ref: "#/$defs/TrafficBudget" },
      stop_conditions: { $ref: "#/$defs/StopConditions" },
    },
    required: [
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
  },
  TargetSnapshot: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/Identifier" },
      name: { $ref: "#/$defs/Name" },
      address: { type: "string", minLength: 1, maxLength: 255 },
      kind: { type: "string", enum: ["DUT", "SINK"] },
      status: { const: "draft", type: "string" },
      created_at: { $ref: "#/$defs/Timestamp" },
    },
    required: ["id", "name", "address", "kind", "status", "created_at"],
  },
  ProfileSnapshot: {
    oneOf: [
      {
        const: {
          id: "tcpreplay-policy",
          name: { en: "Packet replay policy check", ko: "패킷 재생 정책 점검" },
          description: {
            en: "Planning template: operator-owned capture, isolated DUT/SINK, bounded rate and duration, explicit stop/rollback criteria. No capture loaded or packets emitted.",
            ko: "계획 템플릿: 운영자 소유 캡처, 격리된 DUT/SINK, 속도·시간 제한 및 명시적 중지·복구 기준이 필요합니다. 캡처를 로드하거나 패킷을 전송하지 않습니다.",
          },
          engine: "tcpreplay",
          layer: "L2–L4",
          status: "template",
        },
        type: "object",
      },
      {
        const: {
          id: "k6-http",
          name: { en: "HTTP policy scenario", ko: "HTTP 정책 시나리오" },
          description: {
            en: "Planning template: approved lab HTTP service, bounded users/request rate/duration, expected responses and abort criteria. No script executed or HTTP request sent.",
            ko: "계획 템플릿: 승인된 실험실 HTTP 서비스, 사용자·요청 속도·시간 상한, 예상 응답과 중단 기준이 필요합니다. 스크립트를 실행하거나 HTTP 요청을 보내지 않습니다.",
          },
          engine: "k6",
          layer: "L7",
          status: "template",
        },
        type: "object",
      },
    ],
  },
  ScenarioVersion: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/Identifier" },
      version: { type: "integer", minimum: 1, maximum: 10 },
      created_at: { $ref: "#/$defs/Timestamp" },
      status: { const: "definition", type: "string" },
      execution_enabled: { const: false, type: "boolean" },
      definition: { $ref: "#/$defs/ScenarioDefinition" },
      target_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      sink_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      profile_snapshot: { $ref: "#/$defs/ProfileSnapshot" },
      catalog_version: { const: "1.0.0", type: "string" },
      digest: { $ref: "#/$defs/Digest" },
    },
    required: [
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
  },
  ScenarioRef: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/Identifier" },
      version: { type: "integer", minimum: 1, maximum: 10 },
      digest: { $ref: "#/$defs/Digest" },
    },
    required: ["id", "version", "digest"],
  },
  OperatorSource: {
    type: "object",
    additionalProperties: false,
    properties: {
      source: { const: "operator", type: "string" },
      inputs: { $ref: "#/$defs/ProtectedInputs" },
    },
    required: ["source", "inputs"],
  },
  VersionSource: {
    type: "object",
    additionalProperties: false,
    properties: {
      source: { const: "scenario_version", type: "string" },
      reference: { $ref: "#/$defs/ScenarioRef" },
    },
    required: ["source", "reference"],
  },
  InputSource: {
    oneOf: [
      { $ref: "#/$defs/OperatorSource" },
      { $ref: "#/$defs/VersionSource" },
    ],
  },
  Intent: {
    type: "object",
    additionalProperties: false,
    properties: {
      operation: {
        type: "string",
        enum: ["scenario_create", "scenario_append"],
      },
      expected_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      expected_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      base: { anyOf: [{ $ref: "#/$defs/ScenarioRef" }, { type: "null" }] },
      input_source: { $ref: "#/$defs/InputSource" },
    },
    required: [
      "operation",
      "expected_scenario_revision",
      "expected_draft_revision",
      "base",
      "input_source",
    ],
  },
  GrantInputV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      scope: { const: "scenario_write", type: "string" },
      request_id: { $ref: "#/$defs/ChatID" },
      session_id: { $ref: "#/$defs/ChatID" },
      turn_request_id: { $ref: "#/$defs/ChatID" },
      expected_sequence: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      text: { $ref: "#/$defs/UserText" },
      intent: { $ref: "#/$defs/Intent" },
    },
    required: [
      "schema_version",
      "scope",
      "request_id",
      "session_id",
      "turn_request_id",
      "expected_sequence",
      "text",
      "intent",
    ],
  },
  GrantV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      id: { $ref: "#/$defs/ChatID" },
      request_id: { $ref: "#/$defs/ChatID" },
      session_id: { $ref: "#/$defs/ChatID" },
      turn_request_id: { $ref: "#/$defs/ChatID" },
      expected_sequence: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      text_sha256: { $ref: "#/$defs/Digest" },
      settings_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      profile_id: { type: "string", pattern: "^[a-z][a-z0-9_-]{0,63}$" },
      created_at: { $ref: "#/$defs/ChatTime" },
      expires_at: { $ref: "#/$defs/ChatTime" },
      status: {
        type: "string",
        enum: ["pending", "consumed", "revoked", "expired"],
      },
      scope: { const: "scenario_write", type: "string" },
      read_scope: {
        const: ["scenario_context", "scenarios", "scenario"],
        type: "array",
      },
      proposal_tools: {
        type: "array",
        items: { type: "string", enum: ["scenario_create", "scenario_append"] },
        minItems: 1,
        maxItems: 1,
      },
      intent: { $ref: "#/$defs/Intent" },
      resolved_inputs: { $ref: "#/$defs/ProtectedInputs" },
      inputs_digest: { $ref: "#/$defs/Digest" },
    },
    required: [
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
  },
  RuntimeV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      mode: { const: "operator_approved_settings", type: "string" },
      supported: { type: "boolean" },
      reason: {
        anyOf: [
          {
            type: "string",
            enum: [
              "CHAT_NOT_CONFIGURED",
              "CHAT_UNSUPPORTED_PROFILE",
              "CHAT_UNSUPPORTED_OPTIONS",
            ],
          },
          { type: "null" },
        ],
      },
      tools: {
        const: [
          "configuration_read",
          "agent_profile_update",
          "target_create",
          "skill_create",
          "scenario_create",
          "scenario_append",
        ],
        type: "array",
      },
      max_calls: { const: 3, type: "integer" },
      max_writes: { const: 1, type: "integer" },
      requires_write_approval: { const: true, type: "boolean" },
    },
    required: [
      "schema_version",
      "mode",
      "supported",
      "reason",
      "tools",
      "max_calls",
      "max_writes",
      "requires_write_approval",
    ],
  },
  ContextArgs: {
    type: "object",
    additionalProperties: false,
    properties: { kind: { const: "scenario_context", type: "string" } },
    required: ["kind"],
  },
  ListArgs: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenarios", type: "string" },
      offset: { type: "integer", minimum: 0, maximum: 100 },
      limit: { type: "integer", minimum: 1, maximum: 10 },
    },
    required: ["kind", "offset", "limit"],
  },
  DetailArgs: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenario", type: "string" },
      id: { $ref: "#/$defs/Identifier" },
      version: { type: "integer", minimum: 1, maximum: 10 },
      digest: { $ref: "#/$defs/Digest" },
    },
    required: ["kind", "id", "version", "digest"],
  },
  ReadArgs: {
    oneOf: [
      { $ref: "#/$defs/ContextArgs" },
      { $ref: "#/$defs/ListArgs" },
      { $ref: "#/$defs/DetailArgs" },
    ],
  },
  CreateArgs: {
    type: "object",
    additionalProperties: false,
    properties: {
      expected_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      expected_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      definition: { $ref: "#/$defs/ModelDefinition" },
    },
    required: [
      "expected_scenario_revision",
      "expected_draft_revision",
      "definition",
    ],
  },
  AppendArgs: {
    type: "object",
    additionalProperties: false,
    properties: {
      expected_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      expected_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      definition: { $ref: "#/$defs/ModelDefinition" },
      base: { $ref: "#/$defs/ScenarioRef" },
    },
    required: [
      "expected_scenario_revision",
      "expected_draft_revision",
      "definition",
      "base",
    ],
  },
  Snapshots: {
    type: "object",
    additionalProperties: false,
    properties: {
      target_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      sink_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      profile_snapshot: { $ref: "#/$defs/ProfileSnapshot" },
      catalog_version: { const: "1.0.0", type: "string" },
    },
    required: [
      "target_snapshot",
      "sink_snapshot",
      "profile_snapshot",
      "catalog_version",
    ],
  },
  ContextResult: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenario_context", type: "string" },
      scenario_revision: { type: "integer", minimum: 0, maximum: 1000 },
      draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      operation: {
        type: "string",
        enum: ["scenario_create", "scenario_append"],
      },
      resolved_inputs: { $ref: "#/$defs/ProtectedInputs" },
      inputs_digest: { $ref: "#/$defs/Digest" },
      target_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      sink_snapshot: { $ref: "#/$defs/TargetSnapshot" },
      profiles: {
        type: "array",
        items: { $ref: "#/$defs/ProfileSnapshot" },
        minItems: 2,
        maxItems: 2,
      },
      base: { anyOf: [{ $ref: "#/$defs/ScenarioVersion" }, { type: "null" }] },
    },
    required: [
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
  },
  ScenarioSummary: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/Identifier" },
      version: { type: "integer", minimum: 1, maximum: 10 },
      digest: { $ref: "#/$defs/Digest" },
      name: { $ref: "#/$defs/Name" },
      profile_id: { type: "string", enum: ["tcpreplay-policy", "k6-http"] },
      target_id: { $ref: "#/$defs/Identifier" },
      sink_id: { $ref: "#/$defs/Identifier" },
    },
    required: [
      "id",
      "version",
      "digest",
      "name",
      "profile_id",
      "target_id",
      "sink_id",
    ],
  },
  ListResult: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenarios", type: "string" },
      scenario_revision: { type: "integer", minimum: 0, maximum: 1000 },
      total: { type: "integer", minimum: 0, maximum: 100 },
      offset: { type: "integer", minimum: 0, maximum: 100 },
      limit: { type: "integer", minimum: 1, maximum: 10 },
      items: {
        type: "array",
        items: { $ref: "#/$defs/ScenarioSummary" },
        minItems: 0,
        maxItems: 10,
      },
      next_offset: {
        anyOf: [{ type: "integer", minimum: 1, maximum: 99 }, { type: "null" }],
      },
    },
    required: [
      "kind",
      "scenario_revision",
      "total",
      "offset",
      "limit",
      "items",
      "next_offset",
    ],
  },
  DetailResult: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenario", type: "string" },
      scenario_revision: { type: "integer", minimum: 1, maximum: 1000 },
      scenario: { $ref: "#/$defs/ScenarioVersion" },
    },
    required: ["kind", "scenario_revision", "scenario"],
  },
  ProposalV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      operation: {
        type: "string",
        enum: ["scenario_create", "scenario_append"],
      },
      digest: { $ref: "#/$defs/Digest" },
      expected_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      expected_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      before: {
        anyOf: [{ $ref: "#/$defs/ScenarioVersion" }, { type: "null" }],
      },
      after: { $ref: "#/$defs/ScenarioDefinition" },
      snapshots: { $ref: "#/$defs/Snapshots" },
      input_source: { $ref: "#/$defs/InputSource" },
      inputs_digest: { $ref: "#/$defs/Digest" },
      expires_at: { $ref: "#/$defs/ChatTime" },
    },
    required: [
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
  },
  CreatedResult: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenario_created", type: "string" },
      before_scenario_revision: { type: "integer", minimum: 0, maximum: 999 },
      after_scenario_revision: { type: "integer", minimum: 1, maximum: 1000 },
      source_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      scenario: { $ref: "#/$defs/ScenarioVersion" },
      execution_enabled: { const: false, type: "boolean" },
    },
    required: [
      "kind",
      "before_scenario_revision",
      "after_scenario_revision",
      "source_draft_revision",
      "scenario",
      "execution_enabled",
    ],
  },
  AppendedResult: {
    type: "object",
    additionalProperties: false,
    properties: {
      kind: { const: "scenario_appended", type: "string" },
      before_scenario_revision: { type: "integer", minimum: 0, maximum: 999 },
      after_scenario_revision: { type: "integer", minimum: 1, maximum: 1000 },
      source_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      scenario: { $ref: "#/$defs/ScenarioVersion" },
      execution_enabled: { const: false, type: "boolean" },
    },
    required: [
      "kind",
      "before_scenario_revision",
      "after_scenario_revision",
      "source_draft_revision",
      "scenario",
      "execution_enabled",
    ],
  },
  ResultV4: {
    oneOf: [
      { $ref: "#/$defs/ContextResult" },
      { $ref: "#/$defs/ListResult" },
      { $ref: "#/$defs/DetailResult" },
      { $ref: "#/$defs/CreatedResult" },
      { $ref: "#/$defs/AppendedResult" },
    ],
  },
  DecisionInput: {
    type: "object",
    additionalProperties: false,
    properties: {
      request_id: { $ref: "#/$defs/ChatID" },
      proposal_digest: { $ref: "#/$defs/Digest" },
      decision: { type: "string", enum: ["approve", "deny"] },
    },
    required: ["request_id", "proposal_digest", "decision"],
  },
  Decision: {
    type: "object",
    additionalProperties: false,
    properties: {
      request_id: { $ref: "#/$defs/ChatID" },
      proposal_digest: { $ref: "#/$defs/Digest" },
      decision: { type: "string", enum: ["approve", "deny"] },
      schema_version: { const: 1, type: "integer" },
      call_id: { $ref: "#/$defs/ChatID" },
      accepted_at: { $ref: "#/$defs/ChatTime" },
    },
    required: [
      "request_id",
      "proposal_digest",
      "decision",
      "schema_version",
      "call_id",
      "accepted_at",
    ],
  },
  CallV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/ChatID" },
      index: { type: "integer", minimum: 0, maximum: 2 },
      provider_call_id: {
        type: "string",
        minLength: 1,
        maxLength: 128,
        pattern: "^[\\x00-\\x7f]+$",
      },
      tool: {
        type: "string",
        enum: ["configuration_read", "scenario_create", "scenario_append"],
      },
      arguments: {
        oneOf: [
          { $ref: "#/$defs/ContextArgs" },
          { $ref: "#/$defs/ListArgs" },
          { $ref: "#/$defs/DetailArgs" },
          { $ref: "#/$defs/CreateArgs" },
          { $ref: "#/$defs/AppendArgs" },
        ],
      },
      args_digest: { $ref: "#/$defs/Digest" },
      grant_id: { $ref: "#/$defs/ChatID" },
      actor: { const: "operator_authorized_model", type: "string" },
      status: {
        type: "string",
        enum: [
          "requested",
          "awaiting_approval",
          "executing",
          "succeeded",
          "denied",
          "conflict",
          "failed",
          "uncertain",
          "cancelled",
        ],
      },
      error_code: {
        anyOf: [
          {
            type: "string",
            enum: [
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
            ],
          },
          { type: "null" },
        ],
      },
      proposal: { anyOf: [{ $ref: "#/$defs/ProposalV4" }, { type: "null" }] },
      decision: { anyOf: [{ $ref: "#/$defs/Decision" }, { type: "null" }] },
      result: { anyOf: [{ $ref: "#/$defs/ResultV4" }, { type: "null" }] },
      started_at: { $ref: "#/$defs/ChatTime" },
      finished_at: { anyOf: [{ $ref: "#/$defs/ChatTime" }, { type: "null" }] },
    },
    required: [
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
  },
  TranscriptV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      turn_id: { $ref: "#/$defs/ChatID" },
      revision: { type: "integer", minimum: 0, maximum: 9007199254740991 },
      calls: {
        type: "array",
        items: { $ref: "#/$defs/CallV4" },
        minItems: 0,
        maxItems: 3,
      },
    },
    required: ["schema_version", "turn_id", "revision", "calls"],
  },
  ScenarioStateInspection: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      scenario_revision: { type: "integer", minimum: 0, maximum: 1000 },
      registry_write_status: {
        type: "string",
        enum: ["available", "quarantined"],
      },
    },
    required: ["schema_version", "scenario_revision", "registry_write_status"],
  },
  ReconcileInputV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      request_id: { $ref: "#/$defs/ChatID" },
      expected_generation: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      expected_draft_revision: {
        type: "integer",
        minimum: 0,
        maximum: 9007199254740991,
      },
      expected_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      acknowledge_uncertain: { const: true, type: "boolean" },
    },
    required: [
      "schema_version",
      "request_id",
      "expected_generation",
      "expected_draft_revision",
      "expected_scenario_revision",
      "acknowledge_uncertain",
    ],
  },
  ReconcileReceiptV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      schema_version: { const: 4, type: "integer" },
      request_id: { $ref: "#/$defs/ChatID" },
      acknowledged_call_ids: {
        type: "array",
        items: { $ref: "#/$defs/ChatID" },
        minItems: 1,
        maxItems: 1,
      },
      generation: { type: "integer", minimum: 0, maximum: 9007199254740991 },
      write_fenced: { const: false, type: "boolean" },
      prior_outcomes: { const: "remain_uncertain", type: "string" },
      observed_scenario_revision: {
        type: "integer",
        minimum: 0,
        maximum: 1000,
      },
      scenario_recovery: { const: "not_performed", type: "string" },
    },
    required: [
      "schema_version",
      "request_id",
      "acknowledged_call_ids",
      "generation",
      "write_fenced",
      "prior_outcomes",
      "observed_scenario_revision",
      "scenario_recovery",
    ],
  },
  ToolEnvelopeV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      ok: { type: "boolean" },
      result: { anyOf: [{ $ref: "#/$defs/ResultV4" }, { type: "null" }] },
      error_code: {
        anyOf: [
          {
            type: "string",
            enum: [
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
            ],
          },
          { type: "null" },
        ],
      },
    },
    required: ["ok", "result", "error_code"],
  },
  ScenarioExpectation: {
    type: "object",
    additionalProperties: false,
    properties: {
      scenario: { $ref: "#/$defs/ScenarioVersion" },
      after_scenario_revision: { type: "integer", minimum: 1, maximum: 1000 },
    },
    required: ["scenario", "after_scenario_revision"],
  },
  ScenarioSelection: {
    type: "object",
    additionalProperties: false,
    properties: {
      id: { $ref: "#/$defs/Identifier" },
      version: { type: "integer", minimum: 1, maximum: 10 },
      expectation: {
        anyOf: [{ $ref: "#/$defs/ScenarioExpectation" }, { type: "null" }],
      },
    },
    required: ["id", "version", "expectation"],
  },
  ScenarioHistoryV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      revision: { type: "integer", minimum: 1, maximum: 1000 },
      scenario_id: { $ref: "#/$defs/Identifier" },
      versions: {
        type: "array",
        items: { $ref: "#/$defs/ScenarioVersion" },
        minItems: 1,
        maxItems: 10,
      },
      execution_enabled: { type: "boolean", const: false },
    },
    required: ["revision", "scenario_id", "versions", "execution_enabled"],
  },
  ScenarioPageV4: {
    type: "object",
    additionalProperties: false,
    properties: {
      revision: { type: "integer", minimum: 0, maximum: 1000 },
      total: { type: "integer", minimum: 0, maximum: 100 },
      offset: { type: "integer", minimum: 0, maximum: 100 },
      limit: { type: "integer", minimum: 1, maximum: 100 },
      items: {
        type: "array",
        items: { $ref: "#/$defs/ScenarioVersion" },
        minItems: 0,
        maxItems: 100,
      },
      execution_enabled: { type: "boolean", const: false },
    },
    required: [
      "revision",
      "total",
      "offset",
      "limit",
      "items",
      "execution_enabled",
    ],
  },
};

function scalarString(value: string): void {
  check(
    !Array.from(value).some((c) => {
      const n = c.codePointAt(0)!;
      return n >= 0xd800 && n <= 0xdfff;
    }),
  );
}
/** Snapshot direct inputs before async digest work; never invoke accessors. */
function capture(value: unknown, depth = 0): unknown {
  if (typeof value === "string") {
    scalarString(value);
    return value;
  }
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") {
    check(Number.isSafeInteger(value));
    return value;
  }
  check(depth < 32);
  if (Array.isArray(value)) {
    check(denseArray(value, 0, 1048576));
    return value.map((v) => capture(v, depth + 1));
  }
  check(value !== null && typeof value === "object");
  const keys = Object.keys(value);
  check(exact(value, keys));
  const result: Record<string, unknown> = Object.create(null);
  for (const key of keys) {
    scalarString(key);
    result[key] = capture(value[key], depth + 1);
  }
  return result;
}
function shape(node: Shape, value: unknown): void {
  if (node.$ref) {
    namedShape(node.$ref.split("/").at(-1)! as ContractName, value);
    return;
  }
  const choices = node.oneOf ?? node.anyOf;
  if (choices) {
    let matches = 0;
    for (const choice of choices) {
      try {
        shape(choice, value);
        matches++;
      } catch {
        /* distinct closed branch */
      }
    }
    check(node.oneOf ? matches === 1 : matches > 0);
    return;
  }
  if (Object.hasOwn(node, "const"))
    check(canonical(value) === canonical(node.const));
  if (node.enum) check(node.enum.includes(value));
  switch (node.type) {
    case "null":
      check(value === null);
      break;
    case "boolean":
      check(typeof value === "boolean");
      break;
    case "integer":
      check(
        integer(
          value,
          node.minimum ?? -Number.MAX_SAFE_INTEGER,
          node.maximum ?? Number.MAX_SAFE_INTEGER,
        ),
      );
      break;
    case "string": {
      check(typeof value === "string");
      const length = Array.from(value).length;
      check(
        length >= (node.minLength ?? 0) &&
          length <= (node.maxLength ?? Infinity),
      );
      if (node.pattern)
        check(
          new RegExp(node.pattern.replace(/\$$/, "(?![\\s\\S])")).test(value),
        );
      break;
    }
    case "array":
      check(denseArray(value, node.minItems ?? 0, node.maxItems ?? 1048576));
      if (node.uniqueItems)
        check(new Set(value.map(canonical)).size === value.length);
      if (node.items) for (const item of value) shape(node.items, item);
      break;
    case "object":
      if (node.properties) {
        check(exact(value, Object.keys(node.properties)));
        for (const [key, property] of Object.entries(node.properties))
          shape(property, value[key]);
      }
      break;
    default:
      check(false);
  }
}
function namedShape(name: ContractName, value: unknown): void {
  check(Object.hasOwn(shapes, name));
  shape(shapes[name], value);
  if (name === "Name" || name === "Goal")
    check(scenarioText(value, name === "Name" ? 120 : 2000, name === "Goal"));
  if (name === "Timestamp" || name === "ChatTime") check(timestamp(value));
  if (name === "UserText") {
    check(
      typeof value === "string" &&
        !value.includes("\0") &&
        utf8Length(value) <= 8192 &&
        Array.from(value).some((c) => !pythonSpace(c)),
    );
  }
}
const rawLimits: Partial<Record<ContractName, number>> = {
  ScenarioHistoryV4: 262144,
  ScenarioPageV4: 1048576,
  TranscriptV4: 1048576,
  CallV4: 262144,
  CreateArgs: 16384,
  AppendArgs: 16384,
  ReadArgs: 16384,
};
export async function parseV4<K extends ContractName>(
  name: K,
  value: unknown,
): Promise<ContractTypes[K]> {
  const snapshot = capture(value);
  namedShape(name, snapshot);
  await walk(shapes[name], snapshot);
  await semantic(name, snapshot);
  return snapshot as ContractTypes[K];
}
/** Raw bytes retain integer-token and duplicate-key evidence lost by JSON.parse. */
export async function parseV4JSON<K extends ContractName>(
  name: K,
  raw: string | Uint8Array,
): Promise<ContractTypes[K]> {
  const limit = rawLimits[name] ?? 32768;
  check((typeof raw === "string" ? utf8Length(raw) : raw.byteLength) <= limit);
  const text =
    typeof raw === "string"
      ? raw
      : new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw);
  scalarString(text);
  return parseV4(name, parseJSON(text));
}

const same = (a: unknown, b: unknown) => canonical(a) === canonical(b);
const ref = (record: T.ScenarioVersion): T.ScenarioRef => ({
  id: record.id,
  version: record.version,
  digest: record.digest,
});
const micros = (stamp: string): bigint => {
  const fraction = /\.(\d{1,6})/.exec(stamp)?.[1] ?? "";
  return (
    BigInt(Date.parse(stamp.slice(0, 19) + "Z")) * 1000n +
    BigInt(fraction.padEnd(6, "0"))
  );
};
export function protectedProjection(
  v: T.ScenarioDefinition,
): T.ProtectedInputs {
  const {
    target_id,
    sink_id,
    dut_version,
    policy_version,
    pcap_asset,
    traffic_budget,
    stop_conditions,
  } = v;
  return {
    target_id,
    sink_id,
    dut_version,
    policy_version,
    pcap_asset,
    traffic_budget,
    stop_conditions,
  };
}
function modelProjection(v: T.ScenarioDefinition): T.ModelDefinition {
  return Object.fromEntries(
    Object.entries(v).filter(
      ([k]) => !Object.hasOwn(shapes.ProtectedInputs.properties!, k),
    ),
  ) as T.ModelDefinition;
}
export const inputsDigest = (
  input_source: T.InputSource,
  resolved_inputs: T.ProtectedInputs,
): Promise<string> => digest({ input_source, resolved_inputs });
export function proposalDigest(
  call_id: string,
  grant_id: string,
  proposal: T.ProposalV4,
): Promise<string> {
  const content = Object.fromEntries(
    Object.entries(proposal).filter(([k]) => k !== "digest"),
  );
  return digest({ call_id, grant_id, ...content });
}
function snapshotsMatch(d: T.ScenarioDefinition, s: T.Snapshots): void {
  check(
    target(s.target_snapshot, d.target_id, "DUT") &&
      target(s.sink_snapshot, d.sink_id, "SINK"),
  );
  check(d.target_id !== d.sink_id && profile(s.profile_snapshot, d.profile_id));
}
async function walk(node: Shape, value: unknown): Promise<void> {
  if (node.$ref) {
    const name = node.$ref.split("/").at(-1)! as ContractName;
    await walk(shapes[name], value);
    await semantic(name, value);
  } else if (node.oneOf || node.anyOf) {
    const branches = node.oneOf ?? node.anyOf!;
    for (const branch of branches) {
      let matches = true;
      try {
        shape(branch, value);
      } catch {
        matches = false;
      }
      if (matches) {
        await walk(branch, value);
        return;
      }
    }
    check(false);
  } else if (node.properties) {
    for (const [key, property] of Object.entries(node.properties))
      await walk(property, (value as Record<string, unknown>)[key]);
  } else if (node.items) {
    for (const item of value as unknown[]) await walk(node.items, item);
  }
}
function pageCounts(v: T.ListResult | T.ScenarioPageV4): void {
  const revision = "revision" in v ? v.revision : v.scenario_revision;
  check(v.items.length === Math.max(0, Math.min(v.limit, v.total - v.offset)));
  check(new Set(v.items.map((r) => r.id)).size === v.items.length);
  const count = v.items.reduce((n, r) => n + r.version, 0),
    outside = v.total - v.items.length;
  check(v.total <= revision && revision <= v.total * 10);
  check(count + outside <= revision && revision <= count + outside * 10);
}
const canonicalLimits: Partial<Record<ContractName, number>> = {
  GrantV4: 8192,
  ScenarioVersion: 8192,
  ResultV4: 32768,
  ContextResult: 32768,
  ListResult: 32768,
  DetailResult: 32768,
  CreatedResult: 32768,
  AppendedResult: 32768,
  ScenarioExpectation: 32768,
  ScenarioStateInspection: 32768,
  CallV4: 262144,
  TranscriptV4: 1048576,
};
/** Internal consistency only. No client cache or fabricated retained grant. */
async function semantic(name: ContractName, value: unknown): Promise<void> {
  if (canonicalLimits[name] !== undefined)
    check(utf8Length(canonical(value)) <= canonicalLimits[name]!);
  switch (name) {
    case "TargetSnapshot":
      check(validAddress((value as T.TargetSnapshot).address));
      break;
    case "ProtectedInputs": {
      const v = value as T.ProtectedInputs;
      check(v.target_id !== v.sink_id);
      break;
    }
    case "ScenarioDefinition":
      check(validDefinition(value));
      break;
    case "ScenarioVersion":
      await recordValue(value);
      break;
    case "ScenarioHistoryV4":
      await historyValue(value, (value as T.ScenarioHistoryV4).scenario_id);
      break;
    case "ScenarioPageV4": {
      const v = value as T.ScenarioPageV4;
      await pageValue(v, v.offset, v.limit);
      break;
    }
    case "Intent": {
      const v = value as T.Intent;
      check((v.operation === "scenario_create") === (v.base === null));
      if (v.base) check(v.base.version <= 9);
      break;
    }
    case "GrantV4": {
      const v = value as T.GrantV4;
      check(same(v.proposal_tools, [v.intent.operation]));
      check(micros(v.expires_at) - micros(v.created_at) === 300000000n);
      if (v.intent.input_source.source === "operator")
        check(same(v.intent.input_source.inputs, v.resolved_inputs));
      check(
        v.inputs_digest ===
          (await inputsDigest(v.intent.input_source, v.resolved_inputs)),
      );
      break;
    }
    case "RuntimeV4": {
      const v = value as T.RuntimeV4;
      check(v.supported === (v.reason === null));
      break;
    }
    case "ContextResult": {
      const v = value as T.ContextResult;
      check(
        same(
          v.profiles.map((p) => p.id),
          ["tcpreplay-policy", "k6-http"],
        ),
      );
      check((v.operation === "scenario_create") === (v.base === null));
      if (v.base)
        check(v.base.version <= 9 && v.scenario_revision >= v.base.version);
      check(
        target(v.target_snapshot, v.resolved_inputs.target_id, "DUT") &&
          target(v.sink_snapshot, v.resolved_inputs.sink_id, "SINK"),
      );
      break;
    }
    case "ListResult": {
      const v = value as T.ListResult;
      pageCounts(v);
      const end = v.offset + v.items.length;
      check(v.next_offset === (end < v.total ? end : null));
      break;
    }
    case "DetailResult": {
      const v = value as T.DetailResult;
      check(v.scenario_revision >= v.scenario.version);
      break;
    }
    case "ProposalV4": {
      const v = value as T.ProposalV4;
      check((v.operation === "scenario_create") === (v.before === null));
      if (v.before)
        check(
          v.before.version <= 9 &&
            v.expected_scenario_revision >= v.before.version,
        );
      snapshotsMatch(v.after, v.snapshots);
      const projected = protectedProjection(v.after);
      if (v.input_source.source === "operator")
        check(same(v.input_source.inputs, projected));
      check(
        v.inputs_digest === (await inputsDigest(v.input_source, projected)),
      );
      break;
    }
    case "CreatedResult":
    case "AppendedResult": {
      const v = value as T.CreatedResult | T.AppendedResult;
      check(
        v.after_scenario_revision === v.before_scenario_revision + 1 &&
          v.after_scenario_revision >= v.scenario.version,
      );
      if (v.kind === "scenario_created") {
        namedShape("ChatID", v.scenario.id);
        check(v.scenario.version === 1);
      } else check(v.scenario.version >= 2);
      break;
    }
    case "CallV4":
      await callConsistency(value as T.CallV4);
      break;
    case "TranscriptV4": {
      const v = value as T.TranscriptV4;
      check(v.calls.every((c, i) => c.index === i));
      check(new Set(v.calls.map((c) => c.id)).size === v.calls.length);
      check(
        new Set(v.calls.map((c) => c.provider_call_id)).size === v.calls.length,
      );
      check(new Set(v.calls.map((c) => c.grant_id)).size <= 1);
      check(v.calls.filter((c) => c.tool !== "configuration_read").length <= 1);
      break;
    }
    case "ToolEnvelopeV4": {
      const v = value as T.ToolEnvelopeV4;
      check(
        v.ok
          ? v.result !== null && v.error_code === null
          : v.result === null && v.error_code !== null,
      );
      break;
    }
    case "ScenarioExpectation": {
      const v = value as T.ScenarioExpectation;
      check(v.after_scenario_revision >= v.scenario.version);
      break;
    }
    case "ScenarioSelection": {
      const v = value as T.ScenarioSelection;
      if (v.expectation)
        check(
          v.id === v.expectation.scenario.id &&
            v.version === v.expectation.scenario.version,
        );
      break;
    }
  }
}
const terminalCodes: Record<string, readonly string[]> = {
  denied: [
    "CHAT_TOOL_DENIED",
    "CHAT_TOOL_WRITE_FENCED",
    "CHAT_SCENARIO_WRITE_FENCED",
  ],
  conflict: ["CHAT_TOOL_CONFLICT"],
  failed: [
    "CHAT_TIMEOUT",
    "CHAT_INVALID_REQUEST",
    "CHAT_NOT_FOUND",
    "CHAT_TOOL_LIMIT",
    "CHAT_STORAGE_ERROR",
  ],
  uncertain: ["CHAT_TOOL_UNCERTAIN"],
  cancelled: ["CHAT_CANCELLED"],
};
async function callConsistency(c: T.CallV4): Promise<void> {
  const { status, result, proposal: p, decision } = c;
  const argName =
    c.tool === "configuration_read"
      ? "ReadArgs"
      : c.tool === "scenario_create"
        ? "CreateArgs"
        : "AppendArgs";
  namedShape(argName, c.arguments);
  check(c.args_digest === (await digest(c.arguments)));
  const terminal =
    status === "succeeded" || Object.hasOwn(terminalCodes, status);
  if (!terminal)
    check(result === null && c.error_code === null && c.finished_at === null);
  else {
    check(
      c.finished_at !== null && micros(c.finished_at) >= micros(c.started_at),
    );
    if (status === "succeeded") {
      check(result !== null && c.error_code === null);
      const expected =
        c.tool === "configuration_read"
          ? (c.arguments as T.ReadArgs).kind
          : c.tool === "scenario_create"
            ? "scenario_created"
            : "scenario_appended";
      check(result.kind === expected);
    } else
      check(
        result === null &&
          c.error_code !== null &&
          terminalCodes[status].includes(c.error_code),
      );
  }
  if (c.error_code === "CHAT_TOOL_DENIED") check(decision?.decision === "deny");
  if (c.tool === "configuration_read") {
    check(
      p === null &&
        decision === null &&
        status !== "awaiting_approval" &&
        status !== "uncertain",
    );
    const a = c.arguments as T.ReadArgs;
    if (result && a.kind === "scenario")
      check(
        result.kind === "scenario" &&
          same(ref(result.scenario), {
            id: a.id,
            version: a.version,
            digest: a.digest,
          }),
      );
    if (result && a.kind === "scenarios")
      check(
        result.kind === "scenarios" &&
          result.offset === a.offset &&
          result.limit === a.limit,
      );
    return;
  }
  const a = c.arguments as T.CreateArgs | T.AppendArgs;
  if (status === "requested") check(p === null);
  if (p) {
    check(
      p.operation === c.tool &&
        p.digest === (await proposalDigest(c.id, c.grant_id, p)),
    );
    check(
      p.expected_scenario_revision === a.expected_scenario_revision &&
        p.expected_draft_revision === a.expected_draft_revision,
    );
    check(same(modelProjection(p.after), a.definition));
    if (c.tool === "scenario_append")
      check(p.before !== null && "base" in a && same(ref(p.before), a.base));
  }
  if (status === "awaiting_approval") check(p !== null && decision === null);
  if (["executing", "succeeded", "uncertain"].includes(status))
    check(p !== null && decision?.decision === "approve");
  if (decision) {
    check(
      p !== null &&
        decision.call_id === c.id &&
        decision.proposal_digest === p.digest,
    );
    check(status !== "requested" && status !== "awaiting_approval");
    if (decision.decision === "deny")
      check(status === "denied" && c.error_code === "CHAT_TOOL_DENIED");
    check(
      micros(c.started_at) <= micros(decision.accepted_at) &&
        micros(decision.accepted_at) < micros(p.expires_at),
    );
    check(
      c.finished_at === null ||
        micros(decision.accepted_at) <= micros(c.finished_at),
    );
  }
  if (result) {
    check(
      p !== null &&
        (result.kind === "scenario_created" ||
          result.kind === "scenario_appended"),
    );
    check(
      result.before_scenario_revision === p.expected_scenario_revision &&
        result.source_draft_revision === p.expected_draft_revision,
    );
    check(same(result.scenario.definition, p.after));
    check(
      Object.entries(p.snapshots).every(([k, v]) =>
        same(result.scenario[k as keyof T.ScenarioVersion], v),
      ),
    );
    if (c.tool === "scenario_append")
      check(
        p.before !== null &&
          result.scenario.id === p.before.id &&
          result.scenario.version === p.before.version + 1,
      );
  }
}
export const parseScenarioVersionV4 = (
  value: unknown,
): Promise<ScenarioVersion> => parseV4("ScenarioVersion", value);
export async function parseScenarioHistoryV4(
  value: unknown,
  id: string,
): Promise<ScenarioHistory> {
  check(identifier(id));
  const parsed = await parseV4("ScenarioHistoryV4", value);
  check(parsed.scenario_id === id);
  return parsed;
}
export async function parseScenarioPageV4(
  value: unknown,
  offset: number,
  limit: number,
): Promise<ScenarioPage> {
  check(integer(offset, 0, 100) && integer(limit, 1, 100));
  const parsed = await parseV4("ScenarioPageV4", value);
  check(parsed.offset === offset && parsed.limit === limit);
  return parsed;
}
export interface ScenarioGrantCommitment {
  requestedAuthority: "scenario_write_v4";
  request: T.GrantInputV4;
  settings_revision: number;
  profile_id: string;
  /** Operator inputs or projection of the captured, validated immutable version. */
  resolved_inputs: T.ProtectedInputs;
}
export async function boundGrant(
  value: unknown,
  commitment: ScenarioGrantCommitment,
): Promise<T.GrantV4> {
  // Capture all inputs before the first await, not after selectors may change.
  const captured = capture(commitment) as ScenarioGrantCommitment;
  check(captured.requestedAuthority === "scenario_write_v4");
  const g = await parseV4("GrantV4", value),
    request = await parseV4("GrantInputV4", captured.request);
  const resolved = await parseV4("ProtectedInputs", captured.resolved_inputs);
  for (const key of [
    "schema_version",
    "scope",
    "request_id",
    "session_id",
    "turn_request_id",
    "expected_sequence",
    "intent",
  ] as const)
    check(same(g[key], request[key]));
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(request.text),
  );
  check(
    g.text_sha256 ===
      Array.from(new Uint8Array(hash), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join(""),
  );
  check(
    g.settings_revision === captured.settings_revision &&
      g.profile_id === captured.profile_id,
  );
  check(same(g.resolved_inputs, resolved));
  return g;
}
export async function boundCall(
  value: unknown,
  grant: T.GrantV4,
  deadlineAt: string,
): Promise<T.CallV4> {
  const captured = capture(grant);
  const c = await parseV4("CallV4", value),
    g = await parseV4("GrantV4", captured);
  namedShape("ChatTime", deadlineAt);
  check(c.grant_id === g.id);
  if (c.tool !== "configuration_read") {
    const a = c.arguments as T.CreateArgs | T.AppendArgs;
    check(
      c.tool === g.intent.operation &&
        a.expected_scenario_revision === g.intent.expected_scenario_revision &&
        a.expected_draft_revision === g.intent.expected_draft_revision,
    );
    if (c.tool === "scenario_append")
      check("base" in a && same(a.base, g.intent.base));
  }
  if (c.proposal) {
    const p = c.proposal;
    check(
      same(p.input_source, g.intent.input_source) &&
        p.inputs_digest === g.inputs_digest,
    );
    check(same(protectedProjection(p.after), g.resolved_inputs));
    const expiry = micros(g.expires_at),
      deadline = micros(deadlineAt);
    check(micros(p.expires_at) === (expiry < deadline ? expiry : deadline));
  }
  if (c.result?.kind === "scenario_context") {
    const r = c.result;
    check(
      same(r.resolved_inputs, g.resolved_inputs) &&
        r.inputs_digest === g.inputs_digest,
    );
    check(
      r.operation === g.intent.operation &&
        r.scenario_revision === g.intent.expected_scenario_revision &&
        r.draft_revision === g.intent.expected_draft_revision,
    );
    check(same(r.base === null ? null : ref(r.base), g.intent.base));
  }
  return c;
}
/** Cold history requires an exact requested turn, never an invented grant request ID. */
export async function parseTranscriptV4(
  value: unknown,
  turnId: string,
): Promise<T.TranscriptV4> {
  namedShape("ChatID", turnId);
  const result = await parseV4("TranscriptV4", value);
  check(result.turn_id === turnId);
  return result;
}
