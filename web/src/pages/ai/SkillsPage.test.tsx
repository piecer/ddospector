import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SkillsPage } from "./index";
import { aiFixture, createdSkill, jsonResponse } from "./testFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Skills instruction catalog", () => {
  it("refreshes open details from current data and reports a removed Skill honestly", async () => {
    const props = aiFixture();
    const { rerender } = render(<SkillsPage {...props} />);
    await userEvent.click(
      screen.getAllByRole("button", { name: "View instructions" })[0],
    );
    const updated = {
      ...props.data,
      skills: props.data.skills.map((skill) => ({
        ...skill,
        instructions: {
          en: "Synthetic updated instructions",
          ko: "테스트 변경된 지침",
        },
      })),
    };
    rerender(<SkillsPage {...props} data={updated} />);
    expect(
      within(screen.getByRole("dialog")).getByText(
        "Synthetic updated instructions",
      ),
    ).toBeVisible();
    rerender(<SkillsPage {...props} data={{ ...props.data, skills: [] }} />);
    expect(
      within(screen.getByRole("dialog")).getByText(
        "This Skill is no longer available in the current workspace.",
      ),
    ).toBeVisible();
  });

  it("disables editing during a save and distinguishes saved data from a failed refresh", async () => {
    const props = aiFixture();
    props.refresh = vi
      .fn()
      .mockRejectedValueOnce(new Error("Synthetic refresh failure"))
      .mockResolvedValueOnce(undefined);
    let resolve!: (value: Response) => void;
    const fetchMock = vi.fn().mockReturnValue(
      new Promise<Response>((done) => {
        resolve = done;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SkillsPage {...props} locale="ko" />);
    fireEvent.change(screen.getByLabelText("스킬 이름"), {
      target: { value: "Custom synthetic guide" },
    });
    fireEvent.change(screen.getByLabelText("설명"), {
      target: { value: "Custom description" },
    });
    fireEvent.change(screen.getByLabelText("지침"), {
      target: { value: "Review only, do not execute." },
    });
    expect(screen.getByLabelText("지침")).toHaveAttribute("maxlength", "8000");
    await userEvent.click(
      screen.getByRole("button", { name: "스킬 초안 저장" }),
    );
    expect(screen.getByLabelText("지침")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "초안 저장 중…" }),
    ).toBeDisabled();
    await act(async () => {
      resolve(jsonResponse(createdSkill(), 201));
    });
    expect(
      screen.getByText(/저장했지만 워크스페이스를 새로고침하지 못했습니다/),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Custom synthetic guide" }),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "새로고침 재시도" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText(/저장했지만 워크스페이스를 새로고침하지 못했습니다/),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(props.refresh).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["Skill name", "x".repeat(121)],
    ["Description", "x".repeat(1001)],
    ["Instructions", "x".repeat(8001)],
    ["Instructions", "   "],
  ])("rejects invalid %s before making a request", async (label, value) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SkillsPage {...aiFixture()} />);
    fireEvent.change(screen.getByLabelText("Skill name"), {
      target: { value: "Synthetic draft" },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Synthetic description" },
    });
    fireEvent.change(screen.getByLabelText("Instructions"), {
      target: { value: "Synthetic review only" },
    });
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.submit(screen.getByRole("form", { name: "Custom Skill draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Use non-blank text within the field limits.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("retains a failed custom draft and retries through the actual API wrapper", async () => {
    const props = aiFixture();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ message: "Synthetic capacity error" }, 429),
      )
      .mockResolvedValueOnce(jsonResponse(createdSkill(), 201));
    vi.stubGlobal("fetch", fetchMock);
    render(<SkillsPage {...props} />);
    fireEvent.change(screen.getByLabelText("Skill name"), {
      target: { value: "Custom synthetic guide" },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Custom description" },
    });
    fireEvent.change(screen.getByLabelText("Instructions"), {
      target: { value: "Review only, do not execute." },
    });
    await userEvent.selectOptions(
      screen.getByLabelText("Draft category"),
      "analysis",
    );
    expect(screen.getByText("Unsaved draft")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Save Skill draft" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Synthetic capacity error",
    );
    expect(screen.getByLabelText("Skill name")).toHaveValue(
      "Custom synthetic guide",
    );
    expect(screen.getByLabelText("Instructions")).toHaveValue(
      "Review only, do not execute.",
    );
    expect(props.refresh).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Save Skill draft" }),
    );
    expect(
      await screen.findByText(
        "Skill draft saved. No execution permission granted.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Custom synthetic guide" }),
    ).toBeVisible();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/skills",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          name: "Custom synthetic guide",
          description: "Custom description",
          instructions: "Review only, do not execute.",
          category: "analysis",
        }),
      }),
    );
    expect(props.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Skill name")).toHaveValue("");
  });

  it("filters only server-provided entries and distinguishes no matches from an empty catalog", async () => {
    const props = aiFixture();
    const { rerender } = render(<SkillsPage {...props} />);
    await userEvent.selectOptions(
      screen.getByLabelText("Category"),
      "analysis",
    );
    expect(
      screen.queryByRole("heading", { name: "Synthetic policy guide" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Synthetic analysis draft" }),
    ).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText("Source"), "template");
    expect(screen.getByText("No matching instructions")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Clear filters" }),
    );
    await userEvent.type(
      screen.getByLabelText("Search Skills"),
      "synthetic_capability",
    );
    expect(
      screen.getByRole("heading", { name: "Synthetic policy guide" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Synthetic analysis draft" }),
    ).not.toBeInTheDocument();
    rerender(<SkillsPage {...props} data={{ ...props.data, skills: [] }} />);
    expect(screen.getByText("No Skills yet")).toBeVisible();
    expect(screen.queryByText("policy-validation")).not.toBeInTheDocument();
  });

  it("does not interpret missing requirements or safety rules as unrestricted access", async () => {
    render(<SkillsPage {...aiFixture()} />);
    await userEvent.click(
      screen.getAllByRole("button", { name: "View instructions" })[1],
    );
    const dialog = screen.getByRole("dialog", {
      name: "Synthetic analysis draft",
    });
    expect(
      within(dialog).getByText(
        "No capabilities declared; availability is not verified.",
      ),
    ).toBeVisible();
    expect(
      within(dialog).getByText(
        "No operations declared. This does not grant permission.",
      ),
    ).toBeVisible();
    expect(
      within(dialog).getByText(
        "No Skill-specific safety rules supplied. Workspace safeguards still apply.",
      ),
    ).toBeVisible();
  });

  it.each(["en", "ko"] as const)(
    "shows real %s instructions as text and not execution authority",
    async (locale) => {
      const props = aiFixture();
      const skill = props.data.skills[0];
      render(<SkillsPage {...props} locale={locale} />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: locale === "en" ? "Skills" : "스킬",
        }),
      ).toBeVisible();
      expect(
        screen.getByText(
          locale === "en"
            ? /Skills are guidance, not approval authority/
            : /스킬은 지침이며 승인 권한이 아닙니다/,
        ),
      ).toBeVisible();
      expect(screen.getByText(skill.description[locale])).toBeVisible();
      await userEvent.click(
        screen.getAllByRole("button", {
          name: locale === "en" ? "View instructions" : "지침 보기",
        })[0],
      );
      const dialog = screen.getByRole("dialog", { name: skill.name[locale] });
      expect(within(dialog).getByText("test-v2")).toBeVisible();
      expect(within(dialog).getByText("synthetic_capability")).toBeVisible();
      expect(within(dialog).getByText("synthetic_review")).toBeVisible();
      expect(
        within(dialog).getByText(skill.safety_rules[0][locale]),
      ).toBeVisible();
      expect(dialog.querySelector("pre")?.textContent).toBe(
        skill.instructions[locale],
      );
      expect(dialog.querySelector("em")).toBeNull();
    },
  );
});
