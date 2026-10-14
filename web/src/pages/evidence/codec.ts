import { canonical, digest, utf8Length } from "../scenarios/json";
import { exact, denseArray, integer, sha256 } from "../scenarios/validation";
import { uuid, moment } from "../runs/wire";
import { rawJSON } from "../runs/raw";
import { snapshot, freeze } from "../runs/object";
import type { Detail as RunDetail } from "../runs/types";
import type {
  Binding,
  Collection,
  Descriptor,
  Detail,
  Policy,
  Report,
  SideFacts,
  Summary,
} from "./types";
import { sampleCatalog } from "./catalog";
export function check(ok: unknown): asserts ok {
  if (!ok) throw new Error("EVIDENCE_CLIENT_INVALID");
}
export const sides = ["ingress", "egress"] as const;
export function validName(v: unknown): v is string {
  return (
    typeof v === "string" &&
    v.length <= 256 &&
    Array.from(v).length >= 1 &&
    Array.from(v).length <= 128 &&
    utf8Length(v) <= 256 &&
    Array.from(v).every((char) => {
      const c = char.codePointAt(0)!;
      return !(
        c <= 31 ||
        (c >= 127 && c <= 159) ||
        (c >= 0xd800 && c <= 0xdfff) ||
        (c >= 0x202a && c <= 0x202e) ||
        (c >= 0x2066 && c <= 0x2069)
      );
    })
  );
}
export function descriptor(v: unknown): Descriptor {
  check(
    exact(v, ["name", "size_bytes", "sha256"]) &&
      validName(v.name) &&
      integer(v.size_bytes, 1, 65536) &&
      sha256(v.sha256),
  );
  return v as Descriptor;
}
function origin(
  v: Record<string, unknown>,
  i: { sha256: string; size_bytes: number },
  e: { sha256: string; size_bytes: number },
) {
  const sample = sampleCatalog.find(
    (x) => x.ingress.sha256 === i.sha256 && x.egress.sha256 === e.sha256,
  );
  check(
    v.provenance === (sample ? "SYNTHETIC" : "UNVERIFIED") &&
      v.sample_id === (sample?.sample_id ?? null) &&
      v.coverage === (sample?.coverage ?? "UNKNOWN"),
  );
  if (sample)
    check(
      i.size_bytes === sample.ingress.size_bytes &&
        e.size_bytes === sample.egress.size_bytes,
    );
}
export function summary(v: unknown): Summary {
  check(
    exact(v, [
      "id",
      "request_id",
      "ordinal",
      "run_id",
      "run_snapshot_digest",
      "created_at",
      "provenance",
      "sample_id",
      "coverage",
      "ingress",
      "egress",
      "analysis_state",
    ]),
  );
  check(
    uuid(v.id) &&
      uuid(v.request_id) &&
      uuid(v.run_id) &&
      sha256(v.run_snapshot_digest) &&
      integer(v.ordinal, 1, 16),
  );
  moment(v.created_at);
  check(v.analysis_state === "REGISTERED" || v.analysis_state === "ANALYZED");
  origin(v, descriptor(v.ingress), descriptor(v.egress));
  return v as Summary;
}
export const policyKeys = [
  "profile_id",
  "ip_version",
  "protocol",
  "expected_action",
  "delivery_expectation",
  "detection_required",
  "detection_deadline_ms",
  "minimum_delivery_pct",
  "maximum_delivery_pct",
  "evidence_requirements",
];
const requirements = [
  "ingress_pcap",
  "egress_pcap",
  "dut_events",
  "service_probe",
  "resource_metrics",
];
function strings(
  v: unknown,
  allowed: string[],
  max: number,
): asserts v is string[] {
  check(
    denseArray(v, 0, max) &&
      v.every((x) => typeof x === "string" && allowed.includes(x)) &&
      new Set(v).size === v.length,
  );
}
function policy(v: unknown): Policy {
  check(exact(v, policyKeys));
  check(
    (v.profile_id === "tcpreplay-policy" || v.profile_id === "k6-http") &&
      ["TCP", "UDP", "DNS", "HTTP"].includes(v.protocol as string) &&
      (v.ip_version === 4 || v.ip_version === 6),
  );
  check(
    ["ALLOW", "BLOCK", "ALERT"].includes(v.expected_action as string) &&
      ["ALLOW", "BLOCK"].includes(v.delivery_expectation as string) &&
      typeof v.detection_required === "boolean",
  );
  check(
    integer(v.minimum_delivery_pct, 0, 100) &&
      integer(v.maximum_delivery_pct, 0, 100) &&
      v.minimum_delivery_pct <= v.maximum_delivery_pct,
  );
  check(
    v.detection_required
      ? integer(v.detection_deadline_ms, 1, 60000)
      : v.detection_deadline_ms === null,
  );
  check((v.profile_id === "tcpreplay-policy") !== (v.protocol === "HTTP"));
  check(
    v.expected_action === "ALERT"
      ? v.detection_required
      : v.expected_action === v.delivery_expectation,
  );
  check(
    v.delivery_expectation === "ALLOW"
      ? v.maximum_delivery_pct === 100
      : v.minimum_delivery_pct === 0,
  );
  strings(v.evidence_requirements, requirements, 5);
  const required = v.evidence_requirements;
  check(
    required.includes("service_probe") &&
      (v.profile_id !== "tcpreplay-policy" ||
        ["ingress_pcap", "egress_pcap"].every((x) => required.includes(x))) &&
      (!v.detection_required || required.includes("dut_events")),
  );
  return v as Policy;
}
const stats = [
  "packet_count",
  "wire_bytes",
  "payload_bytes",
  "first_timestamp_ns",
  "last_timestamp_ns",
  "timestamps_ordered",
];
function sideFacts(v: unknown): SideFacts {
  check(
    exact(v, ["sha256", "size_bytes", "parse_error", ...stats]) &&
      sha256(v.sha256) &&
      integer(v.size_bytes, 1, 65536),
  );
  if (v.parse_error !== null) {
    check(
      typeof v.parse_error === "string" &&
        [
          "PCAP_TOO_LARGE",
          "PCAP_TOO_MANY_PACKETS",
          "PCAP_MALFORMED",
          "PCAP_UNSUPPORTED",
          "PCAP_TRUNCATED",
          "PCAP_CHECKSUM_UNVERIFIED",
        ].includes(v.parse_error) &&
        stats.every((k) => v[k] === null),
    );
  } else {
    check(
      integer(v.packet_count, 0, 4096) &&
        integer(v.wire_bytes, 0, 65536) &&
        integer(v.payload_bytes, 0, 65536) &&
        typeof v.timestamps_ordered === "boolean",
    );
    const n = v.packet_count;
    check(
      v.wire_bytes === v.size_bytes - 24 - 16 * n &&
        v.payload_bytes <= v.wire_bytes - 54 * n,
    );
    if (n === 0)
      check(
        v.first_timestamp_ns === null &&
          v.last_timestamp_ns === null &&
          v.timestamps_ordered &&
          v.wire_bytes === 0 &&
          v.payload_bytes === 0,
      );
    else {
      for (const t of [v.first_timestamp_ns, v.last_timestamp_ns])
        check(
          typeof t === "string" &&
            /^(0|[1-9][0-9]{0,18})$/.test(t) &&
            BigInt(t) <= 4294967295999999999n,
        );
      if (v.timestamps_ordered)
        check(
          BigInt(v.first_timestamp_ns as string) <=
            BigInt(v.last_timestamp_ns as string),
        );
      if (n === 1)
        check(
          v.first_timestamp_ns === v.last_timestamp_ns && v.timestamps_ordered,
        );
    }
  }
  return v as SideFacts;
}
export async function report(value: unknown, s: Summary): Promise<Report> {
  const v = snapshot(value, 32768);
  check(
    exact(v, [
      "schema_version",
      "kind",
      "rule_id",
      "scope",
      "evidence_id",
      "run_id",
      "run_snapshot_digest",
      "created_at",
      "provenance",
      "sample_id",
      "coverage",
      "outcome",
      "scenario_evaluation",
      "defense_verdict",
      "policy",
      "captures",
      "facts",
      "issues",
      "unassessed_requirements",
      "digest",
    ]),
  );
  check(
    v.schema_version === 1 &&
      v.kind === "offline_capture_criterion" &&
      v.rule_id === "TCP_ALLOW_CAPTURE_V1" &&
      v.scope === "CAPTURE_RECORDSET_ONLY" &&
      v.scenario_evaluation === "NOT_EVALUATED" &&
      v.defense_verdict === null,
  );
  check(
    v.evidence_id === s.id &&
      v.run_id === s.run_id &&
      v.run_snapshot_digest === s.run_snapshot_digest &&
      sha256(v.digest),
  );
  moment(v.created_at);
  const p = policy(v.policy);
  check(exact(v.captures, ["ingress", "egress"]));
  const i = sideFacts(v.captures.ingress),
    e = sideFacts(v.captures.egress);
  origin(v, i, e);
  for (const side of sides) {
    const c = v.captures[side] as SideFacts;
    check(c.sha256 === s[side].sha256 && c.size_bytes === s[side].size_bytes);
  }
  for (const k of ["provenance", "coverage", "sample_id"] as const)
    check(v[k] === s[k]);
  const f = v.facts;
  if (i.parse_error !== null || e.parse_error !== null) check(f === null);
  else {
    check(
      exact(f, [
        "matched_packets",
        "unmatched_ingress_packets",
        "unmatched_egress_packets",
        "delivery_basis_points_floor",
      ]),
    );
    for (const k of [
      "matched_packets",
      "unmatched_ingress_packets",
      "unmatched_egress_packets",
    ])
      check(integer(f[k], 0, 4096));
    const m = f.matched_packets as number,
      n = i.packet_count!;
    check(
      m + (f.unmatched_ingress_packets as number) === n &&
        m + (f.unmatched_egress_packets as number) === e.packet_count,
    );
    check(
      f.delivery_basis_points_floor ===
        (n ? Math.floor((10000 * m) / n) : null),
    );
  }
  const issues: string[] = [];
  if (!(
    p.profile_id === "tcpreplay-policy" &&
    p.ip_version === 4 &&
    p.protocol === "TCP" &&
    p.expected_action === "ALLOW" &&
    p.delivery_expectation === "ALLOW" &&
    !p.detection_required
  ))
    issues.push("UNSUPPORTED_SCENARIO");
  if (v.coverage !== "COMPLETE_SYNTHETIC")
    issues.push("CAPTURE_COVERAGE_UNKNOWN");
  if (i.packet_count === 0) issues.push("NO_INGRESS_RECORDS");
  strings(
    v.issues,
    ["UNSUPPORTED_SCENARIO", "CAPTURE_COVERAGE_UNKNOWN", "NO_INGRESS_RECORDS"],
    3,
  );
  check(canonical(v.issues) === canonical(issues));
  let outcome = "UNKNOWN";
  if (!issues.length && f !== null) {
    const m = (f as Record<string, number>).matched_packets,
      n = i.packet_count!;
    outcome =
      p.minimum_delivery_pct * n <= 100 * m &&
      100 * m <= p.maximum_delivery_pct * n
        ? "SATISFIED"
        : "VIOLATED";
  }
  check(v.outcome === outcome);
  strings(v.unassessed_requirements, requirements, 3);
  check(
    canonical(v.unassessed_requirements) ===
      canonical(
        p.evidence_requirements.filter(
          (x) => x !== "ingress_pcap" && x !== "egress_pcap",
        ),
      ),
  );
  const { digest: expected, ...body } = v;
  check((await digest(body)) === expected);
  return freeze(v as Report);
}
export function wire(bytes: Uint8Array, max = 65536): unknown {
  const v = rawJSON(bytes, max),
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
      bytes,
    );
  check(canonical(v) === text);
  return v;
}
export async function parseDetail(value: unknown): Promise<Detail> {
  const v = snapshot(value, 65536);
  check(
    exact(v, ["schema_version", "evidence", "report"]) &&
      v.schema_version === 1,
  );
  const s = summary(v.evidence);
  check((v.report === null) === (s.analysis_state === "REGISTERED"));
  if (v.report !== null) await report(v.report, s);
  return freeze(v as Detail);
}
export const decodeDetail = async (bytes: Uint8Array) =>
  parseDetail(wire(bytes));
export function decodeList(bytes: Uint8Array): Collection {
  const v = wire(bytes);
  check(
    exact(v, ["schema_version", "items", "total"]) &&
      v.schema_version === 1 &&
      integer(v.total, 0, 16) &&
      denseArray(v.items, 0, 16) &&
      v.items.length === v.total,
  );
  const ids = new Set(),
    requests = new Set();
  v.items.forEach((x, index) => {
    const s = summary(x);
    check(
      s.ordinal === index + 1 && !ids.has(s.id) && !requests.has(s.request_id),
    );
    ids.add(s.id);
    requests.add(s.request_id);
  });
  return freeze(v as Collection);
}
export function bindRun(d: Detail, r: RunDetail): void {
  check(
    r.run.state === "SUCCEEDED" &&
      r.run.mode === "OFFLINE" &&
      r.run.id === d.evidence.run_id &&
      r.snapshot.digest === d.evidence.run_snapshot_digest,
  );
  if (d.report) {
    const definition = r.snapshot.scenario.definition;
    const expected = Object.fromEntries(
      policyKeys.map((k) => [
        k,
        k in definition.success_criteria
          ? definition.success_criteria[
              k as keyof typeof definition.success_criteria
            ]
          : definition[k as keyof typeof definition],
      ]),
    );
    check(canonical(d.report.policy) === canonical(expected));
  }
}
export function bindSubmission(d: Detail, b: Binding): void {
  const s = d.evidence;
  check(
    s.request_id === b.request_id &&
      s.run_id === b.run_id &&
      s.run_snapshot_digest === b.run_snapshot_digest,
  );
  for (const side of sides) check(canonical(s[side]) === canonical(b[side]));
}
