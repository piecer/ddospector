import type { State, Summary } from "./types";
export const terminal = (state: State) =>
  ["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(state);
export const failures = [
  "SNAPSHOT_INVALID",
  "OFFLINE_PREPARATION_FAILED",
  "RESULT_LIMIT_EXCEEDED",
  "RETRY_EXHAUSTED",
] as const;
export type Node = {
  state: State;
  attempt: number;
  generation: number;
  count: number;
  step: number;
  type: string;
  reason: string | null;
};
export const admission: Node = {
  state: "QUEUED",
  attempt: 0,
  generation: 0,
  count: 1,
  step: 0,
  type: "QUEUED",
  reason: null,
};
export function successors(n: Node): Node[] {
  if (terminal(n.state) || n.count >= 16) return [];
  const out: Node[] = [];
  const add = (
    state: State,
    type: string,
    reason: string | null = null,
    attempt = n.attempt,
    generation = n.generation,
    step = n.step,
  ) =>
    out.push({
      state,
      type,
      reason,
      attempt,
      generation,
      step,
      count: n.count + 1,
    });
  const owned = n.state !== "QUEUED",
    revoked = n.generation + (owned ? 1 : 0);
  if (n.state === "QUEUED") {
    if (n.attempt < 3)
      add("RUNNING", "CLAIMED", null, n.attempt + 1, n.generation + 1, 0);
    add("CANCELLED", "CANCELLED", "BEFORE_CLAIM");
  }
  if (n.state === "RUNNING") {
    if (n.step < 2)
      add(
        "RUNNING",
        n.step === 0 ? "SNAPSHOT_VERIFIED" : "MANIFEST_COMPILED",
        null,
        n.attempt,
        n.generation,
        n.step + 1,
      );
    if (n.step === 2) add("SUCCEEDED", "SUCCEEDED", null, n.attempt, revoked);
    for (const failure of failures)
      if (failure !== "RETRY_EXHAUSTED" || n.attempt === 3)
        add("FAILED", "FAILED", failure, n.attempt, revoked);
    if (n.attempt < 3)
      add("QUEUED", "REQUEUED", "LEASE_EXPIRED", n.attempt, revoked, 0);
    add("CANCEL_REQUESTED", "CANCEL_REQUESTED");
    add("CANCELLED", "CANCELLED", "LEASE_REVOKED", n.attempt, revoked);
  }
  if (n.state === "CANCEL_REQUESTED") {
    add("CANCELLED", "CANCELLED", "WORKER_ACK", n.attempt, revoked);
    add("CANCELLED", "CANCELLED", "LEASE_REVOKED", n.attempt, revoked);
  } else add("TIMED_OUT", "TIMED_OUT", "DEADLINE_EXCEEDED", n.attempt, revoked);
  return out.filter((x) => x.generation <= 6);
}
const key = (n: Node) => JSON.stringify(n);
export function unique(nodes: Node[]): Node[] {
  return [...new Map(nodes.map((n) => [key(n), n])).values()];
}
export const levels: Node[][] = [[admission]];
for (let i = 1; i < 16; i++)
  levels.push(unique(levels[i - 1].flatMap(successors)));
export function matching(s: Summary): Node[] {
  return (levels[s.event_count - 1] ?? []).filter(
    (n) =>
      n.state === s.state &&
      n.attempt === s.attempt &&
      n.generation === s.generation &&
      (["FAILED", "TIMED_OUT"].includes(s.state)
        ? n.reason === s.failure_code
        : s.failure_code === null),
  );
}
export function reachable(a: Summary, b: Summary): boolean {
  let nodes = matching(a);
  for (let i = a.event_count; i < b.event_count; i++)
    nodes = unique(nodes.flatMap(successors));
  const targets = new Set(matching(b).map(key));
  return nodes.some((n) => targets.has(key(n)));
}
