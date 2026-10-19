import { afterEach, expect, it, vi } from "vitest";
import { hash, call, gid, now } from "./chat-tool-test-fixtures";
import { parseTranscript } from "./chat-tool-wire";
import { toolClient } from "./chat-tool-client";
import {
  targetTranscript,
  targetSaved,
  target,
  inspection,
} from "./chat-target-test-fixtures";
import { response, tid } from "./chat-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("accepts exact target proposal/receipt through the shipped response decoder", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(targetTranscript)),
  );
  expect(await toolClient.tools(tid)).toEqual(targetTranscript);
});
it("reads actual bounded inventory and refuses duplicate IDs and raw excess bytes", async () => {
  const fetch = vi.fn(async () => response(inspection));
  vi.stubGlobal("fetch", fetch);
  expect(await toolClient.targets()).toEqual(inspection);
  expect(fetch.mock.calls[0]).toBeDefined();
  for (const body of [
    JSON.stringify({ ...inspection, targets: [target, target] }),
    JSON.stringify(inspection) + " ".repeat(131072),
    '{"schema_version":1,"schema_version":1}',
    JSON.stringify({ ...inspection, extra: true }),
  ]) {
    fetch.mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(toolClient.targets()).rejects.toThrow();
  }
});
it("refuses forged target receipts, proposals and audit linkage", async () => {
  for (const change of [
    { result: { ...targetSaved.result, after_revision: 2 } },
    {
      result: {
        ...targetSaved.result,
        target: { ...target, name: "different" },
      },
    },
    {
      result: {
        ...targetSaved.result,
        audit: { ...targetSaved.result.audit, entity_id: "foreign" },
      },
    },
    {
      result: {
        ...targetSaved.result,
        audit: {
          ...targetSaved.result.audit,
          created_at: "2026-10-18T01:00:01Z",
        },
      },
    },
    {
      proposal: { ...targetSaved.proposal, operation: "agent_profile_update" },
    },
    { proposal: { ...targetSaved.proposal, before: {} } },
    {
      proposal: {
        ...targetSaved.proposal,
        after: { ...targetSaved.proposal.after, id: "forged" },
      },
    },
    {
      result: {
        ...targetSaved.result,
        target: { ...target, status: "active" },
      },
    },
    {
      result: {
        ...targetSaved.result,
        target: { ...target, created_at: "not-a-time" },
      },
    },
  ])
    await expect(
      parseTranscript({
        ...targetTranscript,
        calls: [{ ...targetSaved, ...change }],
      }),
    ).rejects.toThrow();
});
it("target read variants retain their distinct pagination limits and literal identity", async () => {
  for (const args of [
    { kind: "targets", offset: 0, limit: 10 },
    { kind: "target", id: target.id },
  ]) {
    const result =
      args.kind === "targets"
        ? {
            kind: "targets",
            draft_revision: 3,
            items: [target],
            next_offset: 1,
          }
        : { kind: "target", draft_revision: 3, target };
    const read = {
      ...call,
      tool: "configuration_read",
      arguments: args,
      args_digest: hash(args),
      proposal: null,
      decision: null,
      status: "succeeded",
      result,
      finished_at: now,
    };
    expect(
      (await parseTranscript({ ...targetTranscript, calls: [read] })).calls[0]
        .result,
    ).toEqual(result);
    if (args.kind === "targets")
      for (const offset of [101, true, -1]) {
        const bad = { ...args, offset };
        await expect(
          parseTranscript({
            ...targetTranscript,
            calls: [{ ...read, arguments: bad, args_digest: hash(bad) }],
          }),
        ).rejects.toThrow();
      }
  }
});
it("rejects two attempted writes even without proposals, and raw escaped duplicate/numeric tokens", async () => {
  const failed = {
    ...targetSaved,
    status: "failed",
    proposal: null,
    decision: null,
    result: null,
    error_code: "CHAT_INVALID_REQUEST",
  };
  await expect(
    parseTranscript({
      ...targetTranscript,
      calls: [
        failed,
        { ...failed, id: gid, index: 1, provider_call_id: "another" },
      ],
    }),
  ).rejects.toThrow();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const raw = JSON.stringify(inspection);
  for (const body of [
    raw.replace('"draft_revision":3', '"draft_revision":3.0'),
    raw.replace('"draft_revision":3', '"draft_revision":true'),
    raw.replace(
      '"id":"target-legacy"',
      '"id":"target-legacy","\\u0069d":"other"',
    ),
  ]) {
    fetch.mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(toolClient.targets()).rejects.toThrow();
  }
});
it.each(["target\n", "target\r", "target\u2028", "target\u2029"])(
  "rejects non-Identifier line terminators: %j",
  async (id) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response({ ...inspection, targets: [{ ...target, id }] }),
      ),
    );
    await expect(toolClient.targets()).rejects.toThrow();
  },
);
it("admits full 100-target bounded inventory and safe counter ceiling; refuses 101", async () => {
  const targets = Array.from({ length: 100 }, (_, i) => ({
    ...target,
    id: `target-${i}`,
    name: "🌍".repeat(120),
  }));
  const fetch = vi.fn(async () =>
    response({
      ...inspection,
      draft_revision: Number.MAX_SAFE_INTEGER,
      targets,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  expect((await toolClient.targets()).targets).toHaveLength(100);
  targets.push({ ...target, id: "target-100" });
  await expect(toolClient.targets()).rejects.toThrow();
});
