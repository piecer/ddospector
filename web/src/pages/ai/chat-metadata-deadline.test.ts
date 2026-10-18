import { afterEach, expect, it, vi } from "vitest";
import { ChatRequestError } from "./chat-client";
import { readChatMetadata } from "./chat-metadata";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("rechecks monotonic completion deadline when the timer fires early", async () => {
  vi.useFakeTimers();
  const clock = vi.spyOn(performance, "now").mockReturnValue(1000);
  const controller = new AbortController();
  let calls = 0;
  const pending = readChatMetadata(async () => {
    if (++calls === 1) throw new ChatRequestError("CHAT_BUSY", true);
    return "ready";
  }, controller.signal);
  try {
    await vi.advanceTimersByTimeAsync(0);
    clock.mockReturnValue(1499.85);
    await vi.advanceTimersByTimeAsync(500);
    expect(calls).toBe(1);
    clock.mockReturnValue(1500.85);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toBe("ready");
    expect(calls).toBe(2);
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    controller.abort();
    await pending.catch(() => undefined);
  }
});
