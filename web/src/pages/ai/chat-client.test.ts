import { afterEach, expect, it, vi } from "vitest";
import { chatClient, observeTurn } from "./chat-client";
import { parseTurn } from "./chat-wire";
import { response, rid, session, sid, tid, turn } from "./chat-test-fixtures";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const snapshot = (
  t:
    | typeof turn
    | (Omit<typeof turn, "finished_at"> & { finished_at: string }) = turn,
) => ({
  schema_version: 1,
  turn_id: t.id,
  revision: t.revision,
  type: "snapshot",
  turn: t,
  text: null,
});
const sse = (v: unknown) => `event: chat\ndata: ${JSON.stringify(v)}\n\n`;
function stream(text: string, fragment = 37) {
  const bytes = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream({
      start(c) {
        for (let i = 0; i < bytes.length; i += fragment)
          c.enqueue(bytes.slice(i, i + fragment));
        c.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}
it("reads fragmented UTF8 SSE and requires authoritative terminal snapshot", async () => {
  const running = {
    ...turn,
    revision: 4,
    status: "running",
    transport: "open",
    provider_stop: "unknown",
  };
  const done = {
    ...running,
    revision: 6,
    status: "succeeded",
    assistant_text: "한😀",
    transport: "closed",
    finished_at: turn.created_at,
  };
  const fetch = vi.fn().mockResolvedValue(
    stream(
      sse(snapshot(running)) +
        sse({
          schema_version: 1,
          turn_id: tid,
          revision: 5,
          type: "delta",
          turn: null,
          text: "한😀",
        }) +
        sse(snapshot(done)),
      1,
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const seen: string[] = [];
  expect(
    await observeTurn(parseTurn(turn), new AbortController().signal, (t) =>
      seen.push(t.assistant_text),
    ),
  ).toEqual(done);
  expect(seen).toEqual(["", "한😀", "한😀"]);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("EOF is never success; recovery is GET and preserves partial output", async () => {
  const partial = { ...turn, revision: 2, assistant_text: "partial" };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(stream(sse(snapshot(partial))))
    .mockResolvedValueOnce(response(partial));
  vi.stubGlobal("fetch", fetch);
  expect(
    await observeTurn(
      parseTurn(turn),
      new AbortController().signal,
      () => undefined,
    ),
  ).toEqual(partial);
  expect(fetch.mock.calls.map((c) => c[0])).toEqual([
    `/api/v1/chat/turns/${tid}/events?after=1`,
    `/api/v1/chat/turns/${tid}`,
  ]);
});
it("recovers uncertain POST by request without re-sending and binds the acknowledgement", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error("lost ACK"))
    .mockResolvedValueOnce(response(turn));
  vi.stubGlobal("fetch", fetch);
  expect(await chatClient.submit(sid, rid, 0, "hello")).toEqual(turn);
  expect(fetch.mock.calls.map((c) => [c[0], c[1].method])).toEqual([
    [`/api/v1/chat/sessions/${sid}/turns`, "POST"],
    [`/api/v1/chat/turns/by-request/${rid}`, "GET"],
  ]);
});
it("Stop makes a separate finite cancel request followed by readback; terminal wins", async () => {
  const done = {
    ...turn,
    status: "succeeded",
    assistant_text: "won race",
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  };
  const fetch = vi.fn().mockImplementation(async () => response(done));
  vi.stubGlobal("fetch", fetch);
  expect(await chatClient.stop(tid)).toEqual(done);
  expect(fetch.mock.calls.map((c) => [c[0], c[1].method])).toEqual([
    [`/api/v1/chat/turns/${tid}/cancel`, "POST"],
    [`/api/v1/chat/turns/${tid}`, "GET"],
  ]);
});
it("admits maximal escaped assistant SSE snapshots without an upstream 64KiB cap", async () => {
  const text = "\u0001".repeat(65535) + "x";
  const done = {
    ...turn,
    revision: 2,
    status: "succeeded",
    assistant_text: text,
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(stream(sse(snapshot(done)), 4093)),
  );
  expect(
    (
      await observeTurn(
        parseTurn(turn),
        new AbortController().signal,
        () => undefined,
      )
    ).assistant_text,
  ).toBe(text);
});
it.each([
  'event: chat\ndata: {"a":1,"a":2}\n\n',
  "event: other\ndata: {}\n\n",
  "event: chat\ndata: {}\ndata: {}\n\n",
  "event: chat\ndata: " + "x".repeat(1048577) + "\n\n",
  "x".repeat(1048576 + 129),
])(
  "rejects malformed/oversized SSE and explicitly reads back (%#)",
  async (body) => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(stream(body, 65536))
      .mockResolvedValueOnce(response(turn));
    vi.stubGlobal("fetch", fetch);
    expect(
      await observeTurn(
        parseTurn(turn),
        new AbortController().signal,
        () => undefined,
      ),
    ).toEqual(turn);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toBe(`/api/v1/chat/turns/${tid}`);
  },
);
it("rejects fatal UTF8, future/cross-turn deltas and premature EOF through readback", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(new Uint8Array([0xc3, 0x28]), {
        headers: { "Content-Type": "text/event-stream" },
      }),
    )
    .mockResolvedValueOnce(response(turn));
  vi.stubGlobal("fetch", fetch);
  expect(
    await observeTurn(
      parseTurn(turn),
      new AbortController().signal,
      () => undefined,
    ),
  ).toEqual(turn);
  expect(fetch).toHaveBeenCalledTimes(2);
});
it("rejects same-revision changed snapshots rather than overwriting durable text", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      stream(sse(snapshot({ ...turn, assistant_text: "uncommitted" }))),
    )
    .mockResolvedValueOnce(response(turn));
  vi.stubGlobal("fetch", fetch);
  const update = vi.fn();
  expect(
    await observeTurn(parseTurn(turn), new AbortController().signal, update),
  ).toEqual(turn);
  expect(update.mock.calls.map((c) => c[0].assistant_text)).not.toContain(
    "uncommitted",
  );
});
it("requires exactly the bounded history page and older cursor, not hidden omissions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () =>
      response({
        schema_version: 1,
        session: { ...session, sequence: 3 },
        turns: [turn],
        next_before_sequence: null,
      }),
    ),
  );
  await expect(chatClient.history(sid)).rejects.toThrow();
});
it("bounds cumulative observation bytes and recovers with GET only", async () => {
  const data = sse(
    snapshot({ ...turn, revision: 2, assistant_text: "x".repeat(65536) }),
  );
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(stream(data.repeat(33), 65536))
    .mockResolvedValueOnce(
      response({ ...turn, revision: 2, assistant_text: "x".repeat(65536) }),
    );
  vi.stubGlobal("fetch", fetch);
  expect(
    (
      await observeTurn(
        parseTurn(turn),
        new AbortController().signal,
        () => undefined,
      )
    ).revision,
  ).toBe(2);
  expect(fetch.mock.calls.map((c) => c[1].method)).toEqual(["GET", "GET"]);
});
it("cancel has a finite independent timeout and still attempts readback exactly once", async () => {
  vi.useFakeTimers();
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal!.addEventListener(
            "abort",
            () => reject(new Error("timeout")),
            { once: true },
          );
        }),
    )
    .mockResolvedValueOnce(response(turn));
  vi.stubGlobal("fetch", fetch);
  const result = chatClient.stop(tid);
  await vi.advanceTimersByTimeAsync(10000);
  expect(await result).toEqual(turn);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[0][1].signal).not.toBe(fetch.mock.calls[1][1].signal);
  expect(vi.getTimerCount()).toBe(0);
});
it("detaching an event reader causes no cancel POST and no readback replay", async () => {
  let cancelled = false;
  const fetch = vi.fn(
    async (_url: string, init: RequestInit) =>
      new Response(
        new ReadableStream({
          start(c) {
            init.signal!.addEventListener(
              "abort",
              () => c.error(new Error("detached")),
              { once: true },
            );
          },
          cancel() {
            cancelled = true;
          },
        }),
        { headers: { "Content-Type": "text/event-stream" } },
      ),
  );
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  const result = observeTurn(
    parseTurn(turn),
    controller.signal,
    () => undefined,
  );
  const rejected = expect(result).rejects.toThrow("Detached");
  await Promise.resolve();
  controller.abort();
  await rejected;
  expect(fetch).toHaveBeenCalledTimes(1);
  // Errored streams do not invoke the underlying cancel callback; no server mutation.
  expect(cancelled).toBe(false);
});
it.each(["application/json", "text/html"])(
  "never accepts an event response with %s content type",
  async (contentType) => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("<secret>", { headers: { "Content-Type": contentType } }),
      )
      .mockResolvedValueOnce(response(turn));
    vi.stubGlobal("fetch", fetch);
    expect(
      await observeTurn(
        parseTurn(turn),
        new AbortController().signal,
        () => undefined,
      ),
    ).toEqual(turn);
  },
);
it("cannot regress a terminal cancel acknowledgement with older readback", async () => {
  const done = {
    ...turn,
    revision: 3,
    status: "succeeded",
    assistant_text: "terminal won",
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  };
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(response(done))
      .mockResolvedValueOnce(response(turn)),
  );
  await expect(chatClient.stop(tid)).rejects.toThrow();
});
it("does not display fabricated deltas when the pinned session disables streaming", async () => {
  const delta = {
    schema_version: 1,
    turn_id: tid,
    revision: 2,
    type: "delta",
    turn: null,
    text: "forbidden delta",
  };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(stream(sse(snapshot(turn)) + sse(delta)))
    .mockResolvedValueOnce(response(turn));
  vi.stubGlobal("fetch", fetch);
  const update = vi.fn();
  expect(
    await observeTurn(
      parseTurn(turn),
      new AbortController().signal,
      update,
      false,
    ),
  ).toEqual(turn);
  expect(update.mock.calls.map((c) => c[0].assistant_text)).not.toContain(
    "forbidden delta",
  );
});
it("keeps fragmented-frame validation linear instead of re-encoding the entire unfinished frame", async () => {
  const done = {
    ...turn,
    revision: 2,
    status: "succeeded",
    assistant_text: "x".repeat(2048),
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  };
  const body = sse(snapshot(done));
  const incoming = stream(body, 1);
  let encodedCharacters = 0;
  const original = TextEncoder.prototype.encode;
  const spy = vi
    .spyOn(TextEncoder.prototype, "encode")
    .mockImplementation(function (this: TextEncoder, input = "") {
      encodedCharacters += input.length;
      return original.call(this, input);
    });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(incoming));
  try {
    expect(
      await observeTurn(
        parseTurn(turn),
        new AbortController().signal,
        () => undefined,
      ),
    ).toEqual(done);
    expect(encodedCharacters).toBeLessThan(body.length * 20);
  } finally {
    spy.mockRestore();
  }
});
it("rejects a valid history envelope on a noncontract success status", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        response(
          {
            schema_version: 1,
            session,
            turns: [turn],
            next_before_sequence: null,
          },
          201,
        ),
      ),
  );
  await expect(chatClient.history(sid)).rejects.toThrow();
});
it("bounds and validates JSON before exposing history", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        schema_version: 1,
        session,
        turns: [turn],
        next_before_sequence: null,
      }),
    ),
  );
  expect((await chatClient.history(sid)).turns).toEqual([turn]);
});
