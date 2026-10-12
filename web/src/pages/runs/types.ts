import type { ScenarioVersion, ScenarioDefinition } from "../scenarios/types";
export type State =
  | "QUEUED"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "TIMED_OUT";
export type Request = {
  request_id: string;
  mode: "OFFLINE";
  scenario_id: string;
  scenario_version: number;
  scenario_digest: string;
};
export type Summary = {
  id: string;
  request_id: string;
  ordinal: number;
  mode: "OFFLINE";
  task: "offline_manifest_v1";
  state: State;
  attempt: number;
  generation: number;
  scenario_id: string;
  scenario_version: number;
  scenario_digest: string;
  snapshot_digest: string;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  deadline_at: string;
  cancel_requested_at: string | null;
  event_count: number;
  failure_code: string | null;
};
export type Snapshot = {
  schema_version: 1;
  task: "offline_manifest_v1";
  source_revision: number;
  scenario: ScenarioVersion;
  digest: string;
};
export type Result = {
  schema_version: 1;
  kind: "offline_preparation";
  snapshot_digest: string;
  checks: string[];
  expected_policy: Pick<
    ScenarioDefinition,
    "expected_action" | "delivery_expectation" | "detection_required"
  >;
  success_criteria: ScenarioDefinition["success_criteria"];
  declared_limits: Pick<
    ScenarioDefinition,
    "traffic_budget" | "stop_conditions"
  >;
  evidence_requirements: { role: string; availability: "NOT_INGESTED" }[];
  asset_status: "NOT_APPLICABLE" | "NOT_DECLARED" | "DECLARED_UNVERIFIED";
  evaluation: "NOT_EVALUATED";
  defense_verdict: null;
  measurements: null;
  digest: string;
};
export type Detail = {
  schema_version: 1;
  run: Summary;
  snapshot: Snapshot;
  result: Result | null;
};
export type RunEvent = {
  seq: number;
  at: string;
  type: string;
  state: State;
  attempt: number;
  generation: number;
  reason: string | null;
};
export type RunPage = {
  schema_version: 1;
  after: number;
  through: number;
  limit: number;
  total: number;
  items: Summary[];
  next_after: number | null;
};
export type EventPage = {
  schema_version: 1;
  run_id: string;
  after: number;
  limit: number;
  total: number;
  items: RunEvent[];
  next_after: number | null;
};
export type Checkpoint = {
  run: Summary;
  source_revision: number;
  result_digest: string | null;
};
export type Receipt = {
  schema_version: 1;
  request: Request;
  request_digest: string;
  checkpoint: Checkpoint | null;
};
