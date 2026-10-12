import { canonical, digest, utf8Length } from "../scenarios/json";
import { exact, integer, sha256 } from "../scenarios/validation";
import { parseVersion } from "../scenarios/wire";
import type { Detail, Summary, Snapshot, Result } from "./types";
import { snapshot, freeze } from "./object";
import { matching, terminal } from "./grammar";
export function invalid(): never {
  throw new Error("Invalid run response.");
}
export function requireValue(ok: unknown): asserts ok {
  if (!ok) invalid();
}
export const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(
    v,
  );
export function moment(v: unknown): bigint {
  requireValue(
    typeof v === "string" &&
      /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$/.test(
        v,
      ) &&
      !v.startsWith("0000"),
  );
  const ms = Date.parse(v);
  requireValue(
    Number.isFinite(ms) && new Date(ms).toISOString() === v.slice(0, 23) + "Z",
  );
  return BigInt(ms) * 1000n + BigInt(v.slice(23, 26));
}
export const summaryKeys = [
  "id",
  "request_id",
  "ordinal",
  "mode",
  "task",
  "state",
  "attempt",
  "generation",
  "scenario_id",
  "scenario_version",
  "scenario_digest",
  "snapshot_digest",
  "created_at",
  "started_at",
  "updated_at",
  "finished_at",
  "deadline_at",
  "cancel_requested_at",
  "event_count",
  "failure_code",
] as const;
export function parseSummary(value: unknown): Summary {
  value = snapshot(value, 4096);
  requireValue(exact(value, summaryKeys));
  const v = value;
  requireValue(
    uuid(v.id) &&
      uuid(v.request_id) &&
      uuid(v.scenario_id) &&
      sha256(v.scenario_digest) &&
      sha256(v.snapshot_digest),
  );
  requireValue(
    v.mode === "OFFLINE" &&
      v.task === "offline_manifest_v1" &&
      integer(v.ordinal, 1, 128) &&
      integer(v.scenario_version, 1, 10),
  );
  requireValue(
    integer(v.attempt, 0, 3) &&
      integer(v.generation, 0, 6) &&
      integer(v.event_count, 1, 16) &&
      matching(v as Summary).length > 0,
  );
  const created = moment(v.created_at),
    updated = moment(v.updated_at),
    deadline = moment(v.deadline_at);
  requireValue(deadline - created === 300000000n && updated >= created);
  requireValue((v.started_at === null) === (v.attempt === 0));
  requireValue(
    (v.finished_at !== null) === terminal(v.state as Summary["state"]),
  );
  requireValue(
    (v.cancel_requested_at !== null) ===
      (v.state === "CANCEL_REQUESTED" || v.state === "CANCELLED"),
  );
  for (const name of [
    "started_at",
    "cancel_requested_at",
    "finished_at",
  ] as const)
    if (v[name] !== null) {
      const at = moment(v[name]);
      requireValue(at >= created && at <= updated);
    }
  if (v.finished_at !== null) requireValue(v.finished_at === v.updated_at);
  if (v.started_at !== null) requireValue(moment(v.started_at) < deadline);
  if (v.cancel_requested_at !== null)
    requireValue(
      moment(v.cancel_requested_at) < deadline &&
        (v.started_at === null ||
          moment(v.cancel_requested_at) >= moment(v.started_at)),
    );
  if (v.state === "TIMED_OUT") requireValue(updated >= deadline);
  else if (v.state !== "CANCELLED") requireValue(updated < deadline);
  if (v.event_count === 1) requireValue(v.updated_at === v.created_at);
  if (v.event_count === 2 && v.state === "RUNNING")
    requireValue(v.started_at === v.updated_at);
  if (
    v.state === "CANCEL_REQUESTED" ||
    (v.state === "CANCELLED" && v.attempt === 0)
  )
    requireValue(v.cancel_requested_at === v.updated_at);
  requireValue(utf8Length(canonical(v)) <= 4096);
  return v as Summary;
}
export async function expectedResult(s: Snapshot): Promise<Result> {
  const d = s.scenario.definition;
  const content = {
    schema_version: 1 as const,
    kind: "offline_preparation" as const,
    snapshot_digest: s.digest,
    checks: [
      "SNAPSHOT_INTEGRITY",
      "POLICY_CONSISTENCY",
      "REQUIREMENTS_COMPILED",
    ],
    expected_policy: {
      expected_action: d.expected_action,
      delivery_expectation: d.delivery_expectation,
      detection_required: d.detection_required,
    },
    success_criteria: d.success_criteria,
    declared_limits: {
      traffic_budget: d.traffic_budget,
      stop_conditions: d.stop_conditions,
    },
    evidence_requirements: d.evidence_requirements.map((role) => ({
      role,
      availability: "NOT_INGESTED" as const,
    })),
    asset_status:
      d.profile_id === "k6-http"
        ? ("NOT_APPLICABLE" as const)
        : d.pcap_asset === null
          ? ("NOT_DECLARED" as const)
          : ("DECLARED_UNVERIFIED" as const),
    evaluation: "NOT_EVALUATED" as const,
    defense_verdict: null,
    measurements: null,
  };
  return { ...content, digest: await digest(content) };
}
export async function parseDetail(value: unknown): Promise<Detail> {
  value = snapshot(value, 32768);
  requireValue(
    exact(value, ["schema_version", "run", "snapshot", "result"]) &&
      value.schema_version === 1,
  );
  const run = parseSummary(value.run),
    s = value.snapshot;
  requireValue(
    exact(s, [
      "schema_version",
      "task",
      "source_revision",
      "scenario",
      "digest",
    ]) &&
      s.schema_version === 1 &&
      s.task === run.task &&
      integer(s.source_revision, run.scenario_version, 1000) &&
      sha256(s.digest),
  );
  const scenario = await parseVersion(s.scenario);
  requireValue(
    scenario.id === run.scenario_id &&
      scenario.version === run.scenario_version &&
      scenario.digest === run.scenario_digest,
  );
  const { digest: expected, ...content } = s;
  requireValue(
    (await digest(content)) === expected && expected === run.snapshot_digest,
  );
  if (run.state === "SUCCEEDED")
    requireValue(
      canonical(value.result) ===
        canonical(await expectedResult(s as Snapshot)) &&
        utf8Length(canonical(value.result)) <= 8192,
    );
  else requireValue(value.result === null);
  requireValue(
    utf8Length(canonical(s)) <= 12288 && utf8Length(canonical(value)) <= 32768,
  );
  return freeze(value as Detail);
}
