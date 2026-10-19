// Synthetic protocol controls, not production responses.
import { afterEach, expect, it, vi } from "vitest";
import { toolClient } from "./chat-tool-client";
import { parseGrant, parseToolRuntime } from "./chat-tool-wire";
import { grant, drid } from "./chat-tool-test-fixtures";
import { skillGrant, skillRuntime } from "./chat-skill-test-fixtures";
import { session, rid, response, turn } from "./chat-test-fixtures";
import type { RequestedAuthority } from "./chat-tool-types";
const { proposal_fields, ...common } = grant;
void proposal_fields;
const targetGrant = {
  ...common,
  schema_version: 2,
  scope: "target_create",
  read_scope: ["targets", "target"],
  proposal_tools: ["target_create"],
};
const authorities = [
  "agent_v1",
  "target_create_v2",
  "skill_create_v3",
] as const;
const grants = [grant, targetGrant, skillGrant];
const s = {
  ...session,
  schema_version: 1 as const,
  locale: "en" as const,
  sequence: 0,
  active_turn_id: null,
};
afterEach(() => vi.unstubAllGlobals());
it("U2 binds exact v3 request and pending pre-submit authority", async () => {
  expect(parseToolRuntime(skillRuntime)).toEqual(skillRuntime);
  const fetch = vi.fn(async (u: string, _i?: RequestInit) =>
    response(u.includes("tool-turns") ? turn : skillGrant),
  );
  vi.stubGlobal("fetch", fetch);
  const g = await toolClient.grant(s, drid, rid, "hello", "skill_create_v3");
  expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({
    schema_version: 3,
    scope: "skill_create",
    request_id: drid,
    session_id: s.id,
    turn_request_id: rid,
    expected_sequence: 0,
    text: "hello",
  });
  expect(
    await toolClient.submit(s, g, "hello", () => true, "skill_create_v3"),
  ).toEqual(turn);
});
for (let a = 0; a < 3; a++)
  for (let b = 0; b < 3; b++)
    if (a !== b) {
      it(`U2 ordered ${authorities[a]} to ${authorities[b]} rejects POST recovery and pre-submit`, async () => {
        const fetch = vi.fn(async (_u: string, _i?: RequestInit) =>
          response(grants[b]),
        );
        vi.stubGlobal("fetch", fetch);
        await expect(
          toolClient.grant(
            s,
            drid,
            rid,
            "hello",
            authorities[a] as RequestedAuthority,
          ),
        ).rejects.toThrow();
        expect(
          fetch.mock.calls.filter(([, i]) => i?.method === "POST"),
        ).toHaveLength(1);
        await expect(
          toolClient.recoverGrant(
            s,
            drid,
            rid,
            "hello",
            authorities[a] as RequestedAuthority,
          ),
        ).rejects.toThrow();
        fetch.mockClear();
        await expect(
          toolClient.submit(
            s,
            parseGrant(grants[b]),
            "hello",
            () => true,
            authorities[a] as RequestedAuthority,
          ),
        ).rejects.toThrow();
        expect(fetch).not.toHaveBeenCalled();
      });
    }
it.each([
  "request_id",
  "session_id",
  "turn_request_id",
  "expected_sequence",
  "profile_id",
  "settings_revision",
  "text_sha256",
])("U2 rejects altered v3 commitment %s", async (key) => {
  const bad = {
    ...skillGrant,
    [key]:
      key.endsWith("revision") || key === "expected_sequence"
        ? 1
        : key === "profile_id"
          ? "foreign"
          : key === "text_sha256"
            ? "a".repeat(64)
            : "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(bad)),
  );
  await expect(
    toolClient.recoverGrant(s, drid, rid, "hello", "skill_create_v3"),
  ).rejects.toThrow();
});

for (let a = 0; a < 3; a++)
  for (let b = 0; b < 3; b++)
    if (a !== b)
      it(`U2 acknowledged wrong ${authorities[b]} cannot be laundered by matching GET ${authorities[a]}`, async () => {
        const fetch = vi.fn(async (_u: string, i?: RequestInit) =>
          response(i?.method === "POST" ? grants[b] : grants[a]),
        );
        vi.stubGlobal("fetch", fetch);
        await expect(
          toolClient.grant(s, drid, rid, "hello", authorities[a]),
        ).rejects.toThrow();
        expect(fetch).toHaveBeenCalledTimes(2);
        expect(fetch.mock.calls.map(([, i]) => i?.method)).toEqual([
          "POST",
          "GET",
        ]);
      });
