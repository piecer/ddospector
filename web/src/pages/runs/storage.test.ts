import { expect, it, vi } from "vitest";
import { ReceiptStore } from "./storage";
import { RECEIPT_KEY } from "./receipt";
import { receiptFixture } from "./testFixtures";
import { canonical } from "../scenarios/json";
function memory(initial: string | null = null) {
  let text = initial;
  return {
    getItem: vi.fn((_key: string) => text),
    setItem: vi.fn((_k: string, v: string) => {
      text = v;
    }),
    removeItem: vi.fn(() => {
      text = null;
    }),
  };
}
it("writes original commitment BEFORE send eligibility; ACK holds until exact GET clears", async () => {
  const { r, d } = await receiptFixture(),
    storage = memory();
  const c = new ReceiptStore(storage);
  await c.initialize();
  expect(await c.reserve(r.request, d.snapshot.scenario)).toBe(true);
  expect(c.receipt?.checkpoint).toBeNull();
  expect(JSON.parse(storage.getItem(RECEIPT_KEY)!)).toEqual(c.receipt);
  await c.accept(d, false);
  expect(c.receipt?.checkpoint?.run.id).toBe(d.run.id);
  expect(storage.removeItem).not.toHaveBeenCalled();
  await c.accept(d, true);
  expect(c.receipt).toBeNull();
  expect(storage.removeItem).toHaveBeenCalledOnce();
  expect(storage.getItem(RECEIPT_KEY)).toBeNull();
});
it("allows proved memory-only send, keeps strongest unsaved checkpoint, and clears only after GET", async () => {
  const { r, d } = await receiptFixture(),
    storage = memory();
  storage.setItem.mockImplementation(() => {
    throw Error("quota");
  });
  const c = new ReceiptStore(storage);
  await c.initialize();
  expect(await c.reserve(r.request, d.snapshot.scenario)).toBe(true);
  expect(c.notice).toBe("RECOVERY_MEMORY_ONLY");
  await c.accept(d, false);
  expect(c.receipt?.checkpoint?.run.id).toBe(d.run.id);
  expect(storage.setItem).toHaveBeenCalledOnce();
  await c.accept(d, true);
  expect(c.receipt).toBeNull();
  expect(storage.removeItem).not.toHaveBeenCalled();
});
it.each(["read", "invalid", "foreign", "remove"])(
  "retains unresolved identity for %s storage fault",
  async (mode) => {
    const { r, d } = await receiptFixture(),
      storage = memory(canonical(r));
    const c = new ReceiptStore(storage);
    if (mode === "read")
      storage.getItem.mockImplementation(() => {
        throw Error("private path");
      });
    if (mode === "invalid")
      storage.getItem.mockReturnValue('{"schema_version":999}');
    await c.initialize();
    if (mode === "read" || mode === "invalid") {
      expect(c.notice).toBe(
        mode === "read"
          ? "RECOVERY_STORAGE_UNKNOWN"
          : "RECOVERY_STORAGE_INVALID",
      );
      expect(storage.setItem).not.toHaveBeenCalled();
    } else {
      if (mode === "foreign")
        storage.setItem(
          RECEIPT_KEY,
          canonical({
            ...r,
            request: {
              ...r.request,
              request_id: "a0000000-0000-4000-8000-000000000001",
            },
          }),
        );
      else
        storage.removeItem.mockImplementation(() => {
          throw Error("denied");
        });
      await c.accept(d, true);
      expect(c.receipt).not.toBeNull();
      expect(c.notice).not.toBeNull();
    }
  },
);
it("restores only the saved identity without writing or replaying", async () => {
  const { r } = await receiptFixture(),
    storage = memory(canonical(r));
  const controller = new ReceiptStore(storage);
  await controller.initialize();
  expect(controller.receipt).toEqual(r);
  expect(storage.getItem).toHaveBeenCalledWith(RECEIPT_KEY);
  expect(storage.setItem).not.toHaveBeenCalled();
  expect(storage.removeItem).not.toHaveBeenCalled();
});
