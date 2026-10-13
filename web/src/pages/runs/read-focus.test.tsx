import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { RunDetails } from "./RunDetails";
import { RunsController } from "./controller";
import { ReceiptStore } from "./storage";
import { runAPI } from "./transport";
import { receiptFixture } from "./testFixtures";
afterEach(() => vi.restoreAllMocks());
function View({ controller }: { controller: RunsController }) {
  useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  return <RunDetails controller={controller} locale="en" onClose={() => {}} />;
}
it.each(["reading", "cancelling"] as const)("read retry stays natively focusable but blocks %s activation", async busy => {
  const { d } = await receiptFixture();
  const c = new RunsController(new ReceiptStore({ getItem: () => null, setItem: () => {}, removeItem: () => {} }));
  const v = c.select(d.run.id);
  v[busy] = true;
  const read = vi.spyOn(c, "read");
  const { rerender, unmount } = render(<View controller={c} />);
  const button = screen.getByRole("button", { name: "Retry run read" });
  expect(button).not.toBeDisabled(); // Native focusability, not Playwright aria semantics.
  expect(button).toHaveAttribute("aria-disabled", "true");
  button.focus();
  fireEvent.click(button);
  expect(read).not.toHaveBeenCalled();
  expect(button).toHaveFocus();
  v[busy] = false;
  rerender(<View controller={c} />);
  expect(button).toHaveAttribute("aria-disabled", "false");
  expect(button).toHaveFocus();
  unmount(); c.leave();
});
it("real controller prevents duplicate GET and read completion does not refocus after user movement", async () => {
  const { d } = await receiptFixture();
  const c = new RunsController(new ReceiptStore({ getItem: () => null, setItem: () => {}, removeItem: () => {} }));
  c.select(d.run.id);
  let release!: (value: typeof d) => void;
  const get = vi.spyOn(runAPI, "get").mockImplementation(() => new Promise(r => { release = r; }));
  vi.spyOn(runAPI, "events").mockRejectedValue(new Error("controlled unavailable events"));
  const { unmount } = render(<View controller={c} />);
  const retry = screen.getByRole("button", { name: "Retry run read" });
  retry.focus();
  fireEvent.click(retry); fireEvent.click(retry); fireEvent.click(retry);
  expect(get).toHaveBeenCalledTimes(1);
  expect(get).toHaveBeenCalledWith(d.run.id);
  const close = screen.getByRole("button", { name: "Close details" });
  close.focus();
  await act(async () => { release(d); });
  await waitFor(() => expect(c.view!.reading).toBe(false));
  expect(close).toHaveFocus();
  expect(c.view!.detail).toEqual(d);
  expect(c.view!.reading).toBe(false);
  unmount(); c.leave();
});
