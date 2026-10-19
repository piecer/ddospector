import type {
  Skill,
  SkillInput,
  CompleteDraftSkill,
} from "../../lib/contracts";
import { canonical, utf8Length } from "../scenarios/json";
import { timestamp as domainTimestamp } from "../scenarios/timestamp";
import {
  array,
  check,
  identifier,
  integer,
  object,
  text,
} from "./chat-tool-wire";
import { skillSafety, skillTemplates } from "./chat-skill-catalog";
import type { ToolCall } from "./chat-tool-types";

export function parseSkillInput(value: unknown): SkillInput {
  const s = object(value, "name description instructions category");
  text(s.name, 120);
  text(s.description, 1000, true);
  text(s.instructions, 8000, true);
  check(["planning", "measurement", "analysis"].includes(s.category as string));
  return value as SkillInput;
}
export function parseDraftSkill(value: unknown): CompleteDraftSkill {
  const s = object(
    value,
    "id name description instructions version category status allowed_operations required_capabilities safety_rules",
  );
  identifier(s.id);
  check(!skillTemplates.some((t) => t.id === s.id));
  check(s.version === "1.0.0" && s.status === "draft");
  for (const key of ["name", "description", "instructions"]) {
    const locale = object(s[key], "en ko");
    check(locale.en === locale.ko);
    text(
      locale.en,
      key === "name" ? 120 : key === "description" ? 1000 : 8000,
      key !== "name",
    );
  }
  check(["planning", "measurement", "analysis"].includes(s.category as string));
  array(s.allowed_operations, 0);
  array(s.required_capabilities, 0);
  array(s.safety_rules, skillSafety.length);
  s.safety_rules.forEach((r) => {
    const rule = object(r, "en ko");
    check(typeof rule.en === "string" && typeof rule.ko === "string");
  });
  check(canonical(s.safety_rules) === canonical(skillSafety));
  return value as CompleteDraftSkill;
}
export function validateSkillResult(value: unknown, call: ToolCall) {
  const r = object(value, "kind before_revision after_revision skill audit");
  check(
    r.kind === "skill_created" &&
      call.proposal &&
      "operation" in call.proposal &&
      call.proposal.operation === "skill_create",
  );
  integer(r.before_revision);
  integer(r.after_revision);
  check(
    r.before_revision === call.proposal.expected_draft_revision &&
      r.after_revision === r.before_revision + 1,
  );
  const s = parseDraftSkill(r.skill);
  check(
    canonical({
      name: s.name.en,
      description: s.description.en,
      instructions: s.instructions.en,
      category: s.category,
    }) === canonical(call.proposal.after),
  );
  const a = object(r.audit, "id action entity_id created_at origin");
  identifier(a.id);
  check(
    a.action === "skill.created" &&
      a.entity_id === s.id &&
      a.id !== s.id &&
      a.origin === "local_operator" &&
      domainTimestamp(a.created_at),
  );
  check(utf8Length(canonical(value)) <= 32768);
}

export function parseActualSkill(value: unknown): Skill {
  const s = object(
    value,
    "id name description instructions version category status allowed_operations required_capabilities safety_rules",
  );
  if (s.status !== "template") return parseDraftSkill(value);
  // Finite source catalog, not a generic template-shaped object.
  for (const key of ["name", "description", "instructions"])
    object(s[key], "en ko");
  array(s.allowed_operations, 2);
  array(s.required_capabilities, 2);
  array(s.safety_rules, 2);
  s.safety_rules.forEach((r) => object(r, "en ko"));
  check(skillTemplates.some((t) => canonical(t) === canonical(value)));
  return value as Skill;
}
export type SkillInspection = {
  schema_version: 1;
  draft_revision: number;
  skill: Skill;
};
export class SkillReadbackMismatch extends Error {}
export function parseSkillInspection(value: unknown): SkillInspection {
  const v = object(value, "schema_version draft_revision skill");
  check(v.schema_version === 1);
  integer(v.draft_revision);
  object(
    v.skill,
    "id name description instructions version category status allowed_operations required_capabilities safety_rules",
  );
  try {
    parseActualSkill(v.skill);
  } catch {
    throw new SkillReadbackMismatch(
      "Skill record differs from the closed catalog/draft policy.",
    );
  }
  check(utf8Length(canonical(value)) <= 131072);
  return value as SkillInspection;
}

export type OperatorSkillSummary = Pick<
  Skill,
  "id" | "name" | "category" | "status" | "version"
>;
export type SkillInventory = {
  schema_version: 1;
  draft_revision: number;
  skills: OperatorSkillSummary[];
};
export function parseSkillInventory(value: unknown): SkillInventory {
  const v = object(value, "schema_version draft_revision skills");
  check(v.schema_version === 1);
  integer(v.draft_revision);
  array(v.skills, 103);
  check(v.skills.length >= skillTemplates.length);
  const ids = new Set();
  v.skills.forEach((value, index) => {
    const s = object(value, "id name category status version");
    identifier(s.id);
    check(!ids.has(s.id));
    ids.add(s.id);
    const name = object(s.name, "en ko");
    text(name.en, 120);
    text(name.ko, 120);
    check(
      s.version === "1.0.0" &&
        ["planning", "measurement", "analysis"].includes(s.category as string),
    );
    if (index < skillTemplates.length) {
      const { id, name, category, status, version } = skillTemplates[index];
      check(
        canonical(value) === canonical({ id, name, category, status, version }),
      );
    } else
      check(
        s.status === "draft" &&
          name.en === name.ko &&
          !skillTemplates.some((t) => t.id === s.id),
      );
  });
  check(utf8Length(canonical(value)) <= 131072);
  return value as SkillInventory;
}
