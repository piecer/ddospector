import type { Target, TrafficProfile } from "../../lib/contracts";
export const evidenceRoles = [
  "ingress_pcap",
  "egress_pcap",
  "dut_events",
  "service_probe",
  "resource_metrics",
] as const;
export type EvidenceRole = (typeof evidenceRoles)[number];
export type ScenarioDefinition = {
  name: string;
  objective: string;
  target_id: string;
  sink_id: string;
  dut_version: string;
  policy_version: string;
  profile_id: "tcpreplay-policy" | "k6-http";
  protocol: "TCP" | "UDP" | "DNS" | "HTTP";
  ip_version: 4 | 6;
  expected_action: "ALLOW" | "BLOCK" | "ALERT";
  delivery_expectation: "ALLOW" | "BLOCK";
  detection_required: boolean;
  pcap_asset: { label: string; sha256: string; size_bytes: number } | null;
  traffic_budget: {
    max_pps: number;
    max_bps: number;
    max_packets: number;
    max_bytes: number;
    max_connections: number;
    duration_seconds: number;
  };
  success_criteria: {
    minimum_delivery_pct: number;
    maximum_delivery_pct: number;
    detection_deadline_ms: number | null;
  };
  stop_conditions: {
    max_legitimate_loss_pct: number;
    max_service_latency_ms: number;
    max_cpu_pct: number | null;
    max_memory_pct: number | null;
    max_sessions: number | null;
    management_loss: true;
  };
  evidence_requirements: EvidenceRole[];
};
export type ScenarioVersion = {
  id: string;
  version: number;
  created_at: string;
  status: "definition";
  execution_enabled: false;
  definition: ScenarioDefinition;
  target_snapshot: Target;
  sink_snapshot: Target;
  profile_snapshot: TrafficProfile;
  catalog_version: "1.0.0";
  digest: string;
};
export type ScenarioPage = {
  revision: number;
  total: number;
  offset: number;
  limit: number;
  items: ScenarioVersion[];
  execution_enabled: false;
};
export type ScenarioHistory = {
  revision: number;
  scenario_id: string;
  versions: ScenarioVersion[];
  execution_enabled: false;
};
export type ScenarioReceipt = {
  revision: number;
  scenario: ScenarioVersion;
  execution_enabled: false;
};
export type Submission = {
  revision: number;
  definition: ScenarioDefinition;
  opened: { id: string; version: number } | null;
};
