import type { Target } from "../../lib/contracts";
import {
  parseScenarioInteger,
  parseOptionalScenarioInteger,
} from "../scenarios/draft";
import {
  budgetBounds,
  identifier,
  integer,
  scenarioText,
  sha256,
} from "../scenarios/validation";
import type { ScenarioDefinition, ScenarioVersion } from "../scenarios/types";

/** Structural r2 wire shapes; this module neither grants authority nor decodes HTTP. */
export type ScenarioProtectedInputs = Pick<
  ScenarioDefinition,
  | "target_id"
  | "sink_id"
  | "dut_version"
  | "policy_version"
  | "pcap_asset"
  | "traffic_budget"
  | "stop_conditions"
>;
export type ScenarioInputReference = Pick<
  ScenarioVersion,
  "id" | "version" | "digest"
>;
export type ScenarioInputSource =
  | { source: "operator"; inputs: ScenarioProtectedInputs }
  | { source: "scenario_version"; reference: ScenarioInputReference };

const emptyValues = {
  target_id: "",
  sink_id: "",
  dut_version: "",
  policy_version: "",
  max_pps: "",
  max_bps: "",
  max_packets: "",
  max_bytes: "",
  max_connections: "",
  duration_seconds: "",
  max_legitimate_loss_pct: "",
  max_service_latency_ms: "",
  max_cpu_pct: "",
  max_memory_pct: "",
  max_sessions: "",
  asset_label: "",
  asset_sha256: "",
  asset_size_bytes: "",
};
export type ScenarioInputValues = typeof emptyValues;
export type OperatorScenarioInputDraft = {
  source: "operator";
  values: ScenarioInputValues;
  asset: boolean;
};
export type ScenarioVersionInputDraft = {
  source: "scenario_version";
  selection: {
    reference: ScenarioInputReference;
    inputs: ScenarioProtectedInputs;
  } | null;
};
export type ScenarioInputDraft =
  OperatorScenarioInputDraft | ScenarioVersionInputDraft;
export type ScenarioInputField = keyof ScenarioInputValues | "source";
export type ScenarioInputResult =
  | { valid: false; errors: ScenarioInputField[] }
  | {
      valid: true;
      input_source: ScenarioInputSource;
      resolved_inputs: ScenarioProtectedInputs;
    };

export function newScenarioInputDraft(): OperatorScenarioInputDraft {
  return { source: "operator", values: { ...emptyValues }, asset: false };
}

/** Capture only an explicitly selected, already validated immutable record.
 * Fetching and full-record/digest validation belong to the trusted parent codec.
 */
export function scenarioInputDraftFromVersion(
  record: ScenarioVersion,
): ScenarioVersionInputDraft {
  const { id, version, digest } = record;
  const {
    target_id,
    sink_id,
    dut_version,
    policy_version,
    pcap_asset,
    traffic_budget,
    stop_conditions,
  } = record.definition;
  return {
    source: "scenario_version",
    selection: structuredClone({
      reference: { id, version, digest },
      inputs: {
        target_id,
        sink_id,
        dut_version,
        policy_version,
        pcap_asset,
        traffic_budget,
        stop_conditions,
      },
    }),
  };
}

/** Explicit copy-to-edit drops the reference: there is never mixed provenance. */
export function copyScenarioInputsToOperator(
  draft: ScenarioVersionInputDraft,
): OperatorScenarioInputDraft | null {
  if (!draft.selection) return null;
  const inputs = draft.selection.inputs;
  const result = newScenarioInputDraft();
  const flat = {
    target_id: inputs.target_id,
    sink_id: inputs.sink_id,
    dut_version: inputs.dut_version,
    policy_version: inputs.policy_version,
    ...inputs.traffic_budget,
    ...inputs.stop_conditions,
    asset_label: inputs.pcap_asset?.label ?? "",
    asset_sha256: inputs.pcap_asset?.sha256 ?? "",
    asset_size_bytes: inputs.pcap_asset?.size_bytes ?? "",
  };
  for (const key of Object.keys(result.values) as (keyof ScenarioInputValues)[])
    result.values[key] = flat[key] === null ? "" : String(flat[key]);
  result.asset = inputs.pcap_asset !== null;
  return result;
}

export function buildScenarioInputResult(
  draft: ScenarioInputDraft,
  targets: readonly Target[],
): ScenarioInputResult {
  if (draft.source === "scenario_version") {
    const copied = copyScenarioInputsToOperator(draft);
    if (!copied || !draft.selection)
      return { valid: false, errors: ["source"] };
    const parsed = buildScenarioInputResult(copied, targets);
    if (!parsed.valid) return parsed;
    return {
      valid: true,
      input_source: {
        source: "scenario_version",
        reference: { ...draft.selection.reference },
      },
      resolved_inputs: structuredClone(draft.selection.inputs),
    };
  }
  const v = draft.values;
  const errors: ScenarioInputField[] = [];
  for (const key of ["target_id", "sink_id"] as const) {
    if (
      !identifier(v[key]) ||
      !scenarioText(v[key], 64) ||
      (key === "sink_id" && v.sink_id === v.target_id) ||
      !targets.some(
        (t) =>
          t.id === v[key] && t.kind === (key === "target_id" ? "DUT" : "SINK"),
      )
    )
      errors.push(key);
  }
  for (const key of ["dut_version", "policy_version"] as const)
    if (!scenarioText(v[key], 120)) errors.push(key);
  const required = (
    key: keyof ScenarioInputValues,
    min: number,
    max: number,
  ) => {
    const value = parseScenarioInteger(v[key]);
    // Require literal canonical input; never normalize the operator's text.
    if (!integer(value, min, max) || String(value) !== v[key]) errors.push(key);
    return value;
  };
  const optional = (key: keyof ScenarioInputValues, max: number) => {
    const value = parseOptionalScenarioInteger(v[key]);
    if (value !== null && (!integer(value, 1, max) || String(value) !== v[key]))
      errors.push(key);
    return value;
  };
  const protectedInputs: ScenarioProtectedInputs = {
    target_id: v.target_id,
    sink_id: v.sink_id,
    dut_version: v.dut_version,
    policy_version: v.policy_version,
    pcap_asset: null,
    traffic_budget: {
      max_pps: required("max_pps", 1, budgetBounds.max_pps),
      max_bps: required("max_bps", 1, budgetBounds.max_bps),
      max_packets: required("max_packets", 1, budgetBounds.max_packets),
      max_bytes: required("max_bytes", 1, budgetBounds.max_bytes),
      max_connections: required(
        "max_connections",
        1,
        budgetBounds.max_connections,
      ),
      duration_seconds: required(
        "duration_seconds",
        1,
        budgetBounds.duration_seconds,
      ),
    },
    stop_conditions: {
      max_legitimate_loss_pct: required("max_legitimate_loss_pct", 0, 100),
      max_service_latency_ms: required("max_service_latency_ms", 1, 60000),
      max_cpu_pct: optional("max_cpu_pct", 100),
      max_memory_pct: optional("max_memory_pct", 100),
      max_sessions: optional("max_sessions", 1000000),
      management_loss: true,
    },
  };
  if (draft.asset) {
    if (!scenarioText(v.asset_label, 120)) errors.push("asset_label");
    if (!sha256(v.asset_sha256) || v.asset_sha256.length !== 64)
      errors.push("asset_sha256");
    protectedInputs.pcap_asset = {
      label: v.asset_label,
      sha256: v.asset_sha256,
      size_bytes: required("asset_size_bytes", 1, 67108864),
    };
  }
  if (errors.length) return { valid: false, errors };
  return {
    valid: true,
    input_source: { source: "operator", inputs: protectedInputs },
    resolved_inputs: structuredClone(protectedInputs),
  };
}
