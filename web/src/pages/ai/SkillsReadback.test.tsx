// Synthetic responses exercise real SkillsPage, hook, transport and decoder.
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SkillsPage } from "./SkillsPage";
import { aiFixture } from "./testFixtures";
import { draft, skillInspection } from "./chat-skill-test-fixtures";
import { response } from "./chat-test-fixtures";
const selection = () => ({
  id: draft.id,
  expectation: { skill: JSON.parse(JSON.stringify(draft)), after_revision: 3 },
});
afterEach(() => vi.unstubAllGlobals());
it("U8 fresh selected detail stays reachable outside filters, preserves dirty form and never injects receipt into library", async () => {
  const fetch = vi.fn(async () => response(skillInspection));
  vi.stubGlobal("fetch", fetch);
  const p = aiFixture();
  const ui = render(<SkillsPage {...p} />);
  fireEvent.change(screen.getByLabelText("Skill name"), {
    target: { value: "dirty name" },
  });
  fireEvent.change(screen.getByLabelText("Search Skills"), {
    target: { value: "hidden" },
  });
  const selected = selection();
  ui.rerender(<SkillsPage {...p} skillSelection={selected} />);
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  expect(screen.getByLabelText("Skill name")).toHaveValue("dirty name");
  expect(screen.getByLabelText("Search Skills")).toHaveValue("hidden");
  const dialog = screen.getByRole("dialog");
  expect(dialog.querySelector(".ai-page .ai-instructions")).not.toBeNull();
  expect(
    within(dialog).getByRole("heading", { name: draft.name.en.trim() }),
  ).toBeInTheDocument();
  expect(dialog.textContent).toContain(draft.instructions.en);
  expect(dialog.textContent).toContain(draft.safety_rules[1].en);
  expect(dialog.querySelector("script, a, img")).toBeNull();
  expect(document.querySelectorAll(".ai-catalog li")).toHaveLength(0);
  ui.rerender(<SkillsPage {...p} locale="ko" skillSelection={selected} />);
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(screen.getByTestId("skill-readback-open")).toHaveFocus();
});
it("U8 late workspace cannot overwrite inspected bytes or preserve a confirmation badge", async () => {
  let release!: (r: Response) => void;
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(skillInspection))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    );
  vi.stubGlobal("fetch", fetch);
  const p = aiFixture(),
    selected = selection();
  const ui = render(<SkillsPage {...p} skillSelection={selected} />);
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  ui.rerender(
    <SkillsPage
      {...p}
      data={{
        ...p.data,
        skills: [
          { ...draft, name: { en: "stale workspace", ko: "stale workspace" } },
        ],
      }}
      skillSelection={selected}
    />,
  );
  expect(screen.getByTestId("skill-readback-status")).not.toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
  expect(
    within(screen.getByRole("dialog")).queryByText("stale workspace"),
  ).toBeNull();
  await act(async () => {});
  await act(async () => release(response(skillInspection)));
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
});
it.each(["missing", "wrong-id", "below-floor", "changed"])(
  "U8 %s is discrepancy, not unavailable or confirmed",
  async (mode) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        mode === "missing"
          ? response({ code: "CHAT_NOT_FOUND", message: "missing" }, 404)
          : response({
              ...skillInspection,
              draft_revision: mode === "below-floor" ? 2 : 3,
              skill:
                mode === "wrong-id"
                  ? { ...draft, id: "other" }
                  : mode === "changed"
                    ? {
                        ...draft,
                        instructions: { en: "changed", ko: "changed" },
                      }
                    : draft,
            }),
      ),
    );
    render(<SkillsPage {...aiFixture()} skillSelection={selection()} />);
    await waitFor(() =>
      expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
        "data-readback",
        "discrepancy",
      ),
    );
  },
);
it("U9 readonly outage portal permits GET retry and Escape without enabling manual writes or late focus theft", async () => {
  let release!: (r: Response) => void;
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      response({ code: "CHAT_BUSY", message: "busy" }, 429),
    )
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    );
  vi.stubGlobal("fetch", fetch);
  render(
    <>
      <button data-testid="outside">outside</button>
      <fieldset disabled>
        <SkillsPage {...aiFixture()} skillSelection={selection()} />
      </fieldset>
    </>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "unavailable",
    ),
  );
  expect(screen.getByLabelText("Skill name")).toBeDisabled();
  const retry = screen.getByRole("button", {
    name: "Read selected Skill again (GET only)",
  });
  expect(retry).toBeEnabled();
  fireEvent.click(retry);
  await act(async () => {});
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true }));
  screen.getByTestId("outside").focus();
  await act(async () => release(response(skillInspection)));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByTestId("outside")).toHaveFocus();
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([
  "name",
  "description",
  "instructions",
  "category",
  "status",
  "version",
  "allowed_operations",
  "required_capabilities",
  "safety_rules",
])(
  "U8 changed full field %s is discrepancy even when it violates draft policy",
  async (key) => {
    const changed = JSON.parse(JSON.stringify(draft));
    if (["name", "description", "instructions"].includes(key))
      changed[key].ko = "altered locale";
    else if (key === "safety_rules")
      changed.safety_rules[0].en = "altered policy";
    else if (key === "allowed_operations" || key === "required_capabilities")
      changed[key] = ["execute"];
    else changed[key] = "changed";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response({ ...skillInspection, skill: changed })),
    );
    render(<SkillsPage {...aiFixture()} skillSelection={selection()} />);
    await waitFor(() =>
      expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
        "data-readback",
        "discrepancy",
      ),
    );
  },
);

it("U8 new selected handoff retires the ordinary details dialog without remounting the dirty form", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(skillInspection)),
  );
  const p = aiFixture(),
    ui = render(<SkillsPage {...p} />);
  fireEvent.change(screen.getByLabelText("Skill name"), {
    target: { value: "keep draft" },
  });
  fireEvent.click(
    screen.getAllByRole("button", { name: "View instructions" })[0],
  );
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  ui.rerender(<SkillsPage {...p} skillSelection={selection()} />);
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.getByLabelText("Skill name")).toHaveValue("keep draft");
});
