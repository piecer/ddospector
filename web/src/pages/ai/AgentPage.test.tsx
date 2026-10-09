import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentPage } from "./index";
import { api } from "../../lib/api";
import { aiFixture, jsonResponse } from "./testFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Agent instruction assignment", () => {
  it("keeps the save receipt when the parent reads back the same saved profile", async () => {
    const props = aiFixture();
    const profile = {
      ...props.data.agent_profile,
      name: "Synthetic persisted profile",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(profile))
      .mockResolvedValueOnce(
        jsonResponse({ ...props.data, agent_profile: profile }),
      );
    vi.stubGlobal("fetch", fetchMock);
    props.refresh = vi.fn(async () => {
      const data = await api.getWorkspace();
      view.rerender(<AgentPage {...props} data={data} />);
    });
    const view = render(<AgentPage {...props} />);
    fireEvent.change(screen.getByLabelText("Agent name"), {
      target: { value: profile.name },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Save assignment" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      screen.getByText(
        "Assignment saved as a draft. This is not operational approval.",
      ),
    ).toBeVisible();
    expect(screen.getByLabelText("Agent name")).toHaveValue(profile.name);
    expect(
      screen.getByRole("button", { name: "Save assignment" }),
    ).toBeDisabled();
  });

  it("includes requirements and safety guidance when inspecting an assigned Skill", async () => {
    render(<AgentPage {...aiFixture()} />);
    await userEvent.click(screen.getAllByText("Read instructions")[0]);
    expect(screen.getByText("synthetic_capability")).toBeVisible();
    expect(screen.getByText("synthetic_review")).toBeVisible();
    expect(
      screen.getByText("Synthetic rule: require human review."),
    ).toBeVisible();
  });

  it("adopts refreshed saved data without silently replacing an unsaved user draft", async () => {
    const props = aiFixture();
    const { rerender } = render(<AgentPage {...props} />);
    const updated = {
      ...props.data,
      agent_profile: {
        ...props.data.agent_profile,
        name: "Synthetic external update",
        skill_ids: ["synthetic-policy"],
      },
    };
    rerender(<AgentPage {...props} data={updated} />);
    expect(screen.getByLabelText("Agent name")).toHaveValue(
      "Synthetic external update",
    );
    expect(
      screen.getByRole("checkbox", { name: "Assign Synthetic policy guide" }),
    ).toBeChecked();
    fireEvent.change(screen.getByLabelText("Agent name"), {
      target: { value: "Synthetic unsaved work" },
    });
    const newer = {
      ...updated,
      agent_profile: {
        ...updated.agent_profile,
        name: "Synthetic newer server value",
      },
    };
    rerender(<AgentPage {...props} data={newer} />);
    expect(screen.getByLabelText("Agent name")).toHaveValue(
      "Synthetic unsaved work",
    );
    expect(
      screen.getByText(/The saved profile changed while you were editing/),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Save assignment" }),
    ).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Use refreshed profile (discard my edits)",
      }),
    );
    expect(screen.getByLabelText("Agent name")).toHaveValue(
      "Synthetic newer server value",
    );
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it.each(["en", "ko"] as const)(
    "assembles saved %s context through the API, never a simulated model answer",
    async (locale) => {
      const props = aiFixture();
      props.data.agent_profile.skill_ids = ["synthetic-policy"];
      props.data.agent_profile.mcp_server_ids = ["synthetic-mcp"];
      const prompt =
        "Synthetic context only.\n<strong>Do not execute.</strong>";
      const fetchMock = vi
        .fn()
        .mockResolvedValue(
          jsonResponse({
            origin: "deterministic_context_preview",
            execution_enabled: false,
            prompt,
            skill_ids: ["synthetic-policy"],
            mcp_server_ids: ["synthetic-mcp"],
          }),
        );
      vi.stubGlobal("fetch", fetchMock);
      render(<AgentPage {...props} locale={locale} />);
      expect(
        screen.getByText(
          locale === "en"
            ? "Deterministic context assembly — not an LLM response or an executed test."
            : "결정적 컨텍스트 조합이며 LLM 응답이나 실행된 테스트가 아닙니다.",
        ),
      ).toBeVisible();
      fireEvent.change(
        screen.getByLabelText(locale === "en" ? "Review goal" : "검토 목표"),
        { target: { value: "Synthetic review goal" } },
      );
      await userEvent.click(
        screen.getByRole("button", {
          name:
            locale === "en"
              ? "Assemble context preview"
              : "컨텍스트 미리보기 조합",
        }),
      );
      const region = await screen.findByRole("region", {
        name: locale === "en" ? "Assembled instructions" : "조합된 지침",
      });
      expect(region.querySelector("pre")?.textContent).toBe(prompt);
      expect(region.querySelector("strong")).toBeNull();
      expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
        "/api/v1/agent/preview",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ goal: "Synthetic review goal", locale }),
        }),
      );
      expect(props.refresh).not.toHaveBeenCalled();
      expect(
        screen.getByRole("checkbox", {
          name:
            locale === "en"
              ? "Assign Synthetic policy guide"
              : "테스트 정책 지침 할당",
        }),
      ).toBeChecked();
    },
  );

  it("keeps edits on an API failure and does not claim approval or clear the dirty state", async () => {
    const props = aiFixture();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ message: "Synthetic save denied" }, 503),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<AgentPage {...props} locale="ko" />);
    fireEvent.change(screen.getByLabelText("에이전트 이름"), {
      target: { value: "실패 시 보존할 이름" },
    });
    await userEvent.click(
      screen.getByRole("checkbox", { name: "테스트 정책 지침 할당" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "할당 저장" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Synthetic save denied",
    );
    expect(screen.getByLabelText("에이전트 이름")).toHaveValue(
      "실패 시 보존할 이름",
    );
    expect(
      screen.getByRole("checkbox", { name: "테스트 정책 지침 할당" }),
    ).toBeChecked();
    expect(screen.getByText("저장하지 않은 변경 사항")).toBeVisible();
    expect(
      screen.getByText(/스킬은 지침이며 승인 권한이 아닙니다/),
    ).toBeVisible();
    expect(props.refresh).not.toHaveBeenCalled();
  });

  it("blocks unavailable saved references until the operator explicitly removes them", async () => {
    const props = aiFixture();
    props.data.agent_profile.skill_ids = ["missing-synthetic-skill"];
    props.data.agent_profile.mcp_server_ids = ["missing-synthetic-mcp"];
    const expected = {
      name: "Repaired synthetic draft",
      skill_ids: [],
      mcp_server_ids: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({
          ...expected,
          autonomy: "REVIEW_ONLY",
          execution_enabled: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<AgentPage {...props} />);
    fireEvent.change(screen.getByLabelText("Agent name"), {
      target: { value: expected.name },
    });
    expect(
      screen.getByText(/Some assigned references are unavailable/),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Save assignment" }),
    ).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", {
        name: "Remove unavailable Skill: missing-synthetic-skill",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Remove unavailable MCP server: missing-synthetic-mcp",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save assignment" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
        "/api/v1/agent-profile",
        expect.objectContaining({ body: JSON.stringify(expected) }),
      ),
    );
  });

  it.each(["", "   ", "x".repeat(121)])(
    "blocks invalid agent names without sending a request",
    async (name) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      render(<AgentPage {...aiFixture()} />);
      fireEvent.change(screen.getByLabelText("Agent name"), {
        target: { value: name },
      });
      fireEvent.submit(screen.getByRole("form", { name: "Agent assignment" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Enter an agent name of 1–120 characters, not only whitespace.",
      );
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("offers honest empty states and routes to real catalog and registration pages", async () => {
    const props = aiFixture();
    props.data.skills = [];
    props.data.mcp_servers = [];
    render(<AgentPage {...props} />);
    expect(screen.getByText("No Skills available")).toBeVisible();
    expect(screen.getByText("No registered MCP servers")).toBeVisible();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Skill library" }),
    );
    expect(props.navigate).toHaveBeenLastCalledWith("skills");
    await userEvent.click(
      screen.getByRole("button", { name: "Manage servers" }),
    );
    expect(props.navigate).toHaveBeenLastCalledWith("mcp-servers");
  });

  it("saves only selected real Skill and MCP IDs through the actual API wrapper", async () => {
    const props = aiFixture();
    const expected = {
      name: "Synthetic review agent",
      skill_ids: ["synthetic-policy"],
      mcp_server_ids: ["synthetic-mcp"],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({
          ...expected,
          autonomy: "REVIEW_ONLY",
          execution_enabled: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<AgentPage {...props} />);
    fireEvent.change(screen.getByLabelText("Agent name"), {
      target: { value: expected.name },
    });
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Assign Synthetic policy guide" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Assign Synthetic observer" }),
    );
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    expect(
      screen.getByText(props.data.mcp_servers[0].usage_instructions),
    ).toBeVisible();
    expect(screen.getByText("Registered draft · not connected")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Save assignment" }),
    );
    await waitFor(() => expect(props.refresh).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/agent-profile",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(expected),
      }),
    );
    expect(
      screen.getByText(
        "Assignment saved as a draft. This is not operational approval.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save assignment" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run agent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Connect MCP" })).toBeDisabled();
    expect(
      screen.getByText(
        /LIVE execution, LLM inference, and MCP connection are unavailable/,
      ),
    ).toBeVisible();
  });
});
