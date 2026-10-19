import type { SkillSelection } from "./contracts";
import { check, identifier, integer, object } from "../pages/ai/chat-tool-wire";
import { parseDraftSkill } from "../pages/ai/chat-skill-wire";
import { canonical, utf8Length } from "../pages/scenarios/json";
function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
/** App-owned exact receipt; URL/history never supply receipt authority. */
export function cloneSkillSelection(value: unknown): SkillSelection {
  const hasExpectation =
    value !== null &&
    typeof value === "object" &&
    Object.hasOwn(value, "expectation");
  const s = object(value, hasExpectation ? "id expectation" : "id");
  identifier(s.id);
  check(typeof s.id === "string");
  if (!hasExpectation) return Object.freeze({ id: s.id });
  const e = object(s.expectation, "skill after_revision");
  const skill = parseDraftSkill(e.skill);
  integer(e.after_revision);
  check(skill.id === s.id && utf8Length(canonical(e)) <= 32768);
  return freeze({
    id: s.id,
    expectation: {
      skill: JSON.parse(JSON.stringify(skill)),
      after_revision: e.after_revision,
    },
  });
}
export function skillSelectionFromLocation(
  location: Pick<Location, "pathname" | "search">,
): SkillSelection | undefined {
  if (location.pathname !== "/skills") return undefined;
  try {
    decodeURIComponent(location.search);
    const params = new URLSearchParams(location.search);
    if ([...params].length !== 1 || params.getAll("skill").length !== 1)
      return undefined;
    return cloneSkillSelection({ id: params.get("skill") });
  } catch {
    return undefined;
  }
}
export function skillSelectionPath(selection: SkillSelection): string {
  return `/skills?skill=${encodeURIComponent(cloneSkillSelection(selection).id)}`;
}
