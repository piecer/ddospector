import { afterEach, expect, it, vi } from "vitest";
import { RunsController } from "./controller";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { runAPI } from "./transport";
import { RECEIPT_KEY } from "./receipt";
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("unmounted create keeps original request and performs one authoritative GET, never new-key replay", async () => {
  const { d } = await receiptFixture();
  let text: string | null = null;
  const c = new RunsController(
    new ReceiptStore({
      getItem: () => text,
      setItem: (_k, v) => {
        text = v;
      },
      removeItem: () => {
        text = null;
      },
    }),
  );
  await c.start();
  let finish!: (value: typeof d) => void;
  const post = vi.spyOn(runAPI, "create").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const get = vi.spyOn(runAPI, "get");
  const pending = c.submit(d.snapshot.scenario);
  await vi.waitFor(() => expect(post).toHaveBeenCalledOnce());
  const original = JSON.parse(text!);
  c.leave();
  const ack = {
    ...d,
    run: { ...d.run, request_id: original.request.request_id },
  };
  get.mockResolvedValue(ack);
  finish(ack);
  await pending;
  expect(post).toHaveBeenCalledOnce();
  expect(get).toHaveBeenCalledExactlyOnceWith(ack.run.id);
  expect(text).toBeNull();
  expect(c.view).toBeNull();
});
it("failed ordinary Cancel remains stale and cannot repeat before a successful explicit GET", async () => {
  const { d } = await receiptFixture();
  const store = new ReceiptStore({
    getItem: () => null,
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
  await store.initialize();
  const c = new RunsController(store),
    v = c.select(d.run.id);
  const get = vi.spyOn(runAPI, "get").mockResolvedValue(d),
    cancel = vi
      .spyOn(runAPI, "cancel")
      .mockRejectedValue(Error("private raw detail"));
  await c.read();
  await c.cancel();
  expect(v.detail).toEqual(d);
  expect(v.error).toBe("CANCELLATION_UNCONFIRMED");
  expect(v.canCancel).toBe(false);
  await c.cancel();
  expect(cancel).toHaveBeenCalledOnce();
  await c.read();
  expect(get).toHaveBeenCalledTimes(2);
  expect(v.canCancel).toBe(true);
  c.leave();
});
it("does not launch a second read or Cancel while one ordinary GET is outstanding", async () => {
  const { d } = await receiptFixture();
  const store = new ReceiptStore({
    getItem: () => null,
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
  await store.initialize();
  const c = new RunsController(store);
  c.select(d.run.id);
  let finish!: (value: typeof d) => void;
  const get = vi.spyOn(runAPI, "get").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    ),
    cancel = vi.spyOn(runAPI, "cancel");
  const pending = c.read();
  await c.read();
  await c.cancel();
  expect(get).toHaveBeenCalledOnce();
  expect(cancel).not.toHaveBeenCalled();
  finish(d);
  await pending;
  c.leave();
});
it("the first failed read stops automatic observation without losing the verified detail", async () => {
  const { d } = await receiptFixture();
  const store = new ReceiptStore({
    getItem: () => null,
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
  await store.initialize();
  const c = new RunsController(store),
    v = c.select(d.run.id);
  const get = vi
    .spyOn(runAPI, "get")
    .mockResolvedValueOnce(d)
    .mockRejectedValue(Error("offline"));
  await c.read();
  v.stop();
  vi.useFakeTimers();
  await c.read();
  expect(v.stale).toBe(true);
  const count = get.mock.calls.length;
  await vi.advanceTimersByTimeAsync(301_000);
  expect(get).toHaveBeenCalledTimes(count);
  expect(v.detail).toEqual(d);
  expect(v.timer).toBeNull();
  c.leave();
});
it("retired receipt epoch callback cannot reopen A or mutate the new B receipt", async () => {
  const { d, r } = await receiptFixture();
  const { canonical } = await import("../scenarios/json");
  let text: string | null = canonical(r);
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: (_k, v) => {
      text = v;
    },
    removeItem: () => {
      text = null;
    },
  });
  await store.initialize();
  const c = new RunsController(store);
  let release!: (value: typeof d) => void;
  const get = vi.spyOn(runAPI, "get").mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const pending = c.recover();
  await vi.waitFor(() => expect(get).toHaveBeenCalledOnce());
  await store.accept(d, true);
  const request = {
    ...r.request,
    request_id: "a0000000-0000-4000-8000-000000000005",
  };
  await store.reserve(request, d.snapshot.scenario);
  const bText = text;
  c.select("a0000000-0000-4000-8000-000000000006");
  release(d);
  await pending;
  expect(text).toBe(bText);
  expect(store.receipt?.request).toEqual(request);
  expect(c.view?.detail).toBeNull();
  expect(c.error).toBeNull();
  c.leave();
});
it("receipt GET clears without losing the view; subsequent ordinary poll and cancel retain it", async () => {
  const { d, r } = await receiptFixture();
  let text = JSON.stringify(r);
  // Restore requires canonical bytes, not arbitrary JSON insertion order.
  const { canonical } = await import("../scenarios/json");
  text = canonical(r);
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: (_k, v) => {
      text = v;
    },
    removeItem: () => {
      text = null as unknown as string;
    },
  });
  await store.initialize();
  const c = new RunsController(store);
  const view = c.select(d.run.id);
  vi.spyOn(runAPI, "get").mockResolvedValue(d);
  await c.read();
  expect(store.receipt).toBeNull();
  expect(view.detail).toEqual(d);
  await c.read();
  expect(c.view).toBe(view);
  expect(view.detail).toEqual(d);
  c.view?.close();
});
it("stale ordinary callback cannot publish into B after A unmount", async () => {
  const { d } = await receiptFixture(),
    store = new ReceiptStore({
      getItem: () => null,
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  await store.initialize();
  const c = new RunsController(store);
  const a = c.select(d.run.id);
  let release!: (value: typeof d) => void;
  vi.spyOn(runAPI, "get").mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const read = c.read();
  const b = c.select("a0000000-0000-4000-8000-000000000001");
  release(d);
  await read;
  expect(a.detail).toBeNull();
  expect(b.detail).toBeNull();
  expect(c.view).toBe(b);
  expect(store.receipt).toBeNull();
  c.view?.close();
});
it("pending A and verified B cancel independently without touching A storage", async () => {
  const { d, r } = await receiptFixture();
  const { canonical } = await import("../scenarios/json");
  let text = canonical(r);
  const set = vi.fn((_k: string, v: string) => {
      text = v;
    }),
    remove = vi.fn();
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: set,
    removeItem: remove,
  });
  await store.initialize();
  const b = {
    ...d,
    run: {
      ...d.run,
      id: "a0000000-0000-4000-8000-000000000001",
      request_id: "a0000000-0000-4000-8000-000000000002",
      ordinal: 2,
    },
  };
  const cancel = {
    ...b,
    run: {
      ...b.run,
      state: "CANCELLED" as const,
      event_count: 2,
      finished_at: b.run.created_at,
      cancel_requested_at: b.run.created_at,
    },
  };
  const c = new RunsController(store);
  const v = c.select(b.run.id, b.run);
  vi.spyOn(runAPI, "get").mockResolvedValue(b);
  const post = vi.spyOn(runAPI, "cancel").mockResolvedValue(cancel);
  await c.read();
  expect(v.canCancel).toBe(true);
  await c.cancel();
  expect(v.detail?.run.state).toBe("CANCELLED");
  expect(post).toHaveBeenCalledExactlyOnceWith(b.run.id);
  expect(text).toBe(canonical(r));
  expect(set).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
  c.leave();
});
it("ordinary dispatch discovering pending A refuses adoption and requires explicit receipt read", async () => {
  const { d, r } = await receiptFixture();
  const { canonical } = await import("../scenarios/json");
  let text: string | null = canonical({ ...r, checkpoint: null });
  const set = vi.fn((_k: string, v: string) => {
      text = v;
    }),
    remove = vi.fn(() => {
      text = null;
    });
  const store = new ReceiptStore({
    getItem: () => text,
    setItem: set,
    removeItem: remove,
  });
  await store.initialize();
  const c = new RunsController(store),
    v = c.select(d.run.id);
  vi.spyOn(runAPI, "get").mockResolvedValue(d);
  const byRequest = vi.spyOn(runAPI, "byRequest").mockResolvedValue(d);
  await c.read();
  expect(v.detail).toBeNull();
  expect(v.stale).toBe(true);
  expect(store.receipt?.checkpoint).toBeNull();
  expect(set).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
  expect(byRequest).not.toHaveBeenCalled();
  await c.recover();
  expect(byRequest).toHaveBeenCalledExactlyOnceWith(r.request.request_id);
  expect(store.receipt).toBeNull();
  expect(v.detail).toEqual(d);
  c.leave();
});
it("captures request before create, holds ACK until authoritative GET; never retries a lost ACK", async () => {
  const { d } = await receiptFixture();
  let stored: string | null = null;
  const store = new ReceiptStore({
    getItem: () => stored,
    setItem: (_k, v) => {
      stored = v;
    },
    removeItem: () => {
      stored = null;
    },
  });
  await store.initialize();
  const c = new RunsController(store);
  let release!: (value: typeof d) => void;
  const create = vi.spyOn(runAPI, "create").mockImplementation(async (r) => {
    expect(JSON.parse(stored!).request).toEqual(r);
    return { ...d, run: { ...d.run, request_id: r.request_id } };
  });
  const get = vi.spyOn(runAPI, "get").mockImplementation(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const pending = c.submit(d.snapshot.scenario);
  await vi.waitFor(() => expect(get).toHaveBeenCalledOnce());
  expect(store.receipt).not.toBeNull();
  expect(stored).not.toBeNull();
  release({
    ...d,
    run: { ...d.run, request_id: store.receipt!.request.request_id },
  });
  await pending;
  expect(store.receipt).toBeNull();
  expect(stored).toBeNull();
  expect(create).toHaveBeenCalledOnce();
  create.mockRejectedValue(new Error("lost acknowledgment"));
  await c.submit(d.snapshot.scenario);
  expect(store.receipt).not.toBeNull();
  expect(create).toHaveBeenCalledTimes(2);
  expect(get).toHaveBeenCalledOnce();
  expect(store.storage.getItem(RECEIPT_KEY)).not.toBeNull();
});
