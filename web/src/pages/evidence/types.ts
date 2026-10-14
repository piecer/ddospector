import type { ScenarioDefinition } from "../scenarios/types";
export type Side = "ingress" | "egress";
export type Descriptor = { name: string; size_bytes: number; sha256: string };
export type Provenance = {
  provenance: "SYNTHETIC" | "UNVERIFIED";
  sample_id: "complete" | "violation" | "unknown" | null;
  coverage: "COMPLETE_SYNTHETIC" | "UNKNOWN";
};
export type Summary = Provenance & {
  id: string;
  request_id: string;
  ordinal: number;
  run_id: string;
  run_snapshot_digest: string;
  created_at: string;
  ingress: Descriptor;
  egress: Descriptor;
  analysis_state: "REGISTERED" | "ANALYZED";
};
export type Policy = Pick<
  ScenarioDefinition,
  | "profile_id"
  | "ip_version"
  | "protocol"
  | "expected_action"
  | "delivery_expectation"
  | "detection_required"
  | "evidence_requirements"
> &
  ScenarioDefinition["success_criteria"];
export type SideFacts = {
  sha256: string;
  size_bytes: number;
  parse_error: string | null;
  packet_count: number | null;
  wire_bytes: number | null;
  payload_bytes: number | null;
  first_timestamp_ns: string | null;
  last_timestamp_ns: string | null;
  timestamps_ordered: boolean | null;
};
export type Facts = {
  matched_packets: number;
  unmatched_ingress_packets: number;
  unmatched_egress_packets: number;
  delivery_basis_points_floor: number | null;
};
export type Report = Provenance & {
  schema_version: 1;
  kind: "offline_capture_criterion";
  rule_id: "TCP_ALLOW_CAPTURE_V1";
  scope: "CAPTURE_RECORDSET_ONLY";
  evidence_id: string;
  run_id: string;
  run_snapshot_digest: string;
  created_at: string;
  outcome: "SATISFIED" | "VIOLATED" | "UNKNOWN";
  scenario_evaluation: "NOT_EVALUATED";
  defense_verdict: null;
  policy: Policy;
  captures: Record<Side, SideFacts>;
  facts: Facts | null;
  issues: string[];
  unassessed_requirements: string[];
  digest: string;
};
export type Detail = {
  schema_version: 1;
  evidence: Summary;
  report: Report | null;
};
export type Collection = { schema_version: 1; items: Summary[]; total: number };
export type Binding = {
  request_id: string;
  run_id: string;
  run_snapshot_digest: string;
  ingress: Descriptor;
  egress: Descriptor;
};
export type Upload = {
  request_id: string;
  run_id: string;
  ingress: { name: string; base64: string };
  egress: { name: string; base64: string };
};
