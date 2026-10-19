import { parseTarget, parseTargetInput } from "./chat-target-wire";
import { chatCodes } from "./chat-types";
import { invalid, uuid } from "./chat-wire";
import { canonical, digest, utf8Length } from "../scenarios/json";
import { forbiddenText, pythonSpace } from "../ai-settings/unicode-text";
import type {
  AgentConfig,
  ToolGrant,
  ToolDecision,
  ToolCall,
  ToolTranscript,
  ToolResult,
  ToolFence,
  ReconcileReceipt,
  TargetInspection,
  ToolRuntime,
} from "./chat-tool-types";
export function check(ok: unknown): asserts ok {
  if (!ok) invalid();
}
export function parseFence(value: unknown): ToolFence {
  const f = object(
    value,
    "schema_version generation fenced call_ids current_draft_revision",
  );
  check(f.schema_version === 1 && typeof f.fenced === "boolean");
  integer(f.generation);
  array(f.call_ids, 1);
  f.call_ids.forEach(uuid);
  check(f.call_ids.length === (f.fenced ? 1 : 0));
  if (f.current_draft_revision !== null) integer(f.current_draft_revision);
  return value as ToolFence;
}
export function parseReconcile(value: unknown): ReconcileReceipt {
  const r = object(
    value,
    "schema_version request_id acknowledged_call_ids generation write_fenced prior_outcomes",
  );
  check(
    r.schema_version === 1 &&
      r.write_fenced === false &&
      r.prior_outcomes === "remain_uncertain",
  );
  uuid(r.request_id);
  integer(r.generation, 1);
  array(r.acknowledged_call_ids, 1);
  check(r.acknowledged_call_ids.length === 1);
  r.acknowledged_call_ids.forEach(uuid);
  return value as ReconcileReceipt;
}
export function reconcileFence(
  previous: ToolFence,
  next: ToolFence,
): ToolFence {
  check(next.generation >= previous.generation);
  if (next.generation === previous.generation)
    check(
      next.fenced === previous.fenced &&
        canonical(next.call_ids) === canonical(previous.call_ids),
    );
  if (
    previous.current_draft_revision !== null &&
    next.current_draft_revision !== null
  )
    check(next.current_draft_revision >= previous.current_draft_revision);
  return next;
}
export function reconcileTranscript(
  previous: ToolTranscript,
  next: ToolTranscript,
): ToolTranscript {
  check(
    next.turn_id === previous.turn_id &&
      next.revision >= previous.revision &&
      next.calls.length >= previous.calls.length,
  );
  if (next.revision === previous.revision)
    check(canonical(next) === canonical(previous));
  previous.calls.forEach((old, index) => {
    const call = next.calls[index];
    for (const key of [
      "id",
      "index",
      "provider_call_id",
      "tool",
      "arguments",
      "args_digest",
      "grant_id",
      "actor",
      "started_at",
    ] as const)
      check(canonical(call[key]) === canonical(old[key]));
    if (old.proposal)
      check(canonical(call.proposal) === canonical(old.proposal));
    if (old.decision)
      check(canonical(call.decision) === canonical(old.decision));
    if (callTerminal(old)) check(canonical(call) === canonical(old));
    else if (old.status === "executing")
      check(call.status !== "requested" && call.status !== "awaiting_approval");
    else if (old.status === "awaiting_approval")
      check(call.status !== "requested");
  });
  return next;
}

export function integer(
  v: unknown,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
): asserts v is number {
  check(
    typeof v === "number" && Number.isSafeInteger(v) && v >= min && v <= max,
  );
}
export function timestamp(v: unknown): asserts v is string {
  check(
    typeof v === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
        v,
      ) &&
      Number.isFinite(Date.parse(v)) &&
      new Date(v).toISOString().slice(0, 19) === v.slice(0, 19),
  );
}
export const timeKey = (v: string) =>
  v.slice(0, 19) + "." + (/\.(\d+)/.exec(v)?.[1] ?? "").padEnd(6, "0");
function sha(v: unknown) {
  check(typeof v === "string" && /^[a-f0-9]{64}$/.test(v));
}
export function identifier(v: unknown) {
  check(typeof v === "string" && /^[a-z0-9-]{1,64}$/.test(v));
}
export function text(v: unknown, max: number, multiline = false) {
  check(typeof v === "string");
  const chars = Array.from(v);
  check(
    chars.length > 0 &&
      chars.length <= max &&
      chars.some((c) => !pythonSpace(c)) &&
      !chars.some(
        (c) => forbiddenText(c) && !(multiline && "\n\r\t".includes(c)),
      ),
  );
}
export function array(v: unknown, max: number): asserts v is unknown[] {
  check(
    Array.isArray(v) &&
      Object.getPrototypeOf(v) === Array.prototype &&
      v.length <= max &&
      Reflect.ownKeys(v).length === v.length + 1,
  );
  for (let i = 0; i < v.length; i++) {
    const d = Object.getOwnPropertyDescriptor(v, String(i));
    check(d && d.enumerable && "value" in d);
  }
}
function ids(v: unknown) {
  array(v, 103);
  v.forEach(identifier);
  check(new Set(v).size === v.length);
}
export function parseAgent(value: unknown): AgentConfig {
  const a = object(value, "resource_id name skill_ids");
  check(a.resource_id === "agent-profile");
  text(a.name, 120);
  ids(a.skill_ids);
  return value as AgentConfig;
}
export function parseGrant(value: unknown): ToolGrant {
  const version =
    value && typeof value === "object"
      ? Object.getOwnPropertyDescriptor(value, "schema_version")?.value
      : undefined;
  check(version === 1 || version === 2);
  const g = object(
    value,
    "schema_version id request_id session_id turn_request_id expected_sequence text_sha256 settings_revision profile_id created_at expires_at status read_scope " +
      (version === 1 ? "proposal_fields" : "scope proposal_tools"),
  );
  [g.id, g.request_id, g.session_id, g.turn_request_id].forEach(uuid);
  integer(g.expected_sequence, 0, 63);
  integer(g.settings_revision);
  sha(g.text_sha256);
  check(
    typeof g.profile_id === "string" &&
      /^[a-z][a-z0-9_-]{0,63}$/.test(g.profile_id),
  );
  timestamp(g.created_at);
  timestamp(g.expires_at);
  check(timeKey(g.expires_at) > timeKey(g.created_at));
  check(
    ["pending", "consumed", "revoked", "expired"].includes(g.status as string),
  );
  array(g.read_scope, 3);
  if (version === 1) {
    array(g.proposal_fields, 2);
    check(
      canonical(g.read_scope) === '["agent_profile","skills","skill"]' &&
        canonical(g.proposal_fields) === '["name","skill_ids"]',
    );
  } else {
    array(g.proposal_tools, 1);
    check(
      g.scope === "target_create" &&
        canonical(g.read_scope) === '["targets","target"]' &&
        canonical(g.proposal_tools) === '["target_create"]',
    );
  }
  check(utf8Length(canonical(value)) <= 8192);
  return value as ToolGrant;
}
export function parseDecision(value: unknown): ToolDecision {
  const d = object(
    value,
    "schema_version request_id call_id proposal_digest decision accepted_at",
  );
  check(d.schema_version === 1);
  uuid(d.request_id);
  uuid(d.call_id);
  sha(d.proposal_digest);
  timestamp(d.accepted_at);
  check(d.decision === "approve" || d.decision === "deny");
  return value as ToolDecision;
}
function argumentsFor(v: unknown, tool: unknown) {
  if (tool === "target_create") {
    const a = object(v, "expected_draft_revision name address kind");
    integer(a.expected_draft_revision);
    parseTargetInput({ name: a.name, address: a.address, kind: a.kind });
  } else if (tool === "agent_profile_update") {
    const a = object(v, "expected_draft_revision name skill_ids");
    integer(a.expected_draft_revision);
    text(a.name, 120);
    ids(a.skill_ids);
  } else {
    check(tool === "configuration_read" && v !== null && typeof v === "object");
    const k = Object.getOwnPropertyDescriptor(v, "kind");
    check(k && "value" in k);
    if (k.value === "agent_profile") object(v, "kind");
    else if (k.value === "skills" || k.value === "targets") {
      const a = object(v, "kind offset limit");
      integer(a.offset, 0, k.value === "targets" ? 100 : 103);
      integer(a.limit, 1, 10);
    } else {
      const a = object(v, "kind id");
      check(a.kind === "skill" || a.kind === "target");
      identifier(a.id);
    }
  }
  check(utf8Length(canonical(v)) <= 16384);
}
function skill(v: unknown, detail: boolean) {
  const s = object(
    v,
    "id name category status version" +
      (detail ? " description instructions" : ""),
  );
  identifier(s.id);
  text(s.name, 120);
  check(
    ["planning", "measurement", "analysis"].includes(s.category as string) &&
      ["template", "draft"].includes(s.status as string) &&
      s.version === "1.0.0",
  );
  if (detail) {
    text(s.description, 1000, true);
    text(s.instructions, 8000, true);
  }
  return s;
}
function resultFor(value: unknown, call: ToolCall): ToolResult {
  if (call.tool === "target_create") {
    const r = object(value, "kind before_revision after_revision target audit");
    check(
      r.kind === "target_created" &&
        call.proposal &&
        "operation" in call.proposal,
    );
    integer(r.before_revision);
    integer(r.after_revision);
    check(
      r.before_revision === call.proposal.expected_draft_revision &&
        r.after_revision === r.before_revision + 1,
    );
    const t = parseTarget(r.target);
    check(
      canonical({ name: t.name, address: t.address, kind: t.kind }) ===
        canonical(call.proposal.after),
    );
    const a = object(r.audit, "id action entity_id created_at origin");
    identifier(a.id);
    check(
      a.action === "target.created" &&
        a.entity_id === t.id &&
        a.origin === "local_operator" &&
        a.created_at === t.created_at,
    );
  } else if (call.tool === "agent_profile_update") {
    const r = object(
      value,
      "kind before_revision after_revision agent_profile audit",
    );
    check(r.kind === "agent_profile_updated");
    integer(r.before_revision);
    integer(r.after_revision);
    check(
      r.before_revision === call.proposal!.expected_draft_revision &&
        r.after_revision === r.before_revision + 1,
    );
    parseAgent(r.agent_profile);
    check(canonical(r.agent_profile) === canonical(call.proposal!.after));
    const a = object(r.audit, "id action entity_id created_at origin");
    identifier(a.id);
    timestamp(a.created_at);
    check(
      a.action === "agent_profile.updated" &&
        a.entity_id === "agent-profile" &&
        a.origin === "local_operator",
    );
  } else {
    const args = call.arguments;
    check("kind" in args);
    if (args.kind === "agent_profile") {
      const r = object(value, "kind draft_revision agent_profile");
      check(r.kind === args.kind);
      integer(r.draft_revision);
      parseAgent(r.agent_profile);
    } else if (args.kind === "target") {
      const r = object(value, "kind draft_revision target");
      check(r.kind === args.kind);
      integer(r.draft_revision);
      check(parseTarget(r.target).id === args.id);
    } else if (args.kind === "targets") {
      const r = object(value, "kind draft_revision items next_offset");
      check(r.kind === args.kind);
      integer(r.draft_revision);
      array(r.items, args.limit);
      const items = r.items.map(parseTarget);
      check(new Set(items.map((t) => t.id)).size === items.length);
      if (r.next_offset !== null) {
        integer(r.next_offset, 1, 100);
        check(items.length > 0 && r.next_offset === args.offset + items.length);
      }
    } else if (args.kind === "skills") {
      const r = object(value, "kind draft_revision items next_offset");
      check(r.kind === args.kind);
      integer(r.draft_revision);
      array(r.items, args.limit);
      const list = r.items.map((s) => skill(s, false));
      check(new Set(list.map((s) => s.id)).size === list.length);
      if (r.next_offset !== null) {
        integer(r.next_offset, 1, 103);
        check(r.next_offset === args.offset + list.length && list.length > 0);
      }
    } else {
      check(args.kind === "skill");
      const r = object(value, "kind draft_revision skill");
      check(r.kind === args.kind);
      integer(r.draft_revision);
      check(skill(r.skill, true).id === args.id);
    }
  }
  check(utf8Length(canonical(value)) <= 32768);
  return value as ToolResult;
}
export const isWrite = (tool: unknown) =>
  tool === "agent_profile_update" || tool === "target_create";
export function parseTargetInspection(value: unknown): TargetInspection {
  const v = object(value, "schema_version draft_revision targets");
  check(v.schema_version === 1);
  integer(v.draft_revision);
  array(v.targets, 100);
  const targets = v.targets.map(parseTarget);
  check(new Set(targets.map((t) => t.id)).size === targets.length);
  check(utf8Length(canonical(value)) <= 131072);
  return value as TargetInspection;
}
export const callTerminal = (c: ToolCall) =>
  !["requested", "awaiting_approval", "executing"].includes(c.status);
async function parseCall(value: unknown): Promise<ToolCall> {
  const c = object(
    value,
    "id index provider_call_id tool arguments args_digest grant_id actor status error_code proposal decision result started_at finished_at",
  );
  uuid(c.id);
  uuid(c.grant_id);
  integer(c.index, 0, 2);
  check(
    typeof c.provider_call_id === "string" &&
      c.provider_call_id.length >= 1 &&
      c.provider_call_id.length <= 128 &&
      Array.from(c.provider_call_id).every((char) => char.charCodeAt(0) <= 127),
  );
  check(c.actor === "operator_authorized_model");
  argumentsFor(c.arguments, c.tool);
  sha(c.args_digest);
  check(c.args_digest === (await digest(c.arguments)));
  timestamp(c.started_at);
  const call = value as ToolCall;
  if (c.proposal !== null) {
    check(isWrite(c.tool));
    const p = object(
      c.proposal,
      "digest expected_draft_revision before after expires_at" +
        (c.tool === "target_create" ? " operation" : ""),
    );
    sha(p.digest);
    integer(p.expected_draft_revision);
    if (c.tool === "target_create") {
      check(p.operation === "target_create" && p.before === null);
      parseTargetInput(p.after);
    } else {
      parseAgent(p.before);
      parseAgent(p.after);
    }
    timestamp(p.expires_at);
    check(timeKey(p.expires_at) > timeKey(c.started_at));
    const args = call.arguments;
    check("expected_draft_revision" in args);
    check(
      p.expected_draft_revision === args.expected_draft_revision &&
        call.proposal!.after.name === args.name &&
        (c.tool === "target_create"
          ? "address" in args &&
            "address" in call.proposal!.after &&
            call.proposal!.after.address === args.address &&
            call.proposal!.after.kind === args.kind
          : "skill_ids" in args &&
            "skill_ids" in call.proposal!.after &&
            canonical(call.proposal!.after.skill_ids) ===
              canonical(args.skill_ids)),
    );
    check(
      p.digest ===
        (await digest({
          call_id: c.id,
          grant_id: c.grant_id,
          ...(c.tool === "target_create" ? { operation: "target_create" } : {}),
          expected_draft_revision: p.expected_draft_revision,
          before: p.before,
          after: p.after,
          expires_at: p.expires_at,
        })),
    );
  }
  if (c.decision !== null) {
    const d = parseDecision(c.decision);
    check(
      isWrite(c.tool) &&
        call.proposal &&
        d.call_id === c.id &&
        d.proposal_digest === call.proposal.digest &&
        timeKey(d.accepted_at) >= timeKey(c.started_at) &&
        timeKey(d.accepted_at) < timeKey(call.proposal.expires_at),
    );
  }
  if (c.tool === "configuration_read")
    check(
      c.proposal === null &&
        c.decision === null &&
        c.status !== "awaiting_approval" &&
        c.status !== "uncertain",
    );
  if (
    ["requested", "awaiting_approval", "executing"].includes(c.status as string)
  ) {
    check(c.error_code === null && c.result === null && c.finished_at === null);
    if (c.status === "requested")
      check(c.proposal === null && c.decision === null);
    if (c.status === "awaiting_approval")
      check(c.proposal !== null && c.decision === null);
  } else {
    timestamp(c.finished_at);
    check(timeKey(c.finished_at) >= timeKey(c.started_at));
    if (call.decision !== null)
      check(timeKey(c.finished_at) >= timeKey(call.decision.accepted_at));
    if (c.status === "succeeded") {
      check(c.error_code === null);
      resultFor(c.result, call);
    } else {
      const codes: Record<string, string[]> = {
        denied: ["CHAT_TOOL_DENIED", "CHAT_TOOL_WRITE_FENCED"],
        conflict: ["CHAT_TOOL_CONFLICT"],
        failed: [
          "CHAT_TIMEOUT",
          "CHAT_INVALID_REQUEST",
          "CHAT_NOT_FOUND",
          "CHAT_TOOL_LIMIT",
          "CHAT_STORAGE_ERROR",
        ],
        uncertain: ["CHAT_TOOL_UNCERTAIN"],
        cancelled: ["CHAT_CANCELLED"],
      };
      check(
        c.result === null &&
          typeof c.status === "string" &&
          codes[c.status]?.includes(c.error_code as string),
      );
    }
  }
  if (
    isWrite(c.tool) &&
    ["executing", "succeeded", "uncertain"].includes(c.status as string)
  )
    check(c.proposal !== null && call.decision?.decision === "approve");
  if (c.status === "denied" && call.decision !== null)
    check(call.decision.decision === "deny");
  if (call.decision?.decision === "deny")
    check(c.status === "denied" && c.error_code === "CHAT_TOOL_DENIED");
  if (c.status === "denied" && c.error_code === "CHAT_TOOL_DENIED")
    check(call.decision?.decision === "deny");
  check(utf8Length(canonical(value)) <= 262144);
  return call;
}
export async function parseTranscript(value: unknown): Promise<ToolTranscript> {
  const t = object(value, "schema_version turn_id revision calls");
  check(t.schema_version === 1);
  uuid(t.turn_id);
  integer(t.revision);
  array(t.calls, 3);
  const calls = await Promise.all(t.calls.map(parseCall));
  check(
    calls.every((c, i) => c.index === i) &&
      new Set(calls.map((c) => c.id)).size === calls.length &&
      new Set(calls.map((c) => c.provider_call_id)).size === calls.length,
  );
  check(
    calls.filter((c) => isWrite(c.tool)).length <= 1 &&
      calls.filter((c) => c.proposal !== null).length <= 1 &&
      calls.filter((c) => c.decision !== null).length <= 1 &&
      new Set(calls.map((c) => c.grant_id)).size <= 1,
  );
  check(utf8Length(canonical(value)) <= 1048576);
  return value as ToolTranscript;
}

export function object(value: unknown, keys: string): Record<string, unknown> {
  check(value !== null && typeof value === "object" && !Array.isArray(value));
  check(
    Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null,
  );
  const expected = keys.split(" ");
  check(Reflect.ownKeys(value).length === expected.length);
  for (const key of expected) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    check(descriptor && descriptor.enumerable && "value" in descriptor);
  }
  return value as Record<string, unknown>;
}
export function parseToolRuntime(value: unknown) {
  const r = object(
    value,
    "schema_version mode supported reason tools max_calls max_writes requires_write_approval",
  );
  check(
    (r.schema_version === 1 || r.schema_version === 2) &&
      r.mode === "operator_approved_settings" &&
      typeof r.supported === "boolean" &&
      r.max_calls === 3 &&
      r.max_writes === 1 &&
      r.requires_write_approval === true,
  );
  array(r.tools, 3);
  check(
    canonical(r.tools) ===
      (r.schema_version === 1
        ? '["configuration_read","agent_profile_update"]'
        : '["configuration_read","agent_profile_update","target_create"]'),
  );
  check(
    r.supported
      ? r.reason === null
      : chatCodes.includes(r.reason as (typeof chatCodes)[number]),
  );
  return value as ToolRuntime;
}
