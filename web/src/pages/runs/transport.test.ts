import { afterEach, expect, it, vi } from "vitest";
import { runAPI } from "./transport";
import { rows, body } from "./testCorpus";
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("times out pending fetch at ten seconds; no retry or mutation fallback", async () => {
  vi.useFakeTimers();
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(() => new Promise(() => {}));
  const p = runAPI.get("a0000000-0000-4000-8000-000000000001");
  const rejection = expect(p).rejects.toMatchObject({
    code: "RUN_CLIENT_TIMEOUT",
  });
  await vi.advanceTimersByTimeAsync(10_000);
  await rejection;
  expect(fetcher).toHaveBeenCalledOnce();
  expect((fetcher.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
});
it.each(["declared", "stream"])(
  "rejects %s over-limit bodies and retires owned body stream",
  async (mode) => {
    const cancel = vi.fn();
    const stream = new ReadableStream({
      start(controller) {
        if (mode === "stream") controller.enqueue(new Uint8Array(32769));
      },
      cancel,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, {
        headers: mode === "declared" ? { "Content-Length": "32769" } : {},
      }),
    );
    await expect(
      runAPI.get("a0000000-0000-4000-8000-000000000001"),
    ).rejects.toMatchObject({ code: "RUN_CLIENT_INVALID" });
    expect(cancel).toHaveBeenCalledOnce();
  },
);
it("reads exact raw bytes from the run selector with no redirects or cache", async () => {
  const row = rows.find((r) => r.state === "QUEUED")!,
    bytes = body(row),
    d = JSON.parse(new TextDecoder().decode(bytes));
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response(bytes));
  expect(await runAPI.get(d.run.id)).toEqual(d);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/offline-runs/" + d.run.id,
    expect.objectContaining({
      method: "GET",
      redirect: "error",
      cache: "no-store",
    }),
  );
});
