/** Closed B3 v4 shape types. Runtime consistency lives in chat-scenario-wire.
 * Generated from the accepted revision-2 shape inventory; no runtime activation.
 */
import type {
  ScenarioVersion as StoredScenarioVersion,
  ScenarioDefinition as StoredScenarioDefinition,
  ScenarioHistory,
  ScenarioPage,
} from "../scenarios/types";
export type Identifier = string;
export type ChatID = string;
export type Digest = string;
export type Name = string;
export type Goal = string;
export type Timestamp = string;
export type ChatTime = string;
export type UserText = string;
export type TrafficBudget = {
  max_pps: number;
  max_bps: number;
  max_packets: number;
  max_bytes: number;
  max_connections: number;
  duration_seconds: number;
};
export type StopConditions = {
  max_legitimate_loss_pct: number;
  max_service_latency_ms: number;
  max_cpu_pct: number | null;
  max_memory_pct: number | null;
  max_sessions: number | null;
  management_loss: true;
};
export type PcapAsset = { label: Name; sha256: Digest; size_bytes: number };
export type SuccessCriteria = {
  minimum_delivery_pct: number;
  maximum_delivery_pct: number;
  detection_deadline_ms: number | null;
};
export type ProtectedInputs = {
  target_id: Identifier;
  sink_id: Identifier;
  dut_version: Name;
  policy_version: Name;
  pcap_asset: PcapAsset | null;
  traffic_budget: TrafficBudget;
  stop_conditions: StopConditions;
};
export type ModelDefinition = {
  name: Name;
  objective: Goal;
  profile_id: "tcpreplay-policy" | "k6-http";
  protocol: "TCP" | "UDP" | "DNS" | "HTTP";
  ip_version: 4 | 6;
  expected_action: "ALLOW" | "BLOCK" | "ALERT";
  delivery_expectation: "ALLOW" | "BLOCK";
  detection_required: boolean;
  success_criteria: SuccessCriteria;
  evidence_requirements: (
    | "ingress_pcap"
    | "egress_pcap"
    | "dut_events"
    | "service_probe"
    | "resource_metrics"
  )[];
};
export type ScenarioDefinition = StoredScenarioDefinition;
export type TargetSnapshot = {
  id: Identifier;
  name: Name;
  address: string;
  kind: "DUT" | "SINK";
  status: "draft";
  created_at: Timestamp;
};
export type ProfileSnapshot =
  | {
      id: "tcpreplay-policy";
      name: { en: "Packet replay policy check"; ko: "패킷 재생 정책 점검" };
      description: {
        en: "Planning template: operator-owned capture, isolated DUT/SINK, bounded rate and duration, explicit stop/rollback criteria. No capture loaded or packets emitted.";
        ko: "계획 템플릿: 운영자 소유 캡처, 격리된 DUT/SINK, 속도·시간 제한 및 명시적 중지·복구 기준이 필요합니다. 캡처를 로드하거나 패킷을 전송하지 않습니다.";
      };
      engine: "tcpreplay";
      layer: "L2–L4";
      status: "template";
    }
  | {
      id: "k6-http";
      name: { en: "HTTP policy scenario"; ko: "HTTP 정책 시나리오" };
      description: {
        en: "Planning template: approved lab HTTP service, bounded users/request rate/duration, expected responses and abort criteria. No script executed or HTTP request sent.";
        ko: "계획 템플릿: 승인된 실험실 HTTP 서비스, 사용자·요청 속도·시간 상한, 예상 응답과 중단 기준이 필요합니다. 스크립트를 실행하거나 HTTP 요청을 보내지 않습니다.";
      };
      engine: "k6";
      layer: "L7";
      status: "template";
    };
export type ScenarioVersion = StoredScenarioVersion;
export type ScenarioRef = { id: Identifier; version: number; digest: Digest };
export type OperatorSource = { source: "operator"; inputs: ProtectedInputs };
export type VersionSource = {
  source: "scenario_version";
  reference: ScenarioRef;
};
export type InputSource = OperatorSource | VersionSource;
export type Intent = {
  operation: "scenario_create" | "scenario_append";
  expected_scenario_revision: number;
  expected_draft_revision: number;
  base: ScenarioRef | null;
  input_source: InputSource;
};
export type GrantInputV4 = {
  schema_version: 4;
  scope: "scenario_write";
  request_id: ChatID;
  session_id: ChatID;
  turn_request_id: ChatID;
  expected_sequence: number;
  text: UserText;
  intent: Intent;
};
export type GrantV4 = {
  schema_version: 4;
  id: ChatID;
  request_id: ChatID;
  session_id: ChatID;
  turn_request_id: ChatID;
  expected_sequence: number;
  text_sha256: Digest;
  settings_revision: number;
  profile_id: string;
  created_at: ChatTime;
  expires_at: ChatTime;
  status: "pending" | "consumed" | "revoked" | "expired";
  scope: "scenario_write";
  read_scope: ["scenario_context", "scenarios", "scenario"];
  proposal_tools: ("scenario_create" | "scenario_append")[];
  intent: Intent;
  resolved_inputs: ProtectedInputs;
  inputs_digest: Digest;
};
export type RuntimeV4 = {
  schema_version: 4;
  mode: "operator_approved_settings";
  supported: boolean;
  reason:
    | "CHAT_NOT_CONFIGURED"
    | "CHAT_UNSUPPORTED_PROFILE"
    | "CHAT_UNSUPPORTED_OPTIONS"
    | null;
  tools: [
    "configuration_read",
    "agent_profile_update",
    "target_create",
    "skill_create",
    "scenario_create",
    "scenario_append",
  ];
  max_calls: 3;
  max_writes: 1;
  requires_write_approval: true;
};
export type ContextArgs = { kind: "scenario_context" };
export type ListArgs = { kind: "scenarios"; offset: number; limit: number };
export type DetailArgs = {
  kind: "scenario";
  id: Identifier;
  version: number;
  digest: Digest;
};
export type ReadArgs = ContextArgs | ListArgs | DetailArgs;
export type CreateArgs = {
  expected_scenario_revision: number;
  expected_draft_revision: number;
  definition: ModelDefinition;
};
export type AppendArgs = {
  expected_scenario_revision: number;
  expected_draft_revision: number;
  definition: ModelDefinition;
  base: ScenarioRef;
};
export type Snapshots = {
  target_snapshot: TargetSnapshot;
  sink_snapshot: TargetSnapshot;
  profile_snapshot: ProfileSnapshot;
  catalog_version: "1.0.0";
};
export type ContextResult = {
  kind: "scenario_context";
  scenario_revision: number;
  draft_revision: number;
  operation: "scenario_create" | "scenario_append";
  resolved_inputs: ProtectedInputs;
  inputs_digest: Digest;
  target_snapshot: TargetSnapshot;
  sink_snapshot: TargetSnapshot;
  profiles: ProfileSnapshot[];
  base: ScenarioVersion | null;
};
export type ScenarioSummary = {
  id: Identifier;
  version: number;
  digest: Digest;
  name: Name;
  profile_id: "tcpreplay-policy" | "k6-http";
  target_id: Identifier;
  sink_id: Identifier;
};
export type ListResult = {
  kind: "scenarios";
  scenario_revision: number;
  total: number;
  offset: number;
  limit: number;
  items: ScenarioSummary[];
  next_offset: number | null;
};
export type DetailResult = {
  kind: "scenario";
  scenario_revision: number;
  scenario: ScenarioVersion;
};
export type ProposalV4 = {
  schema_version: 4;
  operation: "scenario_create" | "scenario_append";
  digest: Digest;
  expected_scenario_revision: number;
  expected_draft_revision: number;
  before: ScenarioVersion | null;
  after: ScenarioDefinition;
  snapshots: Snapshots;
  input_source: InputSource;
  inputs_digest: Digest;
  expires_at: ChatTime;
};
export type CreatedResult = {
  kind: "scenario_created";
  before_scenario_revision: number;
  after_scenario_revision: number;
  source_draft_revision: number;
  scenario: ScenarioVersion;
  execution_enabled: false;
};
export type AppendedResult = {
  kind: "scenario_appended";
  before_scenario_revision: number;
  after_scenario_revision: number;
  source_draft_revision: number;
  scenario: ScenarioVersion;
  execution_enabled: false;
};
export type ResultV4 =
  ContextResult | ListResult | DetailResult | CreatedResult | AppendedResult;
export type DecisionInput = {
  request_id: ChatID;
  proposal_digest: Digest;
  decision: "approve" | "deny";
};
export type Decision = {
  request_id: ChatID;
  proposal_digest: Digest;
  decision: "approve" | "deny";
  schema_version: 1;
  call_id: ChatID;
  accepted_at: ChatTime;
};
export type CallV4 = {
  id: ChatID;
  index: number;
  provider_call_id: string;
  tool: "configuration_read" | "scenario_create" | "scenario_append";
  arguments: ContextArgs | ListArgs | DetailArgs | CreateArgs | AppendArgs;
  args_digest: Digest;
  grant_id: ChatID;
  actor: "operator_authorized_model";
  status:
    | "requested"
    | "awaiting_approval"
    | "executing"
    | "succeeded"
    | "denied"
    | "conflict"
    | "failed"
    | "uncertain"
    | "cancelled";
  error_code:
    | "CHAT_TOOL_DENIED"
    | "CHAT_TOOL_WRITE_FENCED"
    | "CHAT_SCENARIO_WRITE_FENCED"
    | "CHAT_TOOL_CONFLICT"
    | "CHAT_TIMEOUT"
    | "CHAT_INVALID_REQUEST"
    | "CHAT_NOT_FOUND"
    | "CHAT_TOOL_LIMIT"
    | "CHAT_STORAGE_ERROR"
    | "CHAT_TOOL_UNCERTAIN"
    | "CHAT_CANCELLED"
    | null;
  proposal: ProposalV4 | null;
  decision: Decision | null;
  result: ResultV4 | null;
  started_at: ChatTime;
  finished_at: ChatTime | null;
};
export type TranscriptV4 = {
  schema_version: 4;
  turn_id: ChatID;
  revision: number;
  calls: CallV4[];
};
export type ScenarioStateInspection = {
  schema_version: 4;
  scenario_revision: number;
  registry_write_status: "available" | "quarantined";
};
export type ReconcileInputV4 = {
  schema_version: 4;
  request_id: ChatID;
  expected_generation: number;
  expected_draft_revision: number;
  expected_scenario_revision: number;
  acknowledge_uncertain: true;
};
export type ReconcileReceiptV4 = {
  schema_version: 4;
  request_id: ChatID;
  acknowledged_call_ids: ChatID[];
  generation: number;
  write_fenced: false;
  prior_outcomes: "remain_uncertain";
  observed_scenario_revision: number;
  scenario_recovery: "not_performed";
};
export type ToolEnvelopeV4 = {
  ok: boolean;
  result: ResultV4 | null;
  error_code:
    | "CHAT_TOOL_DENIED"
    | "CHAT_TOOL_WRITE_FENCED"
    | "CHAT_SCENARIO_WRITE_FENCED"
    | "CHAT_TOOL_CONFLICT"
    | "CHAT_TIMEOUT"
    | "CHAT_INVALID_REQUEST"
    | "CHAT_NOT_FOUND"
    | "CHAT_TOOL_LIMIT"
    | "CHAT_STORAGE_ERROR"
    | "CHAT_TOOL_UNCERTAIN"
    | "CHAT_CANCELLED"
    | null;
};
export type ScenarioExpectation = {
  scenario: ScenarioVersion;
  after_scenario_revision: number;
};
export type ScenarioSelection = {
  id: Identifier;
  version: number;
  expectation: ScenarioExpectation | null;
};
export type ScenarioHistoryV4 = ScenarioHistory;
export type ScenarioPageV4 = ScenarioPage;
export interface ContractTypes {
  Identifier: Identifier;
  ChatID: ChatID;
  Digest: Digest;
  Name: Name;
  Goal: Goal;
  Timestamp: Timestamp;
  ChatTime: ChatTime;
  UserText: UserText;
  TrafficBudget: TrafficBudget;
  StopConditions: StopConditions;
  PcapAsset: PcapAsset;
  SuccessCriteria: SuccessCriteria;
  ProtectedInputs: ProtectedInputs;
  ModelDefinition: ModelDefinition;
  ScenarioDefinition: ScenarioDefinition;
  TargetSnapshot: TargetSnapshot;
  ProfileSnapshot: ProfileSnapshot;
  ScenarioVersion: ScenarioVersion;
  ScenarioRef: ScenarioRef;
  OperatorSource: OperatorSource;
  VersionSource: VersionSource;
  InputSource: InputSource;
  Intent: Intent;
  GrantInputV4: GrantInputV4;
  GrantV4: GrantV4;
  RuntimeV4: RuntimeV4;
  ContextArgs: ContextArgs;
  ListArgs: ListArgs;
  DetailArgs: DetailArgs;
  ReadArgs: ReadArgs;
  CreateArgs: CreateArgs;
  AppendArgs: AppendArgs;
  Snapshots: Snapshots;
  ContextResult: ContextResult;
  ScenarioSummary: ScenarioSummary;
  ListResult: ListResult;
  DetailResult: DetailResult;
  ProposalV4: ProposalV4;
  CreatedResult: CreatedResult;
  AppendedResult: AppendedResult;
  ResultV4: ResultV4;
  DecisionInput: DecisionInput;
  Decision: Decision;
  CallV4: CallV4;
  TranscriptV4: TranscriptV4;
  ScenarioStateInspection: ScenarioStateInspection;
  ReconcileInputV4: ReconcileInputV4;
  ReconcileReceiptV4: ReconcileReceiptV4;
  ToolEnvelopeV4: ToolEnvelopeV4;
  ScenarioExpectation: ScenarioExpectation;
  ScenarioSelection: ScenarioSelection;
  ScenarioHistoryV4: ScenarioHistoryV4;
  ScenarioPageV4: ScenarioPageV4;
}
export type ContractName = keyof ContractTypes;
