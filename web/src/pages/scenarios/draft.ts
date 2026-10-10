import type { EvidenceRole, ScenarioDefinition } from "./types";
import { validDefinition } from "./validation";
export const blankValues = {
  name: "",
  objective: "",
  target_id: "",
  sink_id: "",
  dut_version: "",
  policy_version: "",
  profile_id: "tcpreplay-policy",
  protocol: "TCP",
  ip_version: "4",
  expected_action: "ALLOW",
  delivery_expectation: "ALLOW",
  max_pps: "",
  max_bps: "",
  max_packets: "",
  max_bytes: "",
  max_connections: "",
  duration_seconds: "",
  minimum_delivery_pct: "",
  maximum_delivery_pct: "",
  detection_deadline_ms: "",
  max_legitimate_loss_pct: "",
  max_service_latency_ms: "",
  max_cpu_pct: "",
  max_memory_pct: "",
  max_sessions: "",
  asset_label: "",
  asset_sha256: "",
  asset_size_bytes: "",
};
export type Values = typeof blankValues;
export type Draft = {
  values: Values;
  detection: boolean;
  asset: boolean;
  evidence: EvidenceRole[];
};
export const newDraft = (): Draft => ({
  values: { ...blankValues },
  detection: false,
  asset: false,
  evidence: [],
});
export function draftFromDefinition(definition: ScenarioDefinition): Draft {
  const draft = newDraft();
  const flat = {
    ...definition,
    ...definition.traffic_budget,
    ...definition.success_criteria,
    ...definition.stop_conditions,
    asset_label: definition.pcap_asset?.label ?? "",
    asset_sha256: definition.pcap_asset?.sha256 ?? "",
    asset_size_bytes: definition.pcap_asset?.size_bytes ?? "",
  };
  for (const key of Object.keys(draft.values) as (keyof Values)[])
    draft.values[key] = flat[key] === null ? "" : String(flat[key]);
  return {
    ...draft,
    detection: definition.detection_required,
    asset: definition.pcap_asset !== null,
    evidence: [...definition.evidence_requirements],
  };
}
const number = (s: string) => (/^(?:0|[1-9][0-9]*)$/.test(s) ? Number(s) : NaN);
const optional = (s: string) => (s === "" ? null : number(s));
export function definitionFromDraft(draft: Draft) {
  const v = draft.values;
  const definition = {
    name: v.name,
    objective: v.objective,
    target_id: v.target_id,
    sink_id: v.sink_id,
    dut_version: v.dut_version,
    policy_version: v.policy_version,
    profile_id: v.profile_id,
    protocol: v.protocol,
    ip_version: number(v.ip_version),
    expected_action: v.expected_action,
    delivery_expectation: v.delivery_expectation,
    detection_required: draft.detection,
    pcap_asset: draft.asset
      ? {
          label: v.asset_label,
          sha256: v.asset_sha256,
          size_bytes: number(v.asset_size_bytes),
        }
      : null,
    traffic_budget: {
      max_pps: number(v.max_pps),
      max_bps: number(v.max_bps),
      max_packets: number(v.max_packets),
      max_bytes: number(v.max_bytes),
      max_connections: number(v.max_connections),
      duration_seconds: number(v.duration_seconds),
    },
    success_criteria: {
      minimum_delivery_pct: number(v.minimum_delivery_pct),
      maximum_delivery_pct: number(v.maximum_delivery_pct),
      detection_deadline_ms: optional(v.detection_deadline_ms),
    },
    stop_conditions: {
      max_legitimate_loss_pct: number(v.max_legitimate_loss_pct),
      max_service_latency_ms: number(v.max_service_latency_ms),
      max_cpu_pct: optional(v.max_cpu_pct),
      max_memory_pct: optional(v.max_memory_pct),
      max_sessions: optional(v.max_sessions),
      management_loss: true,
    },
    evidence_requirements: [...draft.evidence],
  };
  return validDefinition(definition) ? definition : null;
}
