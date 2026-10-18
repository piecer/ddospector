import { expect, it } from "vitest";
it("validates two-turn history and terminal truth without normalizing IDs or text", () => {
  expect(parseSession(session)).toEqual(session);
  expect(parseTurn(turn)).toEqual(turn);
  const history = {
    schema_version: 1,
    session,
    turns: [turn],
    next_before_sequence: null,
  };
  expect(parseHistory(history)).toEqual(history);
  expect(parseSessions({ schema_version: 1, sessions: [session] })).toEqual([
    session,
  ]);
  for (const change of [
    { id: "11111111-1111-4111-A111-111111111111" },
    { sequence: 0 },
    { revision: 1.5 },
    { status: "succeeded" },
    { assistant_text: "\u0000" },
    { user_text: " " },
    { extra: false },
    { error_code: "ANY" },
  ])
    expect(() => parseTurn({ ...turn, ...change })).toThrow();
  for (const change of [
    { turns: [turn, turn] },
    { turns: [{ ...turn, session_id: turn.id }] },
    { next_before_sequence: 0 },
    { extra: true },
  ])
    expect(() => parseHistory({ ...history, ...change })).toThrow();
  expect(() =>
    parseSessions({ schema_version: 1, sessions: [session, session] }),
  ).toThrow();
});
import {
  parseRuntime,
  parseSession,
  parseTurn,
  parseHistory,
  parseSessions,
  ChatEvents,
  decodeJSON,
} from "./chat-wire";
import { session, turn, tid } from "./chat-test-fixtures";
it("requires a first authoritative snapshot and applies each ordered delta once", () => {
  const events = new ChatEvents(tid);
  const snap = {
    schema_version: 1,
    turn_id: tid,
    revision: 4,
    type: "snapshot",
    turn: {
      ...turn,
      revision: 4,
      status: "running",
      transport: "open",
      provider_stop: "unknown",
      assistant_text: "prior",
    },
    text: null,
  };
  const delta = {
    schema_version: 1,
    turn_id: tid,
    revision: 5,
    type: "delta",
    turn: null,
    text: "한😀",
  };
  expect(() => events.apply(delta)).toThrow();
  expect(events.apply(snap).assistant_text).toBe("prior");
  expect(events.apply(delta).assistant_text).toBe("prior한😀");
  expect(events.apply(delta).assistant_text).toBe("prior한😀");
  for (const bad of [
    { ...delta, revision: 7 },
    { ...delta, turn_id: session.id },
    { ...delta, revision: 5, text: "other" },
    { ...snap, revision: 8 },
    { ...delta, revision: 6, extra: 1 },
  ])
    expect(() => events.apply(bad)).toThrow();
  const final = {
    ...snap,
    revision: 6,
    turn: {
      ...snap.turn,
      revision: 6,
      status: "succeeded",
      assistant_text: "authoritative",
      transport: "closed",
      finished_at: turn.created_at,
    },
  };
  expect(events.apply(final).assistant_text).toBe("authoritative");
  expect(() => events.apply({ ...delta, revision: 7 })).toThrow();
});
it("rejects a future live snapshot after the initial authoritative jump", () => {
  const events = new ChatEvents(tid);
  const event = {
    schema_version: 1,
    turn_id: tid,
    revision: 4,
    type: "snapshot",
    turn: { ...turn, revision: 4 },
    text: null,
  };
  events.apply(event);
  expect(() =>
    events.apply({ ...event, revision: 6, turn: { ...turn, revision: 6 } }),
  ).toThrow();
});
it("decodes 1MiB bounded JSON with duplicate rejection and full escape-heavy two-turn history", () => {
  const long = "\u0001".repeat(65536);
  const first = { ...turn, assistant_text: long };
  const second = { ...first, id: session.id, sequence: 2 };
  const history = {
    schema_version: 1,
    session: { ...session, sequence: 2 },
    turns: [first, second],
    next_before_sequence: null,
  };
  expect(
    parseHistory(decodeJSON(new TextEncoder().encode(JSON.stringify(history)))),
  ).toEqual(history);
  for (const source of [
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"n":9007199254740992}',
    '{"n":1e0}',
    " ".repeat(1048577),
  ])
    expect(() => decodeJSON(new TextEncoder().encode(source))).toThrow();
  expect(() => decodeJSON(new Uint8Array([0xc3, 0x28]))).toThrow();
});
it.each(["local\n", "x\u200b", "x\u001f", " x", "x "])(
  "rejects forbidden profile literals %j",
  (value) => {
    expect(() =>
      parseRuntime({
        ...runtime,
        profile: { ...runtime.profile, name: value },
      }),
    ).toThrow();
  },
);
it.each([
  "11111111-1111-4111-8111-111111111111\n",
  "11111111-1111-4111-a111-11111111111A",
])("rejects noncanonical UUID %j", (id) => {
  expect(() => parseTurn({ ...turn, id })).toThrow();
});
it.each([
  "2026-02-30T01:00:00Z",
  "2026-10-18T01:00:00Z\n",
  "2026-10-18T01:00:00+09:00",
])("rejects invalid UTC timestamp %j", (created_at) => {
  expect(() => parseTurn({ ...turn, created_at })).toThrow();
});
it("preserves UTC microsecond ordering instead of truncating timestamps to browser milliseconds", () => {
  const newer = { ...session, created_at: "2026-10-18T01:00:00.000002Z" };
  const older = {
    ...session,
    id: "00000000-0000-4000-8000-000000000000",
    created_at: "2026-10-18T01:00:00.000001+00:00",
  };
  expect(
    parseSessions({ schema_version: 1, sessions: [newer, older] }),
  ).toEqual([newer, older]);
  expect(() =>
    parseTurn({
      ...turn,
      status: "succeeded",
      assistant_text: "valid",
      transport: "closed",
      provider_stop: "unknown",
      created_at: newer.created_at,
      finished_at: older.created_at,
    }),
  ).toThrow();
});
// Synthetic HTTP unit fixtures, not model acceptance.
export const runtime = {
  schema_version: 1,
  mode: "chat_only",
  supported: true,
  reason: null,
  settings_revision: 0,
  profile: {
    id: "local-model_1",
    name: "Local",
    model: "test:model",
    format: "openai",
    endpoint: "http://localhost:11434/v1/chat/completions",
    streaming: true,
  },
  limits: {
    input_bytes: 8192,
    output_bytes: 65536,
    sessions: 32,
    session_turns: 64,
    history_bytes: 8388608,
    turn_seconds: 120,
  },
  history: "persistent",
  configuration_tools: false,
  live_execution: false,
  mcp_execution: false,
};
it("admits closed runtime with verbatim AIIdentifier, not UUID profile IDs", () => {
  expect(parseRuntime(runtime)).toEqual(runtime);
  for (const change of [
    { extra: 1 },
    { settings_revision: 2 ** 53 },
    { configuration_tools: true },
    { supported: false },
    { profile: { ...runtime.profile, id: "Local Model" } },
  ])
    expect(() => parseRuntime({ ...runtime, ...change })).toThrow();
});
