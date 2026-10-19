import type { ComponentType } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Application } from "./App";
import { api } from "./lib/api";
import { navigation, type RouteId } from "./lib/navigation";
import type { PageProps, TargetExpectation } from "./lib/contracts";
import { TargetsPage } from "./pages/lab/targets";
import { target, inspection } from "./pages/ai/chat-target-test-fixtures";
import { workspaceFixture } from "./test/fixtures";
import { response } from "./pages/ai/chat-test-fixtures";
// This isolates Application handoff ownership; ChatTargets exercises the real saved link.
let handoff: TargetExpectation;
vi.mock("./pages/ai/ChatPanel", () => ({
  ChatPanel: ({
    onViewTarget,
  }: {
    onViewTarget: (e: TargetExpectation) => void;
  }) => (
    <button onClick={() => onViewTarget(handoff)}>Synthetic saved link</button>
  ),
}));
const pages = Object.fromEntries(
  navigation.map((n) => [n.id, TargetsPage]),
) as Record<RouteId, ComponentType<PageProps>>;
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("Application owns cloned receipt across unmount, clears it on Back/reload, URL contains ID only", async () => {
  window.history.replaceState(null, "", "/agent");
  localStorage.setItem("aegis.locale", "en");
  vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
  let release!: (r: Response) => void;
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    )
    .mockImplementation(async () => response(inspection));
  vi.stubGlobal("fetch", fetch);
  handoff = { target: { ...target }, after_revision: 3 };
  const app = render(<Application pages={pages} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Synthetic saved link" }),
  );
  expect(window.location.pathname + window.location.search).toBe(
    `/targets?target=${target.id}`,
  );
  expect(window.history.state).toBeNull();
  handoff.target.address = "mutated-alias.test";
  handoff.after_revision = 900;
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await act(async () => release(response(inspection)));
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
  act(() =>
    window.dispatchEvent(
      new PopStateEvent("popstate", {
        state: { expectation: { target, after_revision: 3 } },
      }),
    ),
  );
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  app.unmount();
  render(<Application pages={pages} />);
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
});
