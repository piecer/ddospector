import { literalText, pythonSpace } from "../ai-settings/unicode-text";
import { parseJSON, utf8Length } from "../scenarios/json";
export const JSON_LIMIT = 1048576;
export const FRAME_LIMIT = JSON_LIMIT + 128;
export function decodeJSON(bytes: Uint8Array): unknown {
  check(bytes.byteLength <= JSON_LIMIT);
  return parseJSON(
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes),
  );
}
function sameTurn(a: ChatTurn, b: ChatTurn) {
  return (Object.keys(a) as (keyof ChatTurn)[]).every((k) => a[k] === b[k]);
}
export function reconcileTurn(previous: ChatTurn, next: ChatTurn): ChatTurn {
  check(
    next.id === previous.id &&
      next.session_id === previous.session_id &&
      next.request_id === previous.request_id &&
      next.sequence === previous.sequence &&
      next.user_text === previous.user_text &&
      next.created_at === previous.created_at &&
      next.revision >= previous.revision,
  );
  if (next.revision === previous.revision || terminal(previous))
    check(sameTurn(previous, next));
  return next;
}
export class ChatEvents {
  current: ChatTurn | null = null;
  private lastDelta: string | null = null;
  constructor(
    readonly id: string,
    readonly streaming = true,
  ) {
    uuid(id);
  }
  apply(value: unknown): ChatTurn {
    const e = object(value, "schema_version turn_id revision type turn text");
    check(e.schema_version === 1 && e.turn_id === this.id);
    integer(e.revision, 1);
    if (e.type === "snapshot") {
      check(e.text === null);
      const next = parseTurn(e.turn);
      check(next.id === this.id && next.revision === e.revision);
      if (this.current) {
        check(
          next.session_id === this.current.session_id &&
            next.request_id === this.current.request_id &&
            next.sequence === this.current.sequence &&
            next.user_text === this.current.user_text &&
            next.created_at === this.current.created_at,
        );
        check(next.revision >= this.current.revision);
        if (next.revision === this.current.revision) {
          check(sameTurn(next, this.current));
          return this.current;
        }
        check(
          !terminal(this.current) &&
            next.revision === this.current.revision + 1,
        );
      }
      this.current = next;
      this.lastDelta = null;
    } else {
      check(
        this.streaming &&
          e.type === "delta" &&
          e.turn === null &&
          validText(e.text, 4096) &&
          e.text.length > 0 &&
          this.current &&
          !terminal(this.current),
      );
      if (e.revision === this.current.revision) {
        check(this.lastDelta === e.text);
        return this.current;
      }
      check(e.revision === this.current.revision + 1);
      const text = this.current.assistant_text + e.text;
      check(utf8Length(text) <= 65536);
      this.current = {
        ...this.current,
        revision: e.revision,
        assistant_text: text,
      };
      this.lastDelta = e.text;
    }
    return this.current;
  }
}
import { chatCodes } from "./chat-types";
import type {
  ChatRuntime,
  ChatSession,
  ChatTurn,
  ChatHistory,
} from "./chat-types";
export const terminal = (turn: ChatTurn) =>
  ["succeeded", "failed", "cancelled", "interrupted"].includes(turn.status);
export function uuid(v: unknown): asserts v is string {
  check(
    typeof v === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        v,
      ),
  );
}
function utcKey(v: string) {
  const fraction = /\.(\d+)/.exec(v)?.[1] ?? "";
  return v.slice(0, 19) + "." + fraction.padEnd(6, "0");
}
function timestamp(v: unknown) {
  check(
    typeof v === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
        v,
      ) &&
      Number.isFinite(Date.parse(v)) &&
      new Date(v).toISOString().slice(0, 19) === v.slice(0, 19),
  );
}
export function parseSession(value: unknown): ChatSession {
  const s = object(
    value,
    "schema_version id request_id settings_revision profile_id model endpoint streaming locale created_at sequence active_turn_id",
  );
  check(s.schema_version === 1);
  uuid(s.id);
  uuid(s.request_id);
  integer(s.settings_revision);
  profileID(s.profile_id);
  name(s.model, 200);
  endpoint(s.endpoint);
  check(
    typeof s.streaming === "boolean" &&
      (s.locale === "en" || s.locale === "ko"),
  );
  timestamp(s.created_at);
  integer(s.sequence, 0, 64);
  if (s.active_turn_id !== null) {
    uuid(s.active_turn_id);
    check(s.sequence !== 0);
  }
  return value as ChatSession;
}
export function parseTurn(value: unknown): ChatTurn {
  const t = object(
    value,
    "schema_version id request_id session_id sequence revision status user_text assistant_text error_code transport provider_stop created_at finished_at",
  );
  check(t.schema_version === 1);
  uuid(t.id);
  uuid(t.request_id);
  uuid(t.session_id);
  integer(t.sequence, 1, 64);
  integer(t.revision, 1);
  check(
    [
      "accepted",
      "running",
      "cancel_requested",
      "succeeded",
      "failed",
      "cancelled",
      "interrupted",
    ].includes(t.status as string),
  );
  check(
    validText(t.user_text, 8192, true) && validText(t.assistant_text, 65536),
  );
  code(t.error_code);
  check(
    ["not_started", "open", "closed", "unknown"].includes(
      t.transport as string,
    ) && ["not_dispatched", "unknown"].includes(t.provider_stop as string),
  );
  timestamp(t.created_at);
  const result = value as ChatTurn;
  if (terminal(result)) {
    timestamp(t.finished_at);
    check(utcKey(result.finished_at!) >= utcKey(result.created_at));
    if (t.status === "succeeded")
      check(
        t.error_code === null &&
          validText(t.assistant_text, 65536, true) &&
          t.transport === "closed" &&
          t.provider_stop === "unknown",
      );
    else check(t.error_code !== null);
    if (t.status === "interrupted") check(t.error_code === "CHAT_INTERRUPTED");
    if (t.status === "cancelled") check(t.error_code === "CHAT_CANCELLED");
  } else check(t.finished_at === null && t.error_code === null);
  return result;
}
export function parseSessions(value: unknown): ChatSession[] {
  const r = object(value, "schema_version sessions");
  check(
    r.schema_version === 1 &&
      Array.isArray(r.sessions) &&
      r.sessions.length <= 32,
  );
  const sessions = r.sessions.map(parseSession);
  check(new Set(sessions.map((s) => s.id)).size === sessions.length);
  for (let i = 1; i < sessions.length; i++) {
    const a = sessions[i - 1],
      b = sessions[i];
    check(
      utcKey(a.created_at) > utcKey(b.created_at) ||
        (utcKey(a.created_at) === utcKey(b.created_at) && a.id < b.id),
    );
  }
  return sessions;
}
export function parseHistory(value: unknown): ChatHistory {
  const r = object(value, "schema_version session turns next_before_sequence");
  check(
    r.schema_version === 1 && Array.isArray(r.turns) && r.turns.length <= 2,
  );
  const session = parseSession(r.session),
    turns = r.turns.map(parseTurn);
  check(new Set(turns.map((t) => t.id)).size === turns.length);
  turns.forEach((t, i) =>
    check(
      t.session_id === session.id &&
        t.sequence <= session.sequence &&
        (!i || t.sequence === turns[i - 1].sequence + 1),
    ),
  );
  if (r.next_before_sequence !== null) {
    integer(r.next_before_sequence, 2, 64);
    check(turns.length > 0 && r.next_before_sequence === turns[0].sequence);
  }
  return value as ChatHistory;
}
export function invalid(): never {
  throw new Error("Invalid chat response.");
}
function check(ok: unknown): asserts ok {
  if (!ok) invalid();
}
function object(value: unknown, keys: string): Record<string, unknown> {
  check(value !== null && typeof value === "object" && !Array.isArray(value));
  const record = value as Record<string, unknown>;
  const expected = keys.split(" ");
  check(
    Object.keys(record).length === expected.length &&
      expected.every((k) => Object.hasOwn(record, k)),
  );
  return record;
}
function integer(
  v: unknown,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
): asserts v is number {
  check(
    typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max,
  );
}
export function validText(
  v: unknown,
  max: number,
  nonblank = false,
): v is string {
  return (
    typeof v === "string" &&
    !v.includes(String.fromCharCode(0)) &&
    !/[\uD800-\uDFFF]/u.test(v) &&
    new TextEncoder().encode(v).length <= max &&
    (!nonblank || Array.from(v).some((c) => !pythonSpace(c)))
  );
}
function name(v: unknown, max: number) {
  check(literalText(v, max));
}
function profileID(v: unknown) {
  check(typeof v === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(v));
}
function endpoint(v: unknown) {
  check(
    typeof v === "string" &&
      /^http:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?\/v1\/chat\/completions$/.test(
        v,
      ),
  );
  const u = new URL(v);
  check(!u.port || (+u.port >= 1 && +u.port <= 65535));
}
function code(v: unknown) {
  check(v === null || chatCodes.includes(v as (typeof chatCodes)[number]));
}
export function parseRuntime(value: unknown): ChatRuntime {
  const r = object(
    value,
    "schema_version mode supported reason settings_revision profile limits history configuration_tools live_execution mcp_execution",
  );
  check(
    r.schema_version === 1 &&
      r.mode === "chat_only" &&
      typeof r.supported === "boolean" &&
      r.history === "persistent" &&
      r.configuration_tools === false &&
      r.live_execution === false &&
      r.mcp_execution === false,
  );
  integer(r.settings_revision);
  code(r.reason);
  const limits = object(
    r.limits,
    "input_bytes output_bytes sessions session_turns history_bytes turn_seconds",
  );
  check(
    limits.input_bytes === 8192 &&
      limits.output_bytes === 65536 &&
      limits.sessions === 32 &&
      limits.session_turns === 64 &&
      limits.history_bytes === 8388608 &&
      limits.turn_seconds === 120,
  );
  if (r.supported) {
    check(r.reason === null);
    const p = object(r.profile, "id name model format endpoint streaming");
    profileID(p.id);
    name(p.name, 120);
    name(p.model, 200);
    endpoint(p.endpoint);
    check(p.format === "openai" && typeof p.streaming === "boolean");
  } else check(r.profile === null && r.reason !== null);
  return value as ChatRuntime;
}
