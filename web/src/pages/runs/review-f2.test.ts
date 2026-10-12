import { afterEach, expect, it, vi } from "vitest";
import { RunsController } from "./controller";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { canonical } from "../scenarios/json";
import { runAPI } from "./transport";
import type { Detail } from "./types";

const controllers: RunsController[] = [];
afterEach(async () => {
  for (const c of controllers.splice(0)) {
    const v = c.view;
    c.leave();
    if (v) await vi.waitFor(() => expect(v.reading).toBe(false));
  }
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function setup(held = false) {
  const { d, r } = await receiptFixture();
  let text: string | null = held ? canonical(r) : null;
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: (_key, value) => { text = value; },
    removeItem: () => { throw Error("held receipt"); },
  });
  await store.initialize();
  vi.useFakeTimers();
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  const c = new RunsController(store), v = c.select(d.run.id);
  controllers.push(c);
  const get = vi.spyOn(runAPI, "get").mockResolvedValue(d);
  return { c, v, d, get, store, clock: (value: number) => { now = value; } };
}

it.each([300_500, 900_000])("F2 timer scheduled before budget but dispatched at %i cannot GET; explicit read does not reset budget", async (late) => {
  const h = await setup();
  h.clock(299_500);
  await h.c.read();
  expect(h.v.timer).not.toBeNull();
  h.clock(late);
  await vi.advanceTimersByTimeAsync(1000);
  expect.soft(h.get).toHaveBeenCalledTimes(1);
  await vi.waitFor(() => expect(h.v.reading).toBe(false));
  expect(h.v.detail).toEqual(h.d);
  expect(h.v.started).toBe(0);
  h.c.select(h.d.run.id); // same selection, like presentation/locale refresh
  const before = h.get.mock.calls.length;
  await h.c.read();
  expect(h.get).toHaveBeenCalledTimes(before + 1);
  expect(h.v.started).toBe(0);
  expect(h.v.timer).toBeNull();
  await vi.advanceTimersByTimeAsync(5000);
  expect(h.get).toHaveBeenCalledTimes(before + 1);
  h.c.leave();
});

it("F2 captured timer callback never retargets a newly selected B", async () => {
  const h = await setup();
  const timers = vi.spyOn(globalThis, "setTimeout");
  await h.c.read();
  const callback = timers.mock.calls.find((call) => call[1] === 1000)![0] as () => void;
  const b = { ...h.d, run: { ...h.d.run, id: "b0000000-0000-4000-8000-000000000001",
    request_id: "b0000000-0000-4000-8000-000000000002", ordinal: 2 } };
  const view = h.c.select(b.run.id);
  h.get.mockResolvedValue(b);
  await h.c.read();
  // A callback already dispatched by the timer host can run after cancellation.
  callback();
  await vi.advanceTimersByTimeAsync(0);
  expect.soft(h.get).toHaveBeenCalledTimes(2);
  await vi.waitFor(() => expect(view.reading).toBe(false));
  expect(h.c.view).toBe(view);
  expect(view.detail).toEqual(b);
  h.c.leave();
});

it.each(["expiry", "view-change"])("F2 serialized automatic dispatch rechecks %s after waiting behind recovery", async (gate) => {
  const h = await setup(true);
  h.clock(298_000);
  await h.c.read();
  expect(h.store.receipt).not.toBeNull();
  let release!: (d: Detail) => void;
  h.get.mockImplementationOnce(() => new Promise((ok) => { release = ok; }));
  const recovery = h.c.recover();
  await vi.waitFor(() => expect(h.get).toHaveBeenCalledTimes(2));
  h.clock(299_000);
  await vi.advanceTimersByTimeAsync(1000);
  expect(h.v.reading).toBe(true); // automatic work really is queued
  expect(h.get).toHaveBeenCalledTimes(2);
  if (gate === "expiry") h.clock(300_001);
  else h.c.select("b0000000-0000-4000-8000-000000000001");
  release(h.d);
  await recovery;
  await vi.advanceTimersByTimeAsync(0);
  expect.soft(h.get).toHaveBeenCalledTimes(2);
  await vi.waitFor(() => expect(h.v.reading).toBe(false));
  expect(h.store.receipt).not.toBeNull();
  if (gate === "expiry") {
    await h.c.read();
    expect(h.get).toHaveBeenCalledTimes(3);
    expect(h.v.started).toBe(0);
    expect(h.v.timer).toBeNull();
  } else expect(h.c.view!.detail).toBeNull();
  h.c.leave();
});

it("F2 on-time automatic read still occurs exactly once", async () => {
  const h = await setup();
  await h.c.read();
  h.clock(1000);
  await vi.advanceTimersByTimeAsync(1000);
  await vi.waitFor(() => expect(h.v.reading).toBe(false));
  expect(h.get).toHaveBeenCalledTimes(2);
  expect(h.v.detail).toEqual(h.d);
  h.c.leave();
});
