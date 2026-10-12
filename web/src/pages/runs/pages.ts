import { exact, integer, denseArray } from "../scenarios/validation";
import { levels, successors, unique, type Node } from "./grammar";
import { parseSummary, requireValue, moment, uuid } from "./wire";
import { snapshot, freeze } from "./object";
import { canonical, utf8Length } from "../scenarios/json";
import type { RunPage, EventPage, RunEvent } from "./types";
export function parseList(
  value: unknown,
  after = 0,
  limit = 20,
  through?: number,
): RunPage {
  value = snapshot(value, 131072);
  requireValue(
    exact(value, [
      "schema_version",
      "after",
      "through",
      "limit",
      "total",
      "items",
      "next_after",
    ]) &&
      value.schema_version === 1 &&
      value.after === after &&
      value.limit === limit &&
      integer(after, 0, 128) &&
      integer(limit, 1, 20) &&
      integer(value.through, 0, 128) &&
      value.total === value.through &&
      (through === undefined || value.through === through) &&
      denseArray(value.items, 0, 20),
  );
  requireValue(
    value.items.length === Math.max(0, Math.min(limit, value.through - after)),
  );
  const items = value.items.map(parseSummary);
  requireValue(
    items.every((s, i) => s.ordinal === after + i + 1) &&
      new Set(items.map((s) => s.id)).size === items.length &&
      new Set(items.map((s) => s.request_id)).size === items.length,
  );
  const last = items.at(-1)?.ordinal;
  requireValue(
    value.next_after ===
      (last !== undefined && last < value.through ? last : null),
  );
  return freeze(value as RunPage);
}
function matches(n: Node, e: RunEvent): boolean {
  return (
    n.count === e.seq &&
    n.state === e.state &&
    n.attempt === e.attempt &&
    n.generation === e.generation &&
    n.type === e.type &&
    n.reason === e.reason
  );
}
export function parseEvents(
  value: unknown,
  id: string,
  after = 0,
  limit = 16,
): EventPage {
  value = snapshot(value, 16384);
  requireValue(
    uuid(id) &&
      exact(value, [
        "schema_version",
        "run_id",
        "after",
        "limit",
        "total",
        "items",
        "next_after",
      ]) &&
      value.schema_version === 1 &&
      value.run_id === id &&
      value.after === after &&
      value.limit === limit &&
      integer(after, 0, 16) &&
      integer(limit, 1, 16) &&
      integer(value.total, 1, 16) &&
      denseArray(value.items, 0, 16),
  );
  requireValue(
    value.items.length === Math.max(0, Math.min(limit, value.total - after)),
  );
  let previous: RunEvent | null = null,
    nodes: Node[] = [],
    admitted: bigint | null = null,
    cancelled: bigint | null = null;
  requireValue(levels[value.total - 1].length > 0);
  for (let i = 0; i < value.items.length; i++) {
    const v = value.items[i];
    requireValue(
      exact(v, [
        "seq",
        "at",
        "type",
        "state",
        "attempt",
        "generation",
        "reason",
      ]) &&
        v.seq === after + i + 1 &&
        integer(v.attempt, 0, 3) &&
        integer(v.generation, 0, 6) &&
        utf8Length(canonical(v)) <= 512,
    );
    const event = v as RunEvent;
    const time = moment(event.at);
    if (event.seq === 1) admitted = time;
    if (event.type === "CANCEL_REQUESTED") cancelled = time;
    if (admitted !== null) {
      const deadline = admitted + 300000000n;
      if (event.type === "TIMED_OUT") requireValue(time >= deadline);
      else if (event.type !== "CANCELLED" || cancelled === null)
        requireValue(time < deadline);
    }
    requireValue(previous === null || time >= moment(previous.at));
    nodes = (
      previous ? nodes.flatMap(successors) : levels[event.seq - 1]
    ).filter((n) => matches(n, event));
    requireValue(nodes.length > 0);
    previous = event;
  }
  let remaining = nodes;
  if (previous) {
    for (let seq = previous.seq; seq < value.total; seq++)
      remaining = unique(remaining.flatMap(successors));
    requireValue(remaining.length > 0);
  }
  const last = previous?.seq;
  requireValue(
    value.next_after ===
      (last !== undefined && last < value.total ? last : null),
  );
  return freeze(value as EventPage);
}
