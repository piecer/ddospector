import { forbiddenText, pythonSpace } from "../ai-settings/unicode-text";

/** S01 follows Python Name/Goal, not AI profile whitespace restrictions. */
export function scenarioText(
  value: unknown,
  max: number,
  multiline = false,
): value is string {
  if (typeof value !== "string") return false;
  const chars = Array.from(value);
  return (
    chars.length >= 1 &&
    chars.length <= max &&
    chars.some((c) => !pythonSpace(c)) &&
    !chars.some((c) => forbiddenText(c) && !(multiline && "\n\r\t".includes(c)))
  );
}
export function exact(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return (
    Reflect.ownKeys(value).length === keys.length &&
    keys.every((key) => {
      const d = descriptors[key];
      return d && d.enumerable && Object.hasOwn(d, "value");
    })
  );
}
export function denseArray(
  value: unknown,
  min: number,
  max: number,
): value is unknown[] {
  if (
    !Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Array.prototype ||
    value.length < min ||
    value.length > max ||
    Reflect.ownKeys(value).length !== value.length + 1
  )
    return false;
  for (let i = 0; i < value.length; i++) {
    const d = Object.getOwnPropertyDescriptor(value, String(i));
    if (!d || !d.enumerable || !Object.hasOwn(d, "value")) return false;
  }
  return true;
}
export const integer = (v: unknown, min: number, max: number): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max;
export const identifier = (v: unknown): v is string =>
  typeof v === "string" && /^[a-z0-9-]{1,64}$/.test(v);
export const sha256 = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export const budgetBounds = {
  max_pps: 1_000_000_000,
  max_bps: 1_000_000_000_000,
  max_packets: 1_000_000_000_000,
  max_bytes: 1_000_000_000_000,
  max_connections: 1_000_000,
  duration_seconds: 3600,
};
const definitionKeys = [
  "name",
  "objective",
  "target_id",
  "sink_id",
  "dut_version",
  "policy_version",
  "profile_id",
  "protocol",
  "ip_version",
  "expected_action",
  "delivery_expectation",
  "detection_required",
  "pcap_asset",
  "traffic_budget",
  "success_criteria",
  "stop_conditions",
  "evidence_requirements",
];
export function validDefinition(
  v: unknown,
): v is import("./types").ScenarioDefinition {
  if (
    !exact(v, definitionKeys) ||
    !scenarioText(v.name, 120) ||
    !scenarioText(v.objective, 2000, true) ||
    !scenarioText(v.dut_version, 120) ||
    !scenarioText(v.policy_version, 120) ||
    !identifier(v.target_id) ||
    !identifier(v.sink_id) ||
    v.target_id === v.sink_id
  )
    return false;
  if (v.profile_id !== "tcpreplay-policy" && v.profile_id !== "k6-http")
    return false;
  if (
    v.profile_id === "k6-http"
      ? v.protocol !== "HTTP" || v.pcap_asset !== null
      : !["TCP", "UDP", "DNS"].includes(v.protocol as string)
  )
    return false;
  if (v.ip_version !== 4 && v.ip_version !== 6) return false;
  if (
    !["ALLOW", "BLOCK", "ALERT"].includes(v.expected_action as string) ||
    !["ALLOW", "BLOCK"].includes(v.delivery_expectation as string) ||
    typeof v.detection_required !== "boolean"
  )
    return false;
  if (
    v.expected_action === "ALERT"
      ? !v.detection_required
      : v.expected_action !== v.delivery_expectation
  )
    return false;
  const asset = v.pcap_asset;
  if (
    asset !== null &&
    (!exact(asset, ["label", "sha256", "size_bytes"]) ||
      !scenarioText(asset.label, 120) ||
      !sha256(asset.sha256) ||
      !integer(asset.size_bytes, 1, 67108864))
  )
    return false;
  const budget = v.traffic_budget;
  if (
    !exact(budget, Object.keys(budgetBounds)) ||
    !Object.entries(budgetBounds).every(([key, max]) =>
      integer(budget[key], 1, max),
    )
  )
    return false;
  const criteria = v.success_criteria;
  if (
    !exact(criteria, [
      "minimum_delivery_pct",
      "maximum_delivery_pct",
      "detection_deadline_ms",
    ]) ||
    !integer(criteria.minimum_delivery_pct, 0, 100) ||
    !integer(criteria.maximum_delivery_pct, 0, 100) ||
    criteria.minimum_delivery_pct > criteria.maximum_delivery_pct
  )
    return false;
  if (
    v.delivery_expectation === "ALLOW"
      ? criteria.maximum_delivery_pct !== 100
      : criteria.minimum_delivery_pct !== 0
  )
    return false;
  if (
    v.detection_required
      ? !integer(criteria.detection_deadline_ms, 1, 60000)
      : criteria.detection_deadline_ms !== null
  )
    return false;
  const stops = v.stop_conditions;
  if (
    !exact(stops, [
      "max_legitimate_loss_pct",
      "max_service_latency_ms",
      "max_cpu_pct",
      "max_memory_pct",
      "max_sessions",
      "management_loss",
    ]) ||
    !integer(stops.max_legitimate_loss_pct, 0, 100) ||
    !integer(stops.max_service_latency_ms, 1, 60000) ||
    stops.management_loss !== true
  )
    return false;
  for (const [key, max] of [
    ["max_cpu_pct", 100],
    ["max_memory_pct", 100],
    ["max_sessions", 1000000],
  ] as const)
    if (stops[key] !== null && !integer(stops[key], 1, max)) return false;
  const evidence = v.evidence_requirements;
  if (
    !denseArray(evidence, 1, 5) ||
    !evidence.every(
      (role) =>
        typeof role === "string" &&
        [
          "ingress_pcap",
          "egress_pcap",
          "dut_events",
          "service_probe",
          "resource_metrics",
        ].includes(role),
    ) ||
    new Set(evidence).size !== evidence.length
  )
    return false;
  const required = ["service_probe"];
  if (v.profile_id === "tcpreplay-policy")
    required.push("ingress_pcap", "egress_pcap");
  if (v.detection_required) required.push("dut_events");
  if (
    ["max_cpu_pct", "max_memory_pct", "max_sessions"].some(
      (key) => stops[key] !== null,
    )
  )
    required.push("resource_metrics");
  return required.every((role) => evidence.includes(role));
}
