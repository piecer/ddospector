// Synthetic B controls; not captured Python B producer output.
import { afterEach, expect, it, vi } from "vitest";
import { toolClient } from "./chat-tool-client";
import { parseGrant, parseToolRuntime } from "./chat-tool-wire";
import { grant, drid, toolRuntime } from "./chat-tool-test-fixtures";
import { session, rid, response, turn } from "./chat-test-fixtures";
export const targetGrant = (() => {
  const { proposal_fields: _fields, ...common } = grant;
  void _fields;
  return {
    ...common,
    schema_version: 2,
    scope: "target_create",
    read_scope: ["targets", "target"],
    proposal_tools: ["target_create"],
  };
})();
const s = {
  ...session,
  schema_version: 1 as const,
  locale: "en" as const,
  sequence: 0,
  active_turn_id: null,
};
afterEach(() => vi.unstubAllGlobals());
it("admits closed dual runtime and target grants without broadening legacy", () => {
  expect(parseGrant(targetGrant)).toEqual(targetGrant);
  expect(parseGrant(grant)).toEqual(grant);
  expect(
    parseToolRuntime({
      ...toolRuntime,
      schema_version: 2,
      tools: [...toolRuntime.tools, "target_create"],
    }).schema_version,
  ).toBe(2);
  expect(() =>
    parseGrant({ ...targetGrant, proposal_fields: ["name"] }),
  ).toThrow();
  expect(() => parseGrant({ ...targetGrant, scope: "agent" })).toThrow();
  expect(() =>
    parseToolRuntime({
      ...toolRuntime,
      tools: [...toolRuntime.tools, "target_create"],
    }),
  ).toThrow();
});
it.each([false, true])(
  "binds requested authority both ways on POST and GET recovery (lost=%s)",
  async (lost) => {
    for (const requested of ["agent_v1", "target_create_v2"] as const) {
      const wrong = requested === "agent_v1" ? targetGrant : grant;
      const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
        if (lost && init?.method === "POST") throw Error("lost ACK");
        return response(wrong);
      });
      vi.stubGlobal("fetch", fetch);
      await expect(
        toolClient.grant(s, drid, rid, "hello", requested),
      ).rejects.toThrow();
      expect(
        fetch.mock.calls.filter(([, i]) => i?.method === "POST"),
      ).toHaveLength(1);
      expect(fetch.mock.calls.some(([u]) => u.includes("tool-turns"))).toBe(
        false,
      );
      await expect(
        toolClient.recoverGrant(s, drid, rid, "hello", requested),
      ).rejects.toThrow();
    }
  },
);
it("constructs exact target request and rebinds authority before submit", async () => {
  const fetch = vi.fn(async (url: string) =>
    response(url.includes("tool-turns") ? turn : targetGrant),
  );
  vi.stubGlobal("fetch", fetch);
  const g = await toolClient.grant(s, drid, rid, "hello", "target_create_v2");
  const init = (fetch.mock.calls as unknown as [string, RequestInit][])[0][1];
  expect(JSON.parse(init.body as string)).toEqual({
    schema_version: 2,
    scope: "target_create",
    request_id: drid,
    session_id: s.id,
    turn_request_id: rid,
    expected_sequence: 0,
    text: "hello",
  });
  fetch.mockClear();
  await expect(
    toolClient.submit(s, g, "hello", () => true, "agent_v1"),
  ).rejects.toThrow();
  await expect(
    toolClient.submit(
      s,
      parseGrant(grant),
      "hello",
      () => true,
      "target_create_v2",
    ),
  ).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
  expect(
    await toolClient.submit(s, g, "hello", () => true, "target_create_v2"),
  ).toEqual(turn);
});
