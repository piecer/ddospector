import { expect, it, vi } from "vitest";
import { RunObserver } from "./observer";
import { ReceiptStore } from "./storage";
import { receiptFixture } from "./testFixtures";
import { canonical } from "../scenarios/json";
it("ordinary viewing B cannot accept A or write to its receipt", async () => {
  const { r, d } = await receiptFixture();
  const storage = {
    getItem: () => canonical(r),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  };
  const store = new ReceiptStore(storage);
  await store.initialize();
  const view = new RunObserver("a0000000-0000-4000-8000-000000000001");
  await expect(view.accept(d, store)).rejects.toThrow();
  expect(view.detail).toBeNull();
  expect(storage.setItem).not.toHaveBeenCalled();
  expect(storage.removeItem).not.toHaveBeenCalled();
});
