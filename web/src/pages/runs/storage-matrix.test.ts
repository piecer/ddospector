import { expect, it, vi } from "vitest";
import { canonical, digest } from "../scenarios/json";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { parseReceipt, RECEIPT_KEY } from "./receipt";
async function harness() {
  const { r, d } = await receiptFixture();
  let value: string | null = null;
  const storage = {
    getItem: vi.fn(() => value),
    setItem: vi.fn((_k: string, v: string) => {
      value = v;
    }),
    removeItem: vi.fn(() => {
      value = null;
    }),
  };
  return {
    r,
    d,
    storage,
    get: () => value,
    put: (v: string | null) => {
      value = v;
    },
  };
}
it.each(["before", "after", "silent", "readback"])(
  "initial write %s-effect classification never repeats automatically",
  async (mode) => {
    const h = await harness(),
      c = new ReceiptStore(h.storage);
    await c.initialize();
    h.storage.setItem.mockImplementation((_k, v) => {
      if (mode === "after" || mode === "readback") h.put(v);
      if (mode === "readback")
        h.storage.getItem.mockImplementation(() => {
          throw Error("secret");
        });
      if (mode !== "silent") throw Error("secret");
    });
    const allowed = await c.reserve(h.r.request, h.d.snapshot.scenario);
    expect(allowed).toBe(mode !== "readback");
    expect(c.receipt?.request).toEqual(h.r.request);
    expect(h.storage.setItem).toHaveBeenCalledOnce();
    expect(c.notice).toBe(
      mode === "after"
        ? null
        : mode === "readback"
          ? "RECOVERY_STORAGE_UNKNOWN"
          : "RECOVERY_MEMORY_ONLY",
    );
    if (mode === "readback") {
      expect(c.canSubmit).toBe(false);
      expect(h.storage.removeItem).not.toHaveBeenCalled();
    }
  },
);
it.each(["before", "after", "null", "readback"])(
  "checkpoint update %s preserves strongest memory and reload truth",
  async (mode) => {
    const h = await harness(),
      c = new ReceiptStore(h.storage);
    await c.initialize();
    await c.reserve(h.r.request, h.d.snapshot.scenario);
    const saved = h.get();
    h.storage.setItem.mockClear();
    h.storage.setItem.mockImplementation((_k, v) => {
      if (mode === "after") h.put(v);
      if (mode === "null") h.put(null);
      if (mode === "readback")
        h.storage.getItem.mockImplementation(() => {
          throw Error("secret");
        });
      throw Error("secret");
    });
    await c.accept(h.d, false);
    expect(c.receipt?.checkpoint).toEqual(h.r.checkpoint);
    expect(c.canSubmit).toBe(false);
    expect(c.notice).toBe(
      mode === "after"
        ? null
        : mode === "readback"
          ? "RECOVERY_STORAGE_UNKNOWN"
          : "RECOVERY_CHECKPOINT_UNSAVED",
    );
    if (mode === "before") {
      expect(h.get()).toBe(saved);
      const reloaded = new ReceiptStore(h.storage);
      await reloaded.initialize();
      expect(reloaded.receipt?.checkpoint).toBeNull();
      await c.accept(h.d, false);
      expect(h.storage.setItem).toHaveBeenCalledOnce();
    }
  },
);
it.each(["before", "after", "readback"])(
  "removal %s-effect retains/correctly clears only the verified identity",
  async (mode) => {
    const h = await harness();
    h.put(canonical(h.r));
    const c = new ReceiptStore(h.storage);
    await c.initialize();
    h.storage.removeItem.mockImplementation(() => {
      if (mode !== "before") h.put(null);
      if (mode === "readback")
        h.storage.getItem.mockImplementation(() => {
          throw Error("secret");
        });
      throw Error("secret");
    });
    await c.accept(h.d, true);
    expect(h.storage.removeItem).toHaveBeenCalledOnce();
    expect(c.receipt === null).toBe(mode === "after");
    expect(c.notice).toBe(
      mode === "after"
        ? null
        : mode === "before"
          ? "RECOVERY_CLEAR_UNCONFIRMED"
          : "RECOVERY_STORAGE_UNKNOWN",
    );
    if (mode === "before") {
      await c.recheck();
      expect(c.receipt).not.toBeNull();
      expect(h.storage.removeItem).toHaveBeenCalledOnce();
    }
  },
);
it.each(["invalid", "version", "oversize", "foreign", "advanced"])(
  "interleaved %s storage cannot be overwritten or cleared",
  async (mode) => {
    const h = await harness(),
      c = new ReceiptStore(h.storage);
    await c.initialize();
    await c.reserve(h.r.request, h.d.snapshot.scenario);
    h.storage.setItem.mockClear();
    const request = {
      ...h.r.request,
      request_id: "a0000000-0000-4000-8000-000000000001",
    };
    h.put(
      mode === "invalid"
        ? "{"
        : mode === "version"
          ? canonical({ ...h.r, schema_version: 2 })
          : mode === "oversize"
            ? " ".repeat(2049)
            : mode === "foreign"
              ? canonical({
                  ...h.r,
                  request,
                  request_digest: await digest(request),
                  checkpoint: null,
                })
              : canonical(h.r),
    );
    const prior = h.get();
    await c.recheck();
    expect(h.get()).toBe(prior);
    expect(c.canSubmit).toBe(false);
    expect(h.storage.setItem).not.toHaveBeenCalled();
    expect(h.storage.removeItem).not.toHaveBeenCalled();
    expect(c.notice).toBe(
      ["foreign", "advanced"].includes(mode)
        ? "RECOVERY_IDENTITY_CONFLICT"
        : "RECOVERY_STORAGE_INVALID",
    );
  },
);
it("explicit recheck saves the strongest unsaved checkpoint but cannot resolve the receipt", async () => {
  const h = await harness(),
    c = new ReceiptStore(h.storage);
  await c.initialize();
  await c.reserve(h.r.request, h.d.snapshot.scenario);
  h.storage.setItem.mockImplementation(() => {
    throw Error("quota");
  });
  await c.accept(h.d, false);
  expect(c.notice).toBe("RECOVERY_CHECKPOINT_UNSAVED");
  h.storage.setItem.mockImplementation((_k, v) => h.put(v));
  await c.recheck();
  expect(c.notice).toBeNull();
  expect(await parseReceipt(h.get()!)).toEqual(c.receipt);
  expect(c.receipt?.checkpoint).toEqual(h.r.checkpoint);
  expect(h.storage.removeItem).not.toHaveBeenCalled();
  expect(h.storage.getItem).toHaveBeenCalledWith(RECEIPT_KEY);
});
