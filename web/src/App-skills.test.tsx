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
import type { PageProps, SkillExpectation } from "./lib/contracts";
import { SkillsPage } from "./pages/ai/SkillsPage";
import {
  draft as skill,
  skillInspection as inspection,
} from "./pages/ai/chat-skill-test-fixtures";
import { workspaceFixture } from "./test/fixtures";
import { response } from "./pages/ai/chat-test-fixtures";
// This isolates Application handoff ownership; ChatSkills exercises the real saved link.
let handoff: SkillExpectation;
vi.mock("./pages/ai/ChatPanel", () => ({
  ChatPanel: ({
    onViewSkill,
  }: {
    onViewSkill: (e: SkillExpectation) => void;
  }) => (
    <button onClick={() => onViewSkill(handoff)}>Synthetic saved link</button>
  ),
}));
const pages = Object.fromEntries(
  navigation.map((n) => [n.id, SkillsPage]),
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
  handoff = { skill: JSON.parse(JSON.stringify(skill)), after_revision: 3 };
  const app = render(<Application pages={pages} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Synthetic saved link" }),
  );
  expect(window.location.pathname + window.location.search).toBe(
    `/skills?skill=${skill.id}`,
  );
  expect(window.history.state).toBeNull();
  handoff.skill.name.en = "mutated-alias";
  handoff.skill.safety_rules[0].ko = "mutated-policy";
  handoff.after_revision = 900;
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  await act(async () => release(response(inspection)));
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
  act(() =>
    window.dispatchEvent(
      new PopStateEvent("popstate", {
        state: { expectation: { skill, after_revision: 3 } },
      }),
    ),
  );
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  app.unmount();
  render(<Application pages={pages} />);
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
});

it("U9 URL-only Skill inspection works when initial workspace is unavailable", async () => {
  window.history.replaceState(null, "", "/skills?skill=skill-test");
  vi.spyOn(api, "getWorkspace").mockRejectedValue(Error("synthetic outage"));
  const fetch = vi.fn(async () => response(inspection));
  vi.stubGlobal("fetch", fetch);
  render(<Application pages={pages} />);
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  expect(screen.queryByRole("button", { name: "Save Skill draft" })).toBeNull();
  expect(
    screen.getByRole("button", {
      name: "Read selected Skill again (GET only)",
    }),
  ).toBeEnabled();
});
