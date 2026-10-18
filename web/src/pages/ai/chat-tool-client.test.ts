import { afterEach, expect, it, vi } from "vitest";
import * as client from "./chat-client";
import { response, session, turn, tid, rid, sid } from "./chat-test-fixtures";
import {
  grant,
  drid,
  gid,
  call,
  decision,
  transcript,
  textHash,
} from "./chat-tool-test-fixtures";
const tools = () =>
  (
    client as unknown as {
      toolClient: {
        grant(
          s: unknown,
          request: string,
          turnRequest: string,
          text: string,
        ): Promise<unknown>;
        submit(s: unknown, g: unknown, text: string): Promise<unknown>;
        tools(id: string): Promise<unknown>;
        decide(id: string, turn: string, input: unknown): Promise<unknown>;
      };
    }
  ).toolClient;
afterEach(() => vi.unstubAllGlobals());
it("binds exact next-message grant and uses the real tool-turn route; lost acknowledgements are GET-only", async () => {
  const s = { ...session, sequence: 0, active_turn_id: null };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") throw new Error("Lost ACK");
    if (url.includes("tool-grants/by-request")) return response(grant);
    if (url.includes("turns/by-request")) return response(turn);
    throw Error("Unexpected URL");
  });
  vi.stubGlobal("fetch", fetch);
  const g = await tools().grant(s, drid, rid, "hello");
  expect(g).toEqual(grant);
  expect(await tools().submit(s, g, "hello")).toEqual(turn);
  expect(fetch.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
    ["/api/v1/chat/tool-grants", "POST"],
    [`/api/v1/chat/tool-grants/by-request/${drid}`, "GET"],
    [`/api/v1/chat/sessions/${sid}/tool-turns`, "POST"],
    [`/api/v1/chat/turns/by-request/${rid}`, "GET"],
  ]);
  expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({
    request_id: drid,
    session_id: sid,
    turn_request_id: rid,
    expected_sequence: 0,
    text: "hello",
  });
  expect(JSON.parse(fetch.mock.calls[2][1]!.body as string)).toEqual({
    request_id: rid,
    expected_sequence: 0,
    text: "hello",
    grant_id: gid,
  });
  fetch.mockImplementation(async () =>
    response({ ...grant, text_sha256: textHash("foreign") }),
  );
  await expect(tools().grant(s, drid, rid, "hello")).rejects.toThrow();
});
it("tool-turn admission rechecks caller authority after asynchronous grant binding and before dispatch", async () => {
  const fetch = vi.fn(async () => response(turn, 202));
  vi.stubGlobal("fetch", fetch);
  const submit = tools().submit as (
    s: unknown,
    g: unknown,
    text: string,
    admit: () => boolean,
  ) => Promise<unknown>;
  await expect(
    submit(
      { ...session, sequence: 0, active_turn_id: null },
      grant,
      "hello",
      () => false,
    ),
  ).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it("binds decision recovery to request/call/proposal/value; approval ACK is not a saved receipt", async () => {
  const input = {
    request_id: drid,
    proposal_digest: call.proposal.digest,
    decision: "approve",
  };
  let wrong = false;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") throw Error("Lost ACK");
    expect(url).toBe(`/api/v1/chat/turns/${tid}/tools`);
    return response({
      ...transcript,
      revision: 2,
      calls: [
        {
          ...call,
          status: "executing",
          decision: { ...decision, request_id: wrong ? rid : drid },
        },
      ],
    });
  });
  vi.stubGlobal("fetch", fetch);
  expect(await tools().decide(call.id, tid, input)).toEqual(decision);
  expect(fetch.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(
    1,
  );
  expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual(input);
  wrong = true;
  await expect(tools().decide(call.id, tid, input)).rejects.toThrow();
});
it("rejects raw UTF8/duplicate keys/oversized responses and foreign transcript identity", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  for (const body of [
    '{"schema_version":1,"schema_version":1}',
    new Uint8Array([0xff]),
    " ".repeat(1048577),
  ]) {
    fetch.mockResolvedValue(
      new Response(body, { headers: { "Content-Type": "application/json" } }),
    );
    await expect(tools().tools(tid)).rejects.toThrow();
  }
  fetch.mockResolvedValue(response({ ...transcript, turn_id: rid }));
  await expect(tools().tools(tid)).rejects.toThrow();
});
