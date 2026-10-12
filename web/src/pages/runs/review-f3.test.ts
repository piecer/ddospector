import { afterEach, expect, it, vi } from "vitest";
import { RunsController } from "./controller";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { runAPI } from "./transport";
import { RunError } from "./errors";

afterEach(() => vi.restoreAllMocks());

it.each([
  ["recover", false], ["replay", false], ["recover", true], ["replay", true],
] as const)("F3 A success then B lost ACK: %s binds verified B (clear failure=%s)", async (path, held) => {
  const { d } = await receiptFixture();
  let text: string | null = null;
  let removeFails = false;
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: (_key, value) => { text = value; },
    removeItem: () => { if (removeFails) throw Error("remove failure"); text = null; },
  });
  await store.initialize();
  const c = new RunsController(store);
  let a = d;
  const post = vi.spyOn(runAPI, "create").mockImplementation(async (request) => {
    a = { ...d, run: { ...d.run, request_id: request.request_id } };
    return a;
  });
  const get = vi.spyOn(runAPI, "get").mockImplementation(async () => a);
  await c.submit(d.snapshot.scenario);
  expect(c.createdId).toBe(a.run.id);
  expect(store.receipt).toBeNull();
  post.mockRejectedValue(new RunError("RUN_CLIENT_TIMEOUT"));
  await c.submit(d.snapshot.scenario);
  const request = store.receipt!.request;
  expect(request.request_id).not.toBe(a.run.request_id);
  expect.soft(c.createdId).toBeNull();
  const b = { ...d, run: { ...d.run,
    id: "b0000000-0000-4000-8000-000000000001", request_id: request.request_id, ordinal: 2 } };
  const byRequest = vi.spyOn(runAPI, "byRequest");
  post.mockResolvedValue(b);
  // ACK-only and invalid authoritative GET never become verified success.
  const invalid = { ...b, run: { ...b.run, event_count: 0 } };
  get.mockResolvedValue(invalid);
  byRequest.mockResolvedValue(invalid);
  await c[path]();
  expect.soft(c.createdId).toBeNull();
  expect(store.receipt!.request).toEqual(request);
  get.mockResolvedValue(b);
  byRequest.mockResolvedValue(b);
  removeFails = held;
  await c[path]();
  expect.soft(c.createdId).toBe(b.run.id);
  if (held) {
    expect(store.notice).toBe("RECOVERY_CLEAR_UNCONFIRMED");
    expect(store.receipt!.request).toEqual(request);
    expect(store.canSubmit).toBe(false);
    removeFails = false;
    await c.recover();
    expect.soft(c.createdId).toBe(b.run.id);
  }
  expect(store.receipt).toBeNull();
  expect(text).toBeNull();
  if (path === "recover") expect(post).toHaveBeenCalledTimes(2);
  else {
    expect(post).toHaveBeenCalledTimes(4);
    expect(post.mock.calls[2][0]).toEqual(request);
    expect(post.mock.calls[3][0]).toEqual(request);
  }
  c.leave();
});
