import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { chatClient } from "./chat-client";
import { toolClient } from "./chat-tool-client";
import { parseSession } from "./chat-wire";
import { parseGrant } from "./chat-tool-wire";
import { canonical, digest } from "../scenarios/json";
import {
  cloneTargetSelection,
  targetSelectionFromLocation,
  targetSelectionPath,
} from "../../lib/target-selection";

// Inherited actual HTTP bodies, not regenerated JSON or a new producer run.
// Only fetch transport is replaced. All positive bodies enter real Response ->
// chatJSON/decodeJSON -> shipped client validation, including lexical admission.
type Raw = { raw_utf8: string; sha256: string; bytes: number };
type Row = Raw & {
  file: string;
  method: string;
  path: string;
  status: number;
  content_type: string;
};
type Input = { path: string; sha256: string; mode: string };
type Corpus = {
  schema_version: number;
  provenance: {
    kind: string;
    verdict: string;
    synthetic_provider_requests: number;
    real_model_requests: number;
    source_sha256: string;
  };
  evidence: Record<string, Raw>;
  producer_inputs: Input[];
  responses: Row[];
  ordered_response_sha256: string;
};
const sha = (value: string | Uint8Array) =>
  createHash("sha256").update(value).digest("hex");
const fixture = readFileSync(
  resolve("src/pages/ai/chat-target-producer-data/producer.json"),
);
if (
  sha(fixture) !==
  "82dda5e1345d4ce12a976666df873cc932b9217afee63812fc0ef27bad5146ba"
)
  throw new Error("Changed inherited target capture bundle");
const corpus = JSON.parse(fixture.toString("utf8")) as Corpus;
function guardedRaw(value: Raw) {
  const bytes = Buffer.from(value.raw_utf8, "utf8");
  expect(bytes.length).toBe(value.bytes);
  expect(sha(bytes)).toBe(value.sha256);
  return value.raw_utf8;
}
function row(index: number) {
  const value = corpus.responses[index];
  expect(value.file).toBe(
    `chat_target_http_${String(index).padStart(4, "0")}.json`,
  );
  guardedRaw(value);
  return value;
}
// JSON.parse is used only for expectations and request bindings, NEVER to create
// a positive response body. Captured request bodies were not retained by author.
const expected = (index: number) => JSON.parse(guardedRaw(row(index)));
const session = parseSession(expected(1));
const grant = parseGrant(expected(5));
const turn = expected(8);
const text: string = turn.user_text;
const grantBody = {
  schema_version: 2,
  scope: "target_create",
  request_id: grant.request_id,
  session_id: session.id,
  turn_request_id: grant.turn_request_id,
  expected_sequence: session.sequence,
  text,
};
const decision = expected(14);
const decisionBody = {
  request_id: decision.request_id,
  proposal_digest: decision.proposal_digest,
  decision: decision.decision,
};
type Replay = { index: number; raw?: string; body?: unknown };
let remaining: Replay[] = [];
function replay(...entries: Replay[]) {
  expect(remaining).toHaveLength(0);
  remaining = [...entries];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const next = remaining.shift();
    expect(next, `Unexpected fetch: ${url}`).toBeDefined();
    if (!next) throw new Error("No captured response for request");
    const captured = row(next.index);
    expect(url).toBe(captured.path);
    expect(init?.method).toBe(captured.method);
    expect(init?.cache).toBe("no-store");
    expect(init?.redirect).toBe("error");
    if (next.body !== undefined)
      expect(JSON.parse(String(init?.body))).toEqual(next.body);
    else if (captured.method === "GET") expect(init?.body).toBeUndefined();
    return new Response(next.raw ?? guardedRaw(captured), {
      status: captured.status,
      headers: { "content-type": captured.content_type },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => {
  vi.unstubAllGlobals();
  expect(remaining).toHaveLength(0);
});
const recover = (authority: "agent_v1" | "target_create_v2") =>
  toolClient.recoverGrant(
    session,
    grant.request_id,
    grant.turn_request_id,
    text,
    authority,
  );
const issue = (authority: "agent_v1" | "target_create_v2") =>
  toolClient.grant(
    session,
    grant.request_id,
    grant.turn_request_id,
    text,
    authority,
  );

it("binds all 23 exact bodies and inherited capture evidence to unchanged producer inputs", () => {
  expect(corpus.schema_version).toBe(1);
  expect(corpus.provenance.kind).toBe(
    "inherited_actual_http_capture_not_new_runtime",
  );
  expect(corpus.provenance.verdict).toBe(
    "ACTUAL_PRODUCER_CAPTURE_NOT_REAL_MODEL",
  );
  expect(corpus.provenance.synthetic_provider_requests).toBe(3);
  expect(corpus.provenance.real_model_requests).toBe(0);
  const capture = JSON.parse(
    guardedRaw(corpus.evidence["capture-result.json"]),
  );
  const pre = guardedRaw(corpus.evidence["source-pre.json"]);
  expect(guardedRaw(corpus.evidence["source-post.json"])).toBe(pre);
  const inputs = JSON.parse(pre) as Input[];
  expect(sha(canonical(inputs))).toBe(capture.source_sha256);
  expect(corpus.provenance.source_sha256).toBe(capture.source_sha256);
  expect(capture.verdict).toBe(corpus.provenance.verdict);
  expect(capture.cleanup.cleanup_verified).toBe(true);
  expect(capture.provider_handlers_closed).toBe(true);
  expect(capture.synthetic_provider_requests).toBe(3);
  expect(capture.real_model_requests).toBe(0);
  expect(corpus.responses).toHaveLength(23);
  expect(
    corpus.responses.map(({ raw_utf8: _raw, ...metadata }) => {
      void _raw;
      return metadata;
    }),
  ).toEqual(capture.captures);
  const bytes = corpus.responses.map((value) =>
    Buffer.from(guardedRaw(value), "utf8"),
  );
  expect(bytes.reduce((total, value) => total + value.length, 0)).toBe(50466);
  expect(sha(Buffer.concat(bytes))).toBe(corpus.ordered_response_sha256);
  expect(corpus.ordered_response_sha256).toBe(
    "4d596d3e64473d86c1bb4592d923d3dad1e6c852f69659041129f62bc8c9ce94",
  );
  // Pin producing Python/dependencies/harness, not unrelated mutable frontend.
  // Full original source manifest remains intact above as historical evidence.
  expect(corpus.producer_inputs).toHaveLength(92);
  for (const input of corpus.producer_inputs) {
    expect(inputs.find((entry) => entry.path === input.path)).toEqual(input);
    const path = resolve("..", input.path);
    expect(sha(readFileSync(path)), input.path).toBe(input.sha256);
    expect(`0o${(statSync(path).mode & 0o777).toString(8)}`, input.path).toBe(
      input.mode,
    );
  }
  expect(row(4).path).toBe("/api/v1/chat/tools/runtime");
  expect(row(8).path).toBe(`/api/v1/chat/sessions/${session.id}/tool-turns`);
});

it("consumes actual chat bootstrap and v2 tool runtime through shipped clients", async () => {
  replay({ index: 0 }, { index: 1 }, { index: 4 });
  const runtime = await chatClient.runtime();
  expect(await chatClient.start(runtime, session.request_id, "ko")).toEqual(
    session,
  );
  const tools = await toolClient.runtime();
  expect(tools).toEqual(expected(4));
  expect(tools.schema_version).toBe(2);
  expect(tools.tools).toEqual([
    "configuration_read",
    "agent_profile_update",
    "target_create",
  ]);
});

it.each([5, 6])(
  "binds actual target grant POST response %i to the exact request",
  async (index) => {
    replay({ index, body: grantBody });
    expect(await issue("target_create_v2")).toEqual(grant);
    expect(grant.schema_version).toBe(2);
    expect(grant.text_sha256).toBe(await digest(text));
  },
);
it("binds actual GET-by-request grant without a new POST", async () => {
  const fetch = replay({ index: 7 });
  expect(await recover("target_create_v2")).toEqual(grant);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("rejects genuine target authority on Agent POST and GET recovery", async () => {
  const { schema_version: _version, scope: _scope, ...agentBody } = grantBody;
  void _version;
  void _scope;
  const fetch = replay(
    { index: 5, body: agentBody },
    { index: 7 },
    { index: 7 },
  );
  await expect(issue("agent_v1")).rejects.toThrow();
  await expect(recover("agent_v1")).rejects.toThrow();
  expect(fetch.mock.calls.every(([url]) => !url.includes("tool-turns"))).toBe(
    true,
  );
});
it("rebinds actual target grant before submit; opposite authority dispatches nothing", async () => {
  const fetch = replay();
  await expect(
    toolClient.submit(session, grant, text, () => true, "agent_v1"),
  ).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
  replay({
    index: 8,
    body: {
      request_id: grant.turn_request_id,
      expected_sequence: session.sequence,
      text,
      grant_id: grant.id,
    },
  });
  expect(
    await toolClient.submit(
      session,
      grant,
      text,
      () => true,
      "target_create_v2",
    ),
  ).toEqual(turn);
});

it.each([10, 11, 12, 17, 20])(
  "accepts unmodified actual transcript bytes %i",
  async (index) => {
    replay({ index });
    expect(await toolClient.tools(turn.id)).toEqual(expected(index));
  },
);
it("binds actual pending proposal, canonical digest and explicit decision receipt", async () => {
  replay({ index: 12 }, { index: 14, body: decisionBody });
  const pending = await toolClient.tools(turn.id);
  const call = pending.calls[1];
  const proposal = call.proposal!;
  expect(call.status).toBe("awaiting_approval");
  expect(call.result).toBeNull();
  expect(call.decision).toBeNull();
  expect(expected(13)).toEqual(expected(3)); // actual preapproval workspace unchanged
  expect(pending.calls[0].result).toEqual({
    kind: "targets",
    draft_revision: expected(3).meta.audit_retention.total_recorded,
    items: expected(3).targets,
    next_offset: null,
  });
  expect(proposal.before).toBeNull();
  expect("operation" in proposal && proposal.operation).toBe("target_create");
  expect(proposal.digest).toBe(
    await digest({
      call_id: call.id,
      grant_id: call.grant_id,
      operation: "target_create",
      expected_draft_revision: proposal.expected_draft_revision,
      before: null,
      after: proposal.after,
      expires_at: proposal.expires_at,
    }),
  );
  expect(call.args_digest).toBe(await digest(call.arguments));
  expect(await toolClient.decide(call.id, turn.id, decisionBody)).toEqual(
    decision,
  );
});
it("retains complete saved Target/audit/revisions across actual restart and inventory reads", async () => {
  replay(
    { index: 17 },
    { index: 20 },
    { index: 19 },
    { index: 22 },
    { index: 16 },
  );
  const saved = await toolClient.tools(turn.id);
  const restarted = await toolClient.tools(turn.id);
  expect(guardedRaw(row(17))).toBe(guardedRaw(row(20)));
  expect(restarted).toEqual(saved);
  expect(saved.revision).toBe(7);
  const call = saved.calls[1];
  expect(call.status).toBe("succeeded");
  expect(call.error_code).toBeNull();
  expect(call.decision).toEqual(decision);
  expect(call.result).toEqual(expected(17).calls[1].result);
  const receipt = call.result;
  if (receipt?.kind !== "target_created")
    throw new Error("Missing actual saved receipt");
  expect(Object.keys(receipt.target).sort()).toEqual([
    "address",
    "created_at",
    "id",
    "kind",
    "name",
    "status",
  ]);
  expect(Object.keys(receipt.audit).sort()).toEqual([
    "action",
    "created_at",
    "entity_id",
    "id",
    "origin",
  ]);
  expect(receipt.target.name).toBe("CHAT02B1 승인된 대상 🌍");
  expect(receipt.target.address).toBe("Example.COM.");
  expect(receipt.target.kind).toBe("DUT");
  expect(receipt.target.status).toBe("draft");
  expect(receipt.before_revision).toBe(call.proposal!.expected_draft_revision);
  expect(receipt.after_revision).toBe(receipt.before_revision + 1);
  expect(receipt.audit.action).toBe("target.created");
  expect(receipt.audit.entity_id).toBe(receipt.target.id);
  expect(receipt.audit.origin).toBe("local_operator");
  expect(receipt.audit.created_at).toBe(receipt.target.created_at);
  expect(expected(18)).toEqual(expected(21)); // actual post-restart workspace
  expect(expected(18).targets).toEqual([receipt.target]);
  expect(expected(18).audit.at(-1)).toEqual(receipt.audit);
  expect(expected(18).meta.audit_retention.total_recorded).toBe(
    receipt.after_revision,
  );
  const inventory = await toolClient.targets();
  expect(inventory).toEqual(expected(19));
  expect(await toolClient.targets()).toEqual(inventory);
  expect(inventory.targets).toEqual([receipt.target]);
  expect(inventory.draft_revision).toBe(receipt.after_revision);
  const selection = cloneTargetSelection({
    id: receipt.target.id,
    expectation: {
      target: receipt.target,
      after_revision: receipt.after_revision,
    },
  });
  expect(selection.expectation!.target).not.toBe(receipt.target);
  expect(selection.expectation!.target).toEqual(inventory.targets[0]);
  const path = targetSelectionPath(selection);
  expect(path).toBe(`/targets?target=${encodeURIComponent(receipt.target.id)}`);
  expect(
    targetSelectionFromLocation({
      pathname: "/targets",
      search: path.slice(path.indexOf("?")),
    }),
  ).toEqual({ id: receipt.target.id });
  expect(() =>
    cloneTargetSelection({ ...selection, id: "different-id" }),
  ).toThrow();
  expect(await chatClient.turn(turn.id)).toEqual(expected(16));
});

// All mutations below are SYNTHETIC malformed controls, not producer captures.
// Lexical replacements intentionally avoid parse/stringify: 2.0 and duplicate
// escaped keys must reach the same shipped Response decoder as genuine bytes.
function replaceOnce(raw: string, from: string, to: string) {
  expect(raw.split(from)).toHaveLength(2);
  const changed = raw.replace(from, to);
  expect(changed).not.toBe(raw);
  return changed;
}
const badTranscript: [string, string, string][] = [
  [
    "wrong-operation",
    '"operation":"target_create"',
    '"operation":"agent_profile_update"',
  ],
  [
    "wrong-audit-action",
    '"action":"target.created"',
    '"action":"agent.updated"',
  ],
  ["wrong-audit-origin", '"origin":"local_operator"', '"origin":"model"'],
  [
    "wrong-audit-ID",
    '"entity_id":"ee0818fe-459f-4483-b54c-4dd24a097857"',
    '"entity_id":"other-target"',
  ],
  [
    "wrong-target-ID",
    '"id":"ee0818fe-459f-4483-b54c-4dd24a097857"',
    '"id":"other-target"',
  ],
  [
    "wrong-audit-time",
    '"created_at":"2026-10-18T12:34:39.000293+00:00","origin"',
    '"created_at":"2026-10-18T12:34:39.000294+00:00","origin"',
  ],
  ["wrong-after-revision", '"after_revision":2', '"after_revision":3'],
  ["wrong-before-revision", '"before_revision":1', '"before_revision":0'],
  ["float-integer-token", '"after_revision":2', '"after_revision":2.0'],
  ["exponent-integer-token", '"after_revision":2', '"after_revision":2e0'],
  ["duplicate-key", '"revision":7', '"revision":7,"revision":7'],
  ["escaped-duplicate-key", '"revision":7', '"revision":7,"\\u0072evision":7'],
  ["extra-authority", '"revision":7', '"revision":7,"write_authority":true'],
  [
    "wrong-proposal-digest",
    '"digest":"19ca49eccc099b5ea8b9a1de0b936c2fa53aa818b1d7f0ed75cac7e850327a3e"',
    `"digest":"${"0".repeat(64)}"`,
  ],
];
it.each(badTranscript)(
  "SYNTHETIC malformed actual-receipt derivative rejects: %s",
  async (_label, from, to) => {
    replay({ index: 17, raw: replaceOnce(guardedRaw(row(17)), from, to) });
    await expect(toolClient.tools(turn.id)).rejects.toThrow();
  },
);
it.each([
  [
    "extra-authority",
    '"scope":"target_create"',
    '"scope":"target_create","proposal_fields":["name"]',
  ],
  ["wrong-scope", '"scope":"target_create"', '"scope":"agent"'],
  ["float-version", '"schema_version":2', '"schema_version":2.0'],
  [
    "duplicate-key",
    '"schema_version":2',
    '"schema_version":2,"schema_version":2',
  ],
])(
  "SYNTHETIC malformed grant derivative rejects on GET: %s",
  async (_label, from, to) => {
    replay({ index: 7, raw: replaceOnce(guardedRaw(row(7)), from, to) });
    await expect(recover("target_create_v2")).rejects.toThrow();
  },
);
it("SYNTHETIC opposite-direction legacy grant substitution rejects POST/GET/pre-submit", async () => {
  let legacy = replaceOnce(
    guardedRaw(row(5)),
    '"schema_version":2',
    '"schema_version":1',
  );
  legacy = replaceOnce(
    legacy,
    '"scope":"target_create","read_scope":["targets","target"],"proposal_tools":["target_create"]',
    '"read_scope":["agent_profile","skills","skill"],"proposal_fields":["name","skill_ids"]',
  );
  const legacyGrant = parseGrant(JSON.parse(legacy));
  expect(legacyGrant.schema_version).toBe(1); // valid opposite scope, not random malformed JSON
  const fetch = replay(
    { index: 5, raw: legacy, body: grantBody },
    { index: 7, raw: legacy },
    { index: 7, raw: legacy },
  );
  await expect(issue("target_create_v2")).rejects.toThrow();
  await expect(recover("target_create_v2")).rejects.toThrow();
  const calls = fetch.mock.calls.length;
  await expect(
    toolClient.submit(
      session,
      legacyGrant,
      text,
      () => true,
      "target_create_v2",
    ),
  ).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(calls);
  expect(fetch.mock.calls.some(([url]) => url.includes("tool-turns"))).toBe(
    false,
  );
});
it("SYNTHETIC duplicated inventory IDs reject instead of confirming a selected target", async () => {
  const raw = guardedRaw(row(19));
  const start = raw.indexOf('"targets":[') + '"targets":['.length;
  const target = raw.slice(start, -2);
  replay({
    index: 19,
    raw: raw.slice(0, start) + target + "," + target + "]}",
  });
  await expect(toolClient.targets()).rejects.toThrow();
});
