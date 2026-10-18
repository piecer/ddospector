import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useChat } from "./useChat";
import { runtimeFixture } from "./chat-test-fixtures";
import { grantVectors } from "./chat-tool-producer-test-data";

const g = grantVectors.find((g) => g.label === "combined")!;
const reply = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

for (const mode of ["direct", "lost-ack", "explicit-recovery"] as const) {
  it(`actual canonical grant reaches hook tool-turn dispatch: ${mode}`, async () => {
    let readable = mode !== "explicit-recovery";
    let release: (response: Response) => void = () => undefined;
    const observations: AbortSignal[] = [];
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/runtime")) return reply(runtimeFixture);
      if (url.endsWith("/sessions"))
        return reply({ schema_version: 1, sessions: [g.session] });
      if (url === `/api/v1/chat/sessions/${g.session.id}`)
        return reply({
          schema_version: 1,
          session: g.session,
          turns: [],
          next_before_sequence: null,
        });
      if (url.endsWith("/tool-grants")) {
        if (mode !== "direct") throw new Error("lost grant ACK");
        return new Response(g.wire, {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/tool-grants/by-request/")) {
        if (!readable) throw new Error("not yet readable");
        return new Response(g.wire, {
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/tool-turns"))
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      if (url.includes("/events")) {
        const signal = init!.signal!;
        observations.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    vi.stubGlobal("fetch", fetch);
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce(
        g.input
          .turn_request_id as `${string}-${string}-${string}-${string}-${string}`,
      )
      .mockReturnValueOnce(
        g.input
          .request_id as `${string}-${string}-${string}-${string}-${string}`,
      );
    const { result, unmount } = renderHook(() => useChat("en", true, true));
    await waitFor(() => expect(result.current.runtime?.supported).toBe(true));
    await act(async () => {
      await result.current.open(g.session.id);
    });
    act(() => result.current.setInput(g.input.text));
    let sending: Promise<void>;
    if (mode === "explicit-recovery") {
      await act(async () => {
        await result.current.send(true);
      });
      expect(result.current.phase).toBe("unknown-send");
      expect(result.current.input).toBe(g.input.text);
      act(() => result.current.setInput("later, unapproved editor text"));
      readable = true;
      await act(async () => {
        await result.current.recoverSubmission();
      });
      expect(result.current.phase).toBe("grant-recovered");
      expect(result.current.recoveredGrant?.text).toBe(g.input.text);
      expect(
        fetch.mock.calls.filter(([url]) => url.endsWith("/tool-turns")),
      ).toHaveLength(0);
      act(() => {
        sending = result.current.continueGrant();
      });
    } else {
      act(() => {
        sending = result.current.send(true);
      });
    }
    await waitFor(() =>
      expect(
        fetch.mock.calls.filter(([url]) => url.endsWith("/tool-turns")),
      ).toHaveLength(1),
    );
    act(() => result.current.setInput("later, unapproved editor text"));
    await act(async () => {
      release(
        new Response(g.turn_wire, {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      );
      await sending;
    });
    const posts = fetch.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(posts.map(([url]) => url)).toEqual([
      "/api/v1/chat/tool-grants",
      `/api/v1/chat/sessions/${g.session.id}/tool-turns`,
    ]);
    expect(JSON.parse(posts[1][1]!.body as string)).toEqual({
      request_id: g.input.turn_request_id,
      expected_sequence: g.session.sequence,
      text: g.input.text,
      grant_id: JSON.parse(g.wire).id,
    });
    expect(result.current.uncertain).toBe(false);
    expect(result.current.recoveredGrant).toBeNull();
    expect(result.current.input).toBe("later, unapproved editor text");
    expect(result.current.toolTurns).toEqual([JSON.parse(g.turn_wire).id]);
    unmount();
    expect(observations.every((signal) => signal.aborted)).toBe(true);
  });
}
