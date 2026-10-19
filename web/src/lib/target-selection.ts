import type { TargetSelection } from "./contracts";
import { check, identifier, integer, object } from "../pages/ai/chat-tool-wire";
import { parseTarget } from "../pages/ai/chat-target-wire";
import { canonical, utf8Length } from "../pages/scenarios/json";
/** Only Application accepts a receipt handoff; URL/history never provide it. */
export function cloneTargetSelection(value: unknown): TargetSelection {
  const hasExpectation =
    value !== null &&
    typeof value === "object" &&
    Object.hasOwn(value, "expectation");
  const s = object(value, hasExpectation ? "id expectation" : "id");
  identifier(s.id);
  check(typeof s.id === "string");
  if (!hasExpectation) return Object.freeze({ id: s.id });
  const e = object(s.expectation, "target after_revision");
  const t = parseTarget(e.target);
  integer(e.after_revision);
  check(t.id === s.id && utf8Length(canonical(e)) <= 4096);
  return Object.freeze({
    id: s.id,
    expectation: Object.freeze({
      target: Object.freeze({ ...t }),
      after_revision: e.after_revision,
    }),
  });
}
export function targetSelectionFromLocation(
  location: Pick<Location, "pathname" | "search">,
): TargetSelection | undefined {
  if (location.pathname !== "/targets") return undefined;
  try {
    decodeURIComponent(location.search);
    const params = new URLSearchParams(location.search);
    if ([...params].length !== 1 || params.getAll("target").length !== 1)
      return undefined;
    return cloneTargetSelection({ id: params.get("target") });
  } catch {
    return undefined;
  }
}
export function targetSelectionPath(selection: TargetSelection): string {
  const owned = cloneTargetSelection(selection);
  return `/targets?target=${encodeURIComponent(owned.id)}`;
}
