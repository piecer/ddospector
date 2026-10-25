// Genuine current native HTTP positives; synthetic provider, never a real model.
// JSON.parse supplies expectations only. Positive Response bodies stay byte-exact.
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { toolClient } from "./chat-tool-client";
import { chatClient } from "./chat-client";
import { parseSession } from "./chat-wire";
import { parseGrant } from "./chat-tool-wire";
import { canonical } from "../scenarios/json";
import type { RequestedAuthority } from "./chat-tool-types";

type Pin = { path: string; sha256: string; mode: string };
type Row = {
  file: string;
  path: string;
  method: string;
  status: number;
  content_type: string;
  raw_utf8: string;
  sha256: string;
  bytes: number;
};
type Variant = {
  variant: "agent" | "target" | "skill";
  verdict: string;
  captures: Row[];
  synthetic_provider_requests: number;
  provider_handlers_closed: boolean;
  cleanup: { cleanup_verified: boolean; actual_exit: number };
};
const bundleBytes = readFileSync(
  resolve("src/pages/ai/chat-skill-producer-data/producer.json"),
);
const bundle = JSON.parse(bundleBytes.toString("utf8")) as {
  schema_version: number;
  provenance: string;
  producer_inputs: Pin[];
  source_pre: Pin[];
  source_post: Pin[];
  capture: {
    verdict: string;
    real_model_requests: number;
    synthetic_provider_requests: number;
    source_sha256: string;
    variants: Variant[];
  };
};
const sha = (v: string | Uint8Array) =>
  createHash("sha256").update(v).digest("hex");
function raw(row: Row) {
  expect(Buffer.byteLength(row.raw_utf8)).toBe(row.bytes);
  expect(sha(row.raw_utf8)).toBe(row.sha256);
  expect(row.content_type).toMatch(/^application\/json(?:;|$)/);
  expect([200, 201, 202]).toContain(row.status);
  return row.raw_utf8;
}
function rows(v: Variant, path: string, method = "GET") {
  const result = v.captures.filter(
    (r) => r.path === path && r.method === method,
  );
  expect(
    result.length,
    `${v.variant}: missing actual ${method} ${path}`,
  ).toBeGreaterThan(0);
  return result;
}
function variant(name: Variant["variant"]) {
  const result = bundle.capture.variants.find((v) => v.variant === name);
  expect(result).toBeDefined();
  if (!result) throw new Error("Missing captured variant");
  return result;
}
function context(name: Variant["variant"]) {
  const v = variant(name);
  const session = parseSession(
    JSON.parse(raw(rows(v, "/api/v1/chat/sessions", "POST")[0])),
  );
  const grant = parseGrant(
    JSON.parse(raw(rows(v, "/api/v1/chat/tool-grants", "POST")[0])),
  );
  const turn = JSON.parse(
    raw(rows(v, `/api/v1/chat/sessions/${session.id}/tool-turns`, "POST")[0]),
  );
  const companions = rows(v, `/api/v1/chat/turns/${turn.id}/tools`);
  const finals = companions.filter(
    (r) => JSON.parse(raw(r)).calls[1]?.status === "succeeded",
  );
  expect(finals).toHaveLength(2);
  const saved = JSON.parse(raw(finals[1]));
  return { v, session, grant, turn, companions, finals, saved };
}
function fetchOne(row: Row, body?: unknown, derivative?: string) {
  let consumed = false;
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    expect(consumed, "Unexpected second fetch/retry").toBe(false);
    consumed = true;
    expect(path).toBe(row.path);
    expect(init?.method).toBe(row.method);
    expect(init?.cache).toBe("no-store");
    expect(init?.redirect).toBe("error");
    if (body !== undefined)
      expect(JSON.parse(String(init?.body))).toEqual(body);
    else if (row.method === "GET") expect(init?.body).toBeUndefined();
    return new Response(derivative ?? raw(row), {
      status: row.status,
      headers: { "content-type": row.content_type },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());

it("requires genuine current native v1/v2/v3 closure and exact live producer hashes/modes", () => {
  expect(sha(bundleBytes)).toBe(
    "cb3b7e080c6f59a5669429f9722a1ceddd057b949030971f0a8f2b933dda8732",
  );
  expect(bundle.schema_version).toBe(1);
  expect(bundle.provenance).toBe(
    "actual_current_native_http_all_variants_synthetic_provider_not_real_model",
  );
  expect(bundle.capture.verdict).toBe(
    "ACTUAL_ALL_VARIANT_CAPTURE_NOT_REAL_MODEL",
  );
  expect(bundle.capture.real_model_requests).toBe(0);
  expect(bundle.capture.synthetic_provider_requests).toBe(9);
  expect(bundle.capture.variants.map((v) => v.variant)).toEqual([
    "agent",
    "target",
    "skill",
  ]);
  expect(bundle.source_post).toEqual(bundle.source_pre);
  expect(sha(canonical(bundle.source_pre))).toBe(bundle.capture.source_sha256);
  expect(bundle.capture.source_sha256).toBe(
    "b7da80d6fd376bf7dc583a10ec7f18452cdc69e478dae6a67a5bb8c51d0ea3fb",
  );
  expect(bundle.producer_inputs).toEqual(
    bundle.source_pre.filter(
      (entry) =>
        /^(src\/|tests\/chat\/|tests\/tooling\/|tools\/)/.test(entry.path) ||
        ["pyproject.toml", "uv.lock"].includes(entry.path),
    ),
  );
  expect(bundle.producer_inputs).toHaveLength(100);
  expect(new Set(bundle.producer_inputs.map((p) => p.path)).size).toBe(100);
  for (const required of [
    "tests/chat/chat_skill_capture.py",
    "tests/chat/provider_fixture.py",
    "tests/chat/test_chat_skill_integration.py",
    "tools/chat_tools_acceptance.py",
    "src/aiddos/api/chat_tool_runtime.py",
    "src/aiddos/api/chat_tool_models.py",
    "src/aiddos/api/store.py",
    "uv.lock",
  ]) {
    expect(bundle.producer_inputs.some((p) => p.path === required)).toBe(true);
  }
  for (const pin of bundle.producer_inputs) {
    const path = resolve("..", pin.path);
    expect(sha(readFileSync(path)), pin.path).toBe(pin.sha256);
    expect(`0o${(statSync(path).mode & 0o777).toString(8)}`, pin.path).toBe(
      pin.mode,
    );
  }
  const counts = { agent: 20, target: 22, skill: 23 };
  for (const v of bundle.capture.variants) {
    expect(v.verdict).toBe("ACTUAL_NATIVE_CAPTURE_NOT_REAL_MODEL");
    expect(v.synthetic_provider_requests).toBe(3);
    expect(v.provider_handlers_closed).toBe(true);
    expect(v.cleanup.cleanup_verified).toBe(true);
    // Uvicorn receives the existing harness's deliberate shutdown SIGTERM.
    expect(v.cleanup.actual_exit).toBe(-15);
    expect(v.captures).toHaveLength(counts[v.variant]);
    expect(new Set(v.captures.map((r) => r.file)).size).toBe(v.captures.length);
    v.captures.forEach((r, index) => {
      expect(r.file).toBe(`http_${String(index).padStart(4, "0")}.json`);
      raw(r);
    });
  }
});

it.each(["agent", "target", "skill"] as const)(
  "consumes every actual %s runtime/grant/turn/proposal/decision/saved/restart response through shipped clients",
  async (name) => {
    const { v, session, grant, turn, companions, finals, saved } =
      context(name);
    const authority: RequestedAuthority =
      name === "agent"
        ? "agent_v1"
        : name === "target"
          ? "target_create_v2"
          : "skill_create_v3";
    const runtimeRow = rows(v, "/api/v1/chat/runtime")[0];
    let fetch = fetchOne(runtimeRow);
    const runtime = await chatClient.runtime();
    expect(runtime).toEqual(JSON.parse(raw(runtimeRow)));
    expect(fetch).toHaveBeenCalledTimes(1);
    for (const row of rows(v, "/api/v1/chat/sessions", "POST")) {
      fetch = fetchOne(row, {
        request_id: session.request_id,
        settings_revision: session.settings_revision,
        profile_id: session.profile_id,
        approved_endpoint: session.endpoint,
        locale: session.locale,
      });
      expect(
        await chatClient.start(runtime, session.request_id, session.locale),
      ).toEqual(session);
      expect(fetch).toHaveBeenCalledTimes(1);
    }
    const toolRuntime = rows(v, "/api/v1/chat/tools/runtime")[0];
    fetch = fetchOne(toolRuntime);
    expect(await toolClient.runtime()).toEqual(JSON.parse(raw(toolRuntime)));
    expect(JSON.parse(raw(toolRuntime)).schema_version).toBe(3);
    expect(fetch).toHaveBeenCalledTimes(1);
    const input = {
      ...(name === "agent"
        ? {}
        : {
            schema_version: name === "target" ? 2 : 3,
            scope: name === "target" ? "target_create" : "skill_create",
          }),
      request_id: grant.request_id,
      session_id: session.id,
      turn_request_id: grant.turn_request_id,
      expected_sequence: session.sequence,
      text: turn.user_text,
    };
    for (const row of rows(v, "/api/v1/chat/tool-grants", "POST")) {
      fetch = fetchOne(row, input);
      expect(
        await toolClient.grant(
          session,
          grant.request_id,
          grant.turn_request_id,
          turn.user_text,
          authority,
        ),
      ).toEqual(grant);
      expect(fetch).toHaveBeenCalledTimes(1);
    }
    fetch = fetchOne(
      rows(v, `/api/v1/chat/tool-grants/by-request/${grant.request_id}`)[0],
    );
    expect(
      await toolClient.recoverGrant(
        session,
        grant.request_id,
        grant.turn_request_id,
        turn.user_text,
        authority,
      ),
    ).toEqual(grant);
    expect(fetch).toHaveBeenCalledTimes(1);
    for (const row of rows(
      v,
      `/api/v1/chat/sessions/${session.id}/tool-turns`,
      "POST",
    )) {
      fetch = fetchOne(row, {
        request_id: grant.turn_request_id,
        expected_sequence: session.sequence,
        text: turn.user_text,
        grant_id: grant.id,
      });
      expect(
        await toolClient.submit(
          session,
          grant,
          turn.user_text,
          () => true,
          authority,
        ),
      ).toEqual(JSON.parse(raw(row)));
      expect(fetch).toHaveBeenCalledTimes(1);
    }
    expect(
      companions.some((r) =>
        JSON.parse(raw(r)).calls.some(
          (c: { status: string }) => c.status === "awaiting_approval",
        ),
      ),
    ).toBe(true);
    for (const row of companions) {
      fetch = fetchOne(row);
      expect(await toolClient.tools(turn.id)).toEqual(JSON.parse(raw(row)));
      expect(fetch).toHaveBeenCalledTimes(1);
    }
    expect(raw(finals[1])).toBe(raw(finals[0]));
    const call = saved.calls[1];
    expect(call.result.kind).toBe(
      {
        agent: "agent_profile_updated",
        target: "target_created",
        skill: "skill_created",
      }[name],
    );
    const decision = rows(
      v,
      `/api/v1/chat/tool-calls/${call.id}/decision`,
      "POST",
    )[0];
    const d = JSON.parse(raw(decision));
    const body = {
      request_id: d.request_id,
      proposal_digest: d.proposal_digest,
      decision: d.decision,
    };
    fetch = fetchOne(decision, body);
    expect(await toolClient.decide(call.id, turn.id, body, false)).toEqual(d);
    expect(call.decision).toEqual(d);
    expect(fetch).toHaveBeenCalledTimes(1);
    for (const row of rows(v, `/api/v1/chat/turns/${turn.id}`)) {
      fetch = fetchOne(row);
      expect(await chatClient.turn(turn.id)).toEqual(JSON.parse(raw(row)));
      expect(fetch).toHaveBeenCalledTimes(1);
    }
    if (name === "target") {
      for (const row of rows(v, "/api/v1/chat/tools/targets")) {
        fetch = fetchOne(row);
        const inspected = await toolClient.targets();
        expect(inspected).toEqual(JSON.parse(raw(row)));
        expect(inspected.targets).toContainEqual(call.result.target);
        expect(inspected.draft_revision).toBeGreaterThanOrEqual(
          call.result.after_revision,
        );
        expect(fetch).toHaveBeenCalledTimes(1);
      }
    }
    if (name === "skill") {
      for (const row of rows(
        v,
        `/api/v1/chat/tools/skills/${call.result.skill.id}`,
      )) {
        fetch = fetchOne(row);
        // The shipped requested-ID/full-record parser, not just chatJSON.
        const inspected = await toolClient.skill(call.result.skill.id);
        expect(inspected).toEqual(JSON.parse(raw(row)));
        expect(inspected.skill).toEqual(call.result.skill);
        expect(inspected.draft_revision).toBeGreaterThanOrEqual(
          call.result.after_revision,
        );
        expect(fetch).toHaveBeenCalledTimes(1);
      }
      for (const row of rows(v, "/api/v1/chat/tools/skills")) {
        fetch = fetchOne(row);
        expect(await toolClient.skills()).toEqual(JSON.parse(raw(row)));
        expect(fetch).toHaveBeenCalledTimes(1);
      }
    }
  },
);

// These negative bodies are explicitly SYNTHETIC derivatives, never captures.
it.each([
  "wrong-requested-ID",
  "missing-safety-field",
  "extra-created-at",
  "unequal-locales",
  "changed-safety-rule",
  "float-revision-token",
  "duplicate-key",
] as const)(
  "SYNTHETIC current Skill detail derivative rejects: %s",
  async (fault) => {
    const { v, saved } = context("skill");
    const id = saved.calls[1].result.skill.id;
    const row = rows(v, `/api/v1/chat/tools/skills/${id}`)[0];
    const value = JSON.parse(raw(row));
    if (fault === "wrong-requested-ID") value.skill.id = "different-skill-id";
    if (fault === "missing-safety-field") delete value.skill.safety_rules;
    if (fault === "extra-created-at")
      value.skill.created_at = "2026-01-01T00:00:00Z";
    if (fault === "unequal-locales") value.skill.instructions.ko += "changed";
    if (fault === "changed-safety-rule")
      value.skill.safety_rules[0].en += "changed";
    let derivative = JSON.stringify(value);
    if (fault === "float-revision-token")
      derivative = derivative.replace(
        /"draft_revision":(\d+)/,
        '"draft_revision":$1.0',
      );
    if (fault === "duplicate-key")
      derivative = derivative.replace(
        '"schema_version":1',
        '"schema_version":1,"schema_version":1',
      );
    expect(derivative).not.toBe(raw(row));
    const fetch = fetchOne(row, undefined, derivative);
    await expect(toolClient.skill(id)).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
  },
);

it.each([
  "wrong-audit-action",
  "wrong-revision",
  "mismatched-full-record",
  "extra-authority",
  "wrong-proposal-digest",
] as const)(
  "SYNTHETIC current Skill saved derivative rejects: %s",
  async (fault) => {
    const { turn, finals } = context("skill");
    const row = finals[1];
    const value = JSON.parse(raw(row));
    const call = value.calls[1];
    if (fault === "wrong-audit-action")
      call.result.audit.action = "target.created";
    if (fault === "wrong-revision") call.result.after_revision += 1;
    if (fault === "mismatched-full-record") {
      call.result.skill.instructions.en += "changed";
      call.result.skill.instructions.ko += "changed";
    }
    if (fault === "extra-authority")
      call.result.skill.allowed_operations = ["execute"];
    if (fault === "wrong-proposal-digest")
      call.proposal.digest = "0".repeat(64);
    const fetch = fetchOne(row, undefined, JSON.stringify(value));
    await expect(toolClient.tools(turn.id)).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
  },
);
