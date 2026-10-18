import { afterEach, expect, it, vi } from "vitest";
import { toolClient } from "./chat-tool-client";
import { parseGrant } from "./chat-tool-wire";
import { grantVectors, producer } from "./chat-tool-producer-test-data";
import { textHash } from "./chat-tool-test-fixtures";

const reply = (wire: string, status = 200) =>
  new Response(wire, {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => vi.unstubAllGlobals());

for (const g of [...producer.grants, ...grantVectors]) {
  it(`canonical actual grant: ${g.label}`, async () => {
    const expected = parseGrant(JSON.parse(g.wire));
    const fetch = vi.fn(async () => reply(g.wire, 201));
    vi.stubGlobal("fetch", fetch);
    expect(
      await toolClient.grant(
        g.session,
        g.input.request_id,
        g.input.turn_request_id,
        g.input.text,
      ),
    ).toEqual(expected);
    expect(fetch.mock.calls).toHaveLength(1);
    // Repair the synthetic helper to the actual producer commitment too.
    expect(textHash(g.input.text)).toBe(expected.text_sha256);
  });
  it(`lost ACK canonical GET recovery without rePOST: ${g.label}`, async () => {
    const expected = parseGrant(JSON.parse(g.wire));
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") throw new Error("lost ACK");
      return reply(g.wire);
    });
    vi.stubGlobal("fetch", fetch);
    expect(
      await toolClient.grant(
        g.session,
        g.input.request_id,
        g.input.turn_request_id,
        g.input.text,
      ),
    ).toEqual(expected);
    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["/api/v1/chat/tool-grants", "POST"],
      [`/api/v1/chat/tool-grants/by-request/${g.input.request_id}`, "GET"],
    ]);
  });
}
for (const g of grantVectors.filter((g) => !g.label.includes("boundary"))) {
  it(`GET cannot authorize changed text: ${g.label}`, async () => {
    const fetch = vi.fn(async () => reply(g.wire));
    vi.stubGlobal("fetch", fetch);
    await expect(
      toolClient.recoverGrant(
        g.session,
        g.input.request_id,
        g.input.turn_request_id,
        g.input.text + "!",
      ),
    ).rejects.toThrow();
    expect(fetch.mock.calls).toHaveLength(1);
  });
}
for (const g of grantVectors.filter((g) => g.label.includes("boundary"))) {
  it(`8192-byte producer boundary and 8193-byte refusal: ${g.label}`, async () => {
    expect(new TextEncoder().encode(g.input.text).length).toBe(8192);
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      toolClient.grant(
        g.session,
        g.input.request_id,
        g.input.turn_request_id,
        g.input.text + "x",
      ),
    ).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
}
