import type { Checkpoint, Detail, Request, Summary } from "./types";
import { requireValue, parseSummary, moment } from "./wire";
import { terminal, reachable } from "./grammar";
import { canonical } from "../scenarios/json";
export const checkpoint = (d: Detail): Checkpoint => ({
  run: d.run,
  source_revision: d.snapshot.source_revision,
  result_digest: d.result?.digest ?? null,
});
export const immutableKeys = [
  "id",
  "request_id",
  "ordinal",
  "mode",
  "task",
  "scenario_id",
  "scenario_version",
  "scenario_digest",
  "snapshot_digest",
  "created_at",
  "deadline_at",
] as const;
export function bindRequest(r: Request, d: Detail): void {
  requireValue(
    d.run.request_id === r.request_id &&
      d.run.mode === r.mode &&
      d.run.scenario_id === r.scenario_id &&
      d.run.scenario_version === r.scenario_version &&
      d.run.scenario_digest === r.scenario_digest &&
      d.snapshot.scenario.digest === r.scenario_digest,
  );
}
export function compareCheckpoint(old: Checkpoint, next: Checkpoint): void {
  parseSummary(old.run);
  parseSummary(next.run);
  bindList(old.run, next.run);
  requireValue(old.source_revision === next.source_revision);
  if (terminal(old.run.state) || old.run.event_count === next.run.event_count) {
    requireValue(canonical(old) === canonical(next));
    return;
  }
  for (const key of ["attempt", "generation", "event_count"] as const)
    requireValue(next.run[key] >= old.run[key]);
  for (const key of ["started_at", "cancel_requested_at"] as const)
    if (old.run[key] !== null) requireValue(next.run[key] === old.run[key]);
  requireValue(
    moment(next.run.updated_at) >= moment(old.run.updated_at) &&
      reachable(old.run, next.run),
  );
}
export function bindList(summary: Summary, next: Summary): void {
  requireValue(immutableKeys.every((k) => summary[k] === next[k]));
}
export function compareDetail(old: Detail, next: Detail): void {
  requireValue(canonical(old.snapshot) === canonical(next.snapshot));
  compareCheckpoint(checkpoint(old), checkpoint(next));
}
