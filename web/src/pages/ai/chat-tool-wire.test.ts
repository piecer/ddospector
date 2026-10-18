import { expect, it } from "vitest";
import * as wire from "./chat-wire";
import * as tools from "./chat-tool-wire";
import {
  call,
  transcript,
  savedCall,
  decision,
  grant,
  hash,
} from "./chat-tool-test-fixtures";
const parser = tools as unknown as {
  parseTranscript(v: unknown): Promise<unknown>;
  parseGrant(v: unknown): unknown;
};
it.each([
  ["requested", null, null, null],
  ["executing", decision, null, null],
  [
    "denied",
    { ...decision, decision: "deny" },
    "CHAT_TOOL_DENIED",
    call.started_at,
  ],
  ["denied", null, "CHAT_TOOL_WRITE_FENCED", call.started_at],
  ["conflict", decision, "CHAT_TOOL_CONFLICT", call.started_at],
  ["failed", null, "CHAT_TIMEOUT", call.started_at],
  ["failed", decision, "CHAT_INVALID_REQUEST", call.started_at],
  ["uncertain", decision, "CHAT_TOOL_UNCERTAIN", call.started_at],
  ["cancelled", null, "CHAT_CANCELLED", call.started_at],
])(
  "closed A1 write outcome %s has factual code/decision/null relationships",
  async (status, d, code, finished) => {
    const witness = {
      ...transcript,
      calls: [
        {
          ...call,
          status,
          proposal: status === "requested" ? null : call.proposal,
          decision: d,
          error_code: code,
          finished_at: finished,
        },
      ],
    };
    expect(await parser.parseTranscript(witness)).toEqual(witness);
    if (code)
      await expect(
        parser.parseTranscript({
          ...witness,
          calls: [{ ...witness.calls[0], error_code: "CHAT_PROVIDER_ERROR" }],
        }),
      ).rejects.toThrow();
  },
);
it("Skill detail and list results preserve literal identifiers, UTF8 budgets, ordered paging and closed nested keys", async () => {
  const args = { kind: "skill", id: "literal-id" };
  const detail = {
    id: "literal-id",
    name: " 이름 ",
    category: "analysis",
    status: "draft",
    version: "1.0.0",
    description: "description",
    instructions: "<img src=x> untrusted data",
  };
  const read = {
    ...call,
    tool: "configuration_read",
    arguments: args,
    args_digest: hash(args),
    status: "succeeded",
    proposal: null,
    result: { kind: "skill", draft_revision: 2, skill: detail },
    finished_at: call.started_at,
  };
  expect(
    await parser.parseTranscript({ ...transcript, calls: [read] }),
  ).toBeTruthy();
  for (const skill of [
    { ...detail, id: "foreign-id" },
    {
      ...detail,
      instructions: "😀".repeat(8000),
      description: "😀".repeat(1000),
    },
    { ...detail, extra: "authority" },
    { ...detail, name: "name\u200b" },
    { ...detail, version: "2.0.0" },
  ])
    await expect(
      parser.parseTranscript({
        ...transcript,
        calls: [{ ...read, result: { ...read.result, skill } }],
      }),
    ).rejects.toThrow();
  const listArgs = { kind: "skills", offset: 0, limit: 1 };
  const list = {
    ...read,
    arguments: listArgs,
    args_digest: hash(listArgs),
    result: {
      kind: "skills",
      draft_revision: 2,
      items: [
        {
          id: detail.id,
          name: detail.name,
          category: detail.category,
          status: detail.status,
          version: detail.version,
        },
      ],
      next_offset: 1,
    },
  };
  expect(
    await parser.parseTranscript({ ...transcript, calls: [list] }),
  ).toBeTruthy();
  await expect(
    parser.parseTranscript({
      ...transcript,
      calls: [{ ...list, result: { ...list.result, next_offset: 2 } }],
    }),
  ).rejects.toThrow();
  await expect(
    parser.parseTranscript({ ...transcript, calls: Array(4).fill(call) }),
  ).rejects.toThrow();
});
it("admits bound authoritative calls and rejects forged/impossible saved facts", async () => {
  expect(await parser.parseTranscript(transcript)).toEqual(transcript);
  expect(
    await parser.parseTranscript({ ...transcript, calls: [savedCall] }),
  ).toEqual({ ...transcript, calls: [savedCall] });
  expect(parser.parseGrant(grant)).toEqual(grant);
  for (const delta of [
    { extra: 1 },
    { index: true },
    { args_digest: "0".repeat(64) },
    { actor: "model" },
    { status: "executing" },
    { status: "succeeded" },
    { decision },
    { finished_at: call.started_at },
    { proposal: { ...call.proposal, digest: "a".repeat(64) } },
    { arguments: { ...call.arguments, skill_ids: ["bad_id"] } },
  ])
    await expect(
      parser.parseTranscript({ ...transcript, calls: [{ ...call, ...delta }] }),
    ).rejects.toThrow();
  for (const delta of [
    { decision: null },
    { result: { ...savedCall.result, after_revision: 4 } },
    { result: { ...savedCall.result, agent_profile: call.proposal.before } },
    {
      result: {
        ...savedCall.result,
        audit: { ...savedCall.result.audit, action: "skill.created" },
      },
    },
  ])
    await expect(
      parser.parseTranscript({
        ...transcript,
        calls: [{ ...savedCall, ...delta }],
      }),
    ).rejects.toThrow();
  const readArgs = { kind: "agent_profile" };
  const read = {
    ...call,
    tool: "configuration_read",
    arguments: readArgs,
    args_digest: hash(readArgs),
    status: "succeeded",
    proposal: null,
    result: {
      kind: "agent_profile",
      draft_revision: 2,
      agent_profile: call.proposal.before,
    },
    finished_at: call.started_at,
  };
  expect(
    await parser.parseTranscript({ ...transcript, calls: [read] }),
  ).toBeTruthy();
  await expect(
    parser.parseTranscript({ ...transcript, calls: [{ ...read, decision }] }),
  ).rejects.toThrow();
  for (const delta of [
    { status: "approved" },
    { read_scope: ["shell"] },
    { expected_sequence: true },
    { extra: null },
  ])
    expect(() => parser.parseGrant({ ...grant, ...delta })).toThrow();
});
const parseRuntime = (value: unknown) =>
  (
    wire as unknown as { parseToolRuntime(v: unknown): unknown }
  ).parseToolRuntime(value);
export const toolRuntime = {
  schema_version: 1,
  mode: "operator_approved_settings",
  supported: true,
  reason: null,
  tools: ["configuration_read", "agent_profile_update"],
  max_calls: 3,
  max_writes: 1,
  requires_write_approval: true,
};
it("a denied write cannot retain an approve Decision", async () => {
  await expect(
    parser.parseTranscript({
      ...transcript,
      calls: [
        {
          ...call,
          status: "denied",
          decision,
          error_code: "CHAT_TOOL_WRITE_FENCED",
          finished_at: call.started_at,
        },
      ],
    }),
  ).rejects.toThrow();
});
it("canonical identifiers and digests reject trailing line terminators literally", async () => {
  await expect(
    parser.parseTranscript({
      ...transcript,
      turn_id: transcript.turn_id + "\n",
    }),
  ).rejects.toThrow();
  expect(() =>
    parser.parseGrant({ ...grant, profile_id: grant.profile_id + "\n" }),
  ).toThrow();
  const args = { kind: "skill", id: "literal-id\n" };
  const read = {
    ...call,
    tool: "configuration_read",
    arguments: args,
    args_digest: hash(args),
    status: "requested",
    proposal: null,
  };
  await expect(
    parser.parseTranscript({ ...transcript, calls: [read] }),
  ).rejects.toThrow();
  expect(() =>
    tools.parseDecision({
      ...decision,
      proposal_digest: decision.proposal_digest + "\n",
    }),
  ).toThrow();
});
it("closed runtime arrays reject hidden keys and accessors without executing them", () => {
  let reads = 0;
  const list = [...toolRuntime.tools];
  Object.defineProperty(list, "hidden", { value: true });
  expect(() => parseRuntime({ ...toolRuntime, tools: list })).toThrow();
  const getter = [...toolRuntime.tools];
  Object.defineProperty(getter, "0", {
    enumerable: true,
    get: () => {
      reads++;
      return "configuration_read";
    },
  });
  expect(() => parseRuntime({ ...toolRuntime, tools: getter })).toThrow();
  expect(reads).toBe(0);
});
it("admits only the frozen separate read/propose runtime without changing v1", () => {
  expect(parseRuntime(toolRuntime)).toEqual(toolRuntime);
  for (const delta of [
    { extra: true },
    { max_calls: true },
    { max_writes: 2 },
    { requires_write_approval: false },
    { tools: ["shell"] },
    { reason: "UNKNOWN" },
  ])
    expect(() => parseRuntime({ ...toolRuntime, ...delta })).toThrow();
});
