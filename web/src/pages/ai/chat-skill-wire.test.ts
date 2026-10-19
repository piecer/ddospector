import { expect, it } from "vitest";
import { canonical, utf8Length } from "../scenarios/json";
import { hash, cid, gid, expiry } from "./chat-tool-test-fixtures";
import { parseDraftSkill } from "./chat-skill-wire";
import { parseTranscript } from "./chat-tool-wire";
import {
  skillTranscript,
  skillSaved,
  draft,
  skillInput,
} from "./chat-skill-test-fixtures";
it("U1 accepts a complete ten-field Skill receipt with literal locales and separate audit", async () => {
  expect((await parseTranscript(skillTranscript)).calls[0]).toEqual(skillSaved);
});

it("U1 rejects every missing/additional full record key and forged locale/policy/result/audit/proposal graph", async () => {
  for (const key of Object.keys(draft)) {
    const bad = { ...draft } as Record<string, unknown>;
    delete bad[key];
    expect(() => parseDraftSkill(bad)).toThrow();
  }
  for (const bad of [
    { ...draft, created_at: "invented" },
    { ...draft, name: { ...draft.name, ko: "translation" } },
    { ...draft, status: "template" },
    { ...draft, version: "2.0.0" },
    { ...draft, allowed_operations: ["run"] },
    { ...draft, required_capabilities: ["shell"] },
    { ...draft, safety_rules: [] },
    { ...draft, id: "policy-validation" },
  ])
    expect(() => parseDraftSkill(bad)).toThrow();
  for (const changes of [
    { result: { ...skillSaved.result, kind: "target_created" } },
    { result: { ...skillSaved.result, after_revision: 5 } },
    { result: { ...skillSaved.result, before_revision: 1 } },
    {
      result: {
        ...skillSaved.result,
        audit: { ...skillSaved.result.audit, entity_id: "foreign" },
      },
    },
    {
      result: {
        ...skillSaved.result,
        audit: { ...skillSaved.result.audit, action: "target.created" },
      },
    },
    {
      result: {
        ...skillSaved.result,
        audit: {
          ...skillSaved.result.audit,
          created_at: "2026-02-30T00:00:00Z",
        },
      },
    },
    {
      result: {
        ...skillSaved.result,
        audit: { ...skillSaved.result.audit, origin: "model" },
      },
    },
    {
      result: {
        ...skillSaved.result,
        skill: { ...draft, category: "analysis" },
      },
    },
    { proposal: { ...skillSaved.proposal, operation: "target_create" } },
    { proposal: { ...skillSaved.proposal, before: {} } },
    {
      proposal: {
        ...skillSaved.proposal,
        after: { ...skillInput, description: "changed" },
      },
    },
    { proposal: { ...skillSaved.proposal, digest: "a".repeat(64) } },
    { decision: { ...skillSaved.decision, proposal_digest: "a".repeat(64) } },
  ])
    await expect(
      parseTranscript({
        ...skillTranscript,
        calls: [{ ...skillSaved, ...changes }],
      }),
    ).rejects.toThrow();
});
it("U1 Skill audit timestamp is independent; a valid distinct time is preserved", async () => {
  const saved = {
    ...skillSaved,
    result: {
      ...skillSaved.result,
      audit: { ...skillSaved.result.audit, created_at: "2026-10-18T01:00:01Z" },
    },
  };
  expect(
    (await parseTranscript({ ...skillTranscript, calls: [saved] })).calls[0]
      .result,
  ).toEqual(saved.result);
});
it("U10 reconstructs raw arguments fitting 16KiB while the complete bilingual receipt exceeds 32KiB", async () => {
  const input = {
    ...skillInput,
    name: "x",
    description: "x",
    instructions: "🌍".repeat(4000),
  };
  const args = { expected_draft_revision: 2, ...input };
  const proposal = {
    operation: "skill_create",
    expected_draft_revision: 2,
    before: null,
    after: input,
    expires_at: expiry,
  };
  const digest = hash({ call_id: cid, grant_id: gid, ...proposal });
  const skill = {
    ...draft,
    name: { en: input.name, ko: input.name },
    description: { en: input.description, ko: input.description },
    instructions: { en: input.instructions, ko: input.instructions },
  };
  const result = { ...skillSaved.result, skill };
  expect(utf8Length(canonical(args))).toBeLessThanOrEqual(16384);
  expect(utf8Length(canonical(result))).toBeGreaterThan(32768);
  const saved = {
    ...skillSaved,
    arguments: args,
    args_digest: hash(args),
    proposal: { ...proposal, digest },
    decision: { ...skillSaved.decision, proposal_digest: digest },
    result,
  };
  await expect(
    parseTranscript({ ...skillTranscript, calls: [saved] }),
  ).rejects.toThrow();
  // This is a consumer rejection witness, NOT evidence of backend prospective admission.
});
it("U1 finite write slot includes Skill even without proposal", async () => {
  const failed = {
    ...skillSaved,
    status: "failed",
    error_code: "CHAT_INVALID_REQUEST",
    proposal: null,
    decision: null,
    result: null,
  };
  await expect(
    parseTranscript({
      ...skillTranscript,
      calls: [
        failed,
        { ...failed, id: gid, index: 1, provider_call_id: "second" },
      ],
    }),
  ).rejects.toThrow();
});

it("U10 exact full result 32768 accepts and valid +1 byte audit ID rejects", async () => {
  function make(id: string, n: number) {
    const input = {
      ...skillInput,
      instructions: "🌍".repeat(3500) + "x".repeat(n),
    };
    const args = { expected_draft_revision: 2, ...input };
    const proposal = {
      operation: "skill_create",
      expected_draft_revision: 2,
      before: null,
      after: input,
      expires_at: expiry,
    };
    const digest = hash({ call_id: cid, grant_id: gid, ...proposal });
    const result = {
      ...skillSaved.result,
      skill: {
        ...draft,
        id,
        instructions: { en: input.instructions, ko: input.instructions },
      },
      audit: { ...skillSaved.result.audit, entity_id: id },
    };
    return {
      ...skillSaved,
      arguments: args,
      args_digest: hash(args),
      proposal: { ...proposal, digest },
      decision: { ...skillSaved.decision, proposal_digest: digest },
      result,
    };
  }
  // ID appears twice (record + audit entity); choose audit ID parity independently.
  let exact = make("s", 0);
  const base = utf8Length(canonical(exact.result));
  const parity = (32768 - base) % 2;
  const n = (32768 - base - parity) / 2;
  exact = make("s", n);
  if (parity) exact.result.audit.id += "x";
  expect(utf8Length(canonical(exact.result))).toBe(32768);
  expect(utf8Length(canonical(exact.arguments))).toBeLessThanOrEqual(16384);
  expect(
    (await parseTranscript({ ...skillTranscript, calls: [exact] })).calls[0]
      .result,
  ).toEqual(exact.result);
  exact.result.audit.id += "x";
  expect(utf8Length(canonical(exact.result))).toBe(32769);
  await expect(
    parseTranscript({ ...skillTranscript, calls: [exact] }),
  ).rejects.toThrow();
});
