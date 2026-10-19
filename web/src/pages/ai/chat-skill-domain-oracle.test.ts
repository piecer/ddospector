import { afterEach, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { ChatRequestError } from "./chat-client";
import { toolClient } from "./chat-tool-client";
import {
  parseDraftSkill,
  parseSkillInput,
  parseActualSkill,
} from "./chat-skill-wire";
import { skillSafety, skillTemplates } from "./chat-skill-catalog";
import { draft, skillInput, skillInspection } from "./chat-skill-test-fixtures";
import { response } from "./chat-test-fixtures";
import { canonical, utf8Length } from "../scenarios/json";
const root = resolve("..");
function oracle(code: string, input?: unknown) {
  return JSON.parse(
    execFileSync(
      resolve(root, ".venv/bin/python"),
      [
        "-c",
        `import aiddos.api.catalog as c; import aiddos.api.models as m; import json,sys; from pathlib import Path; assert Path(c.__file__).resolve().is_relative_to(Path(${JSON.stringify(root)})); assert Path(m.__file__).resolve().is_relative_to(Path(${JSON.stringify(root)})); ${code}`,
      ],
      {
        input: JSON.stringify(input),
        encoding: "utf8",
        env: {
          ...process.env,
          PYTHONPATH: `${root}/src:${root}`,
          PYTHONDONTWRITEBYTECODE: "1",
        },
      },
    ),
  );
}
afterEach(() => vi.unstubAllGlobals());
it("U1 source-bound exact finite catalog and safety literals match actual Python DTOs", () => {
  const actual = oracle(
    "print(json.dumps({'templates':c.SKILLS_V1,'safety':c.SAFETY_RULES}))",
  );
  expect(actual).toEqual({ templates: skillTemplates, safety: skillSafety });
  for (const t of actual.templates) expect(parseActualSkill(t)).toEqual(t);
  for (const t of actual.templates) {
    expect(() =>
      parseActualSkill({
        ...t,
        description: { ...t.description, ko: "forged" },
      }),
    ).toThrow();
    expect(() => parseDraftSkill({ ...draft, id: t.id })).toThrow();
  }
  expect(() => parseActualSkill({ ...draft, status: "template" })).toThrow();
});
it("U1 Python codepoint, blank and Cc Cf Cs parity retains exact literals", () => {
  const cases = [
    skillInput,
    { ...skillInput, name: "🌍".repeat(120) },
    { ...skillInput, name: "🌍".repeat(121) },
    { ...skillInput, description: "x\n\r\t" },
    ...["\u001c", "\u200b", "\ud800", "\ufeff", "\u0085"].flatMap((c) => [
      { ...skillInput, name: "x" + c },
      { ...skillInput, instructions: "x" + c },
    ]),
    { ...skillInput, name: "\u00a0" },
    { ...skillInput, name: " \u0301 " },
  ];
  const actual = oracle(
    "values=json.load(sys.stdin)\nresults=[]\nfor v in values:\n try: results.append(m.SkillInput.model_validate(v).model_dump())\n except ValueError: results.append(None)\nprint(json.dumps(results))",
    cases,
  );
  cases.forEach((v, i) => {
    if (actual[i] === null) expect(() => parseSkillInput(v)).toThrow();
    else expect(parseSkillInput(v)).toEqual(actual[i]);
  });
});
it("U10 maximum manual Skill remains readable at 128KiB but full chat receipt cannot fit 32KiB", async () => {
  const full = {
    ...draft,
    name: { en: "🌍".repeat(120), ko: "🌍".repeat(120) },
    description: { en: "🌍".repeat(1000), ko: "🌍".repeat(1000) },
    instructions: { en: "🌍".repeat(8000), ko: "🌍".repeat(8000) },
  };
  expect(parseDraftSkill(full)).toEqual(full);
  const inspection = { ...skillInspection, skill: full };
  expect(utf8Length(canonical(full))).toBeGreaterThan(32768);
  expect(utf8Length(canonical(inspection))).toBeLessThan(131072);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(inspection)),
  );
  expect(await toolClient.skill(full.id)).toEqual(inspection);
});
it("U8 U10 single detail binds requested ID and rejects raw boundary+1 duplicate and numeric tokens", async () => {
  const raw = JSON.stringify(skillInspection);
  const fetch = vi.fn(async () => response(skillInspection));
  vi.stubGlobal("fetch", fetch);
  expect(await toolClient.skill(draft.id)).toEqual(skillInspection);
  await expect(toolClient.skill("other-id")).rejects.toThrow();
  for (const id of ["bad?query", "a/b", "x\n", "x\r"])
    await expect(toolClient.skill(id)).rejects.toThrow();
  for (const body of [
    raw + " ".repeat(131073 - utf8Length(raw)),
    raw.replace('"draft_revision":3', '"draft_revision":3.0'),
    raw.replace('"draft_revision":3', '"draft_revision":3e0'),
    raw.replace('"draft_revision":3', '"draft_revision":true'),
    raw.replace(
      '"draft_revision":3',
      '"draft_revision":3,"draft_\\u0072evision":3',
    ),
  ]) {
    fetch.mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(toolClient.skill(draft.id)).rejects.toThrow();
  }
  fetch.mockResolvedValue(
    new Response(raw + " ".repeat(131072 - utf8Length(raw)), {
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(await toolClient.skill(draft.id)).toEqual(skillInspection);
});

it("U10 error responses share the Skill operator raw 128KiB cap", async () => {
  const body = JSON.stringify({
    code: "CHAT_NOT_FOUND",
    message: "x".repeat(131072),
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(body, {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  const error = await toolClient.skill(draft.id).catch((e) => e);
  expect(error).toBeInstanceOf(Error);
  expect(error).not.toBeInstanceOf(ChatRequestError);
});
