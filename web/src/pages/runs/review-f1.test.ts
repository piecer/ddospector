import { afterEach, expect, it, vi } from "vitest";
import { RunsController } from "./controller";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { canonical } from "../scenarios/json";
import { runAPI } from "./transport";
import { RunError } from "./errors";
import type { Detail } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function held() {
  const { d, r } = await receiptFixture();
  let text: string | null = canonical(r);
  let removeFails = true;
  const remove = vi.fn(() => {
    if (removeFails) throw Error("remove denied");
    text = null;
  });
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: (_key, value) => { text = value; },
    removeItem: remove,
  });
  await store.initialize();
  const c = new RunsController(store);
  const v = c.select(d.run.id);
  const get = vi.spyOn(runAPI, "get").mockResolvedValue(d);
  const cancel = vi.spyOn(runAPI, "cancel").mockRejectedValue(Error("must not cancel"));
  await c.read();
  expect(store.notice).toBe("RECOVERY_CLEAR_UNCONFIRMED");
  expect(v.detail).toEqual(d);
  return { c, v, d, r, store, get, cancel, remove,
    text: () => text, allowRemove: () => { removeFails = false; } };
}

it.each(["RUN_NOT_FOUND", "RUN_DB_UNAVAILABLE", "RUN_CLIENT_TIMEOUT", "invalid"])(
  "F1 replay ACK followed by %s stops timers and preserves held A until explicit read",
  async (failure) => {
    const h = await held();
    h.v.stop();
    vi.useFakeTimers();
    // An explicit successful read schedules a timer on the real shipped observer.
    await h.c.read();
    const checkpoint = h.store.receipt!.checkpoint;
    const saved = h.text();
    const removes = h.remove.mock.calls.length;
    let release!: (d: Detail) => void;
    const post = vi.spyOn(runAPI, "create").mockImplementation(() => new Promise((ok) => { release = ok; }));
    const replay = h.c.replay();
    await vi.waitFor(() => expect(post).toHaveBeenCalledOnce());
    // Timer already exists when replay starts; it must not survive failure,
    // including work queued behind this receipt's serialized replay.
    await vi.advanceTimersByTimeAsync(1000);
    if (failure === "invalid") {
      h.get.mockResolvedValue({ ...h.d, run: { ...h.d.run, event_count: 0 } });
    } else {
      h.get.mockRejectedValue(new RunError(failure));
    }
    const before = h.get.mock.calls.length;
    release(h.d);
    await replay;
    expect.soft(h.v.stale).toBe(true);
    expect.soft(h.v.canCancel).toBe(false);
    expect.soft(h.v.error).toBe(failure === "invalid" ? "RUN_CLIENT_INVALID" : failure);
    await vi.advanceTimersByTimeAsync(5000);
    expect.soft(h.get).toHaveBeenCalledTimes(before + 1);
    expect.soft(h.v.timer).toBeNull();
    expect(h.v.detail).toEqual(h.d);
    expect(h.store.receipt!.checkpoint).toEqual(checkpoint);
    expect(h.text()).toBe(saved);
    expect(h.remove).toHaveBeenCalledTimes(removes);
    await h.c.cancel();
    expect.soft(h.cancel).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledExactlyOnceWith(h.r.request);
    h.allowRemove();
    h.get.mockResolvedValue(h.d);
    await h.c.read();
    expect(h.v.stale).toBe(false);
    expect(h.v.canCancel).toBe(true);
    expect(h.store.receipt).toBeNull();
    expect(h.text()).toBeNull();
    h.c.leave();
  },
);

it("F1 already-queued automatic poll is dropped after replay GET failure", async () => {
  const h = await held();
  h.v.stop();
  vi.useFakeTimers();
  await h.c.read();
  let release!: (d: Detail) => void;
  const post = vi.spyOn(runAPI, "create").mockImplementation(() => new Promise((ok) => { release = ok; }));
  const replay = h.c.replay();
  // Deliver the existing timer before the receipt turn starts: poll queues
  // behind replay, so cancelling the timer at replay start is insufficient.
  vi.advanceTimersByTime(1000);
  expect(h.v.reading).toBe(true);
  await vi.waitFor(() => expect(post).toHaveBeenCalledOnce());
  const before = h.get.mock.calls.length;
  h.get.mockRejectedValue(new RunError("RUN_NOT_FOUND"));
  release(h.d);
  await replay;
  await vi.advanceTimersByTimeAsync(5000);
  expect(h.get).toHaveBeenCalledTimes(before + 1);
  expect(h.v.reading).toBe(false);
  expect(h.v.stale).toBe(true);
  expect(h.v.detail).toEqual(h.d);
  expect(h.store.receipt).not.toBeNull();
  h.c.leave();
});

it("F1 off-view A replay failure leaves verified B fresh and cancellable", async () => {
  const h = await held();
  const b = { ...h.d, run: { ...h.d.run,
    id: "b0000000-0000-4000-8000-000000000001",
    request_id: "b0000000-0000-4000-8000-000000000002", ordinal: 2 } };
  const v = h.c.select(b.run.id);
  h.get.mockResolvedValue(b);
  await h.c.read();
  v.stop();
  vi.spyOn(runAPI, "create").mockResolvedValue(h.d);
  h.get.mockRejectedValue(new RunError("RUN_NOT_FOUND"));
  await h.c.replay();
  expect(v.detail).toEqual(b);
  expect(v.stale).toBe(false);
  expect(v.error).toBeNull();
  expect(v.canCancel).toBe(true);
  expect(h.store.receipt!.request).toEqual(h.r.request);
  h.c.leave();
});
