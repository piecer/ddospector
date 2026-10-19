import { expect, it } from "vitest";
import {
  cloneSkillSelection,
  skillSelectionFromLocation,
  skillSelectionPath,
} from "./skill-selection";
import { draft } from "../pages/ai/chat-skill-test-fixtures";
import { canonical, utf8Length } from "../pages/scenarios/json";
it("U6 clones and freezes every receipt child without trusting aliases", () => {
  const input = {
    id: draft.id,
    expectation: {
      skill: JSON.parse(JSON.stringify(draft)),
      after_revision: 3,
    },
  };
  const owned = cloneSkillSelection(input);
  expect(skillSelectionPath(owned)).toBe(`/skills?skill=${draft.id}`);
  input.expectation.skill.name.en = "altered";
  input.expectation.skill.safety_rules[0].ko = "altered";
  expect(owned.expectation!.skill).toEqual(draft);
  function frozen(v: unknown) {
    if (v && typeof v === "object") {
      expect(Object.isFrozen(v)).toBe(true);
      Object.values(v).forEach(frozen);
    }
  }
  frozen(owned);
});
it("U6 URL selection is exact ID only and rejects malformed duplicate or extra authority", () => {
  for (const search of [
    "?skill=x&skill=x",
    "?skill=x&expectation=x",
    "?skill=%zz",
    "?skill=X",
    "?skill=x%0A",
    "?other=x",
    "?skill=x/y",
  ])
    expect(
      skillSelectionFromLocation({ pathname: "/skills", search }),
    ).toBeUndefined();
  expect(
    skillSelectionFromLocation({
      pathname: "/skills",
      search: "?skill=policy-validation",
    }),
  ).toEqual({ id: "policy-validation" });
  expect(
    skillSelectionFromLocation({ pathname: "/targets", search: "?skill=x" }),
  ).toBeUndefined();
  for (const value of [
    { id: "other", expectation: { skill: draft, after_revision: 3 } },
    {
      id: draft.id,
      expectation: {
        skill: { ...draft, created_at: "invented" },
        after_revision: 3,
      },
    },
    { id: draft.id, expectation: { skill: draft, after_revision: true } },
  ])
    expect(() => cloneSkillSelection(value)).toThrow();
});
it("U6 U10 enforces exact UTF8 32KiB expectation including safety metadata", () => {
  const make = (n: number) => ({
    id: draft.id,
    expectation: {
      skill: {
        ...draft,
        instructions: { en: "x".repeat(n), ko: "x".repeat(n) },
      },
      after_revision: 3,
    },
  });
  const big = make(8000);
  big.expectation.skill.instructions = {
    en: "🌍".repeat(4000),
    ko: "🌍".repeat(4000),
  };
  expect(utf8Length(canonical(big.expectation))).toBeGreaterThan(32768);
  expect(() => cloneSkillSelection(big)).toThrow();
  expect(
    cloneSkillSelection(make(8000)).expectation!.skill.instructions.en.length,
  ).toBe(8000);
});

it("U6 exact 32768-byte expectation accepts and valid +1-byte ID refuses", () => {
  const skill = {
    ...draft,
    id: "s",
    instructions: { en: "🌍".repeat(3500), ko: "🌍".repeat(3500) },
  };
  const e = { skill, after_revision: 3 };
  let needed = 32768 - utf8Length(canonical(e));
  if (needed % 2) {
    skill.id += "s";
    needed--;
  }
  skill.instructions.en += "x".repeat(needed / 2);
  skill.instructions.ko = skill.instructions.en;
  expect(utf8Length(canonical(e))).toBe(32768);
  expect(
    cloneSkillSelection({ id: skill.id, expectation: e }).expectation,
  ).toEqual(e);
  skill.id += "s";
  expect(utf8Length(canonical(e))).toBe(32769);
  expect(() => cloneSkillSelection({ id: skill.id, expectation: e })).toThrow();
});
