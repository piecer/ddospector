import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentPage } from "./index";
import { aiFixture, jsonResponse } from "./testFixtures";

const syntheticPreview = {
  origin: "deterministic_context_preview",
  execution_enabled: false,
  prompt: "Synthetic assembled instructions",
  skill_ids: [],
  mcp_server_ids: [],
};
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Deterministic context boundaries", () => {
  it.each(["", "   ", "x".repeat(2001)])(
    "rejects invalid goals without requesting a preview",
    async (goal) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      render(<AgentPage {...aiFixture()} />);
      expect(screen.getByLabelText("Review goal")).toHaveAttribute(
        "maxlength",
        "2000",
      );
      fireEvent.change(screen.getByLabelText("Review goal"), {
        target: { value: goal },
      });
      fireEvent.submit(
        screen.getByRole("form", { name: "Context preview request" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Enter a review goal of 1–2000 characters, not only whitespace.",
      );
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("invalidates an old preview on edits and retains the new goal after failure", async () => {
    const props = aiFixture();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(syntheticPreview))
      .mockResolvedValueOnce(
        jsonResponse({ message: "Synthetic preview unavailable" }, 503),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<AgentPage {...props} />);
    fireEvent.change(screen.getByLabelText("Review goal"), {
      target: { value: "Synthetic first goal" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble context preview" }),
    );
    expect(
      await screen.findByRole("region", { name: "Assembled instructions" }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Review goal"), {
      target: { value: "Synthetic revised goal" },
    });
    expect(
      screen.queryByRole("region", { name: "Assembled instructions" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble context preview" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Synthetic preview unavailable",
    );
    expect(screen.getByLabelText("Review goal")).toHaveValue(
      "Synthetic revised goal",
    );
    expect(
      screen.queryByRole("region", { name: "Assembled instructions" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Assign Synthetic policy guide" }),
    );
    expect(
      screen.getByRole("button", { name: "Assemble context preview" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Save a valid assignment before previewing/),
    ).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never publishes a late response in a different locale", async () => {
    const props = aiFixture();
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      ),
    );
    const { rerender } = render(<AgentPage {...props} />);
    fireEvent.change(screen.getByLabelText("Review goal"), {
      target: { value: "Synthetic pending goal" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble context preview" }),
    );
    expect(
      screen.getByRole("button", { name: "Assembling context…" }),
    ).toBeDisabled();
    rerender(<AgentPage {...props} locale="ko" />);
    await act(async () => {
      resolve(jsonResponse(syntheticPreview));
    });
    expect(
      screen.queryByRole("region", { name: "조합된 지침" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("검토 목표")).toHaveValue(
      "Synthetic pending goal",
    );
  });

  it.each([
    { origin: "synthetic_llm_reply" },
    { execution_enabled: true },
    { skill_ids: ["unselected-synthetic-skill"] },
    { mcp_server_ids: ["unselected-synthetic-server"] },
    { prompt: "" },
  ])("rejects incompatible preview metadata %j", async (override) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ ...syntheticPreview, ...override })),
    );
    render(<AgentPage {...aiFixture()} />);
    fireEvent.change(screen.getByLabelText("Review goal"), {
      target: { value: "Synthetic review goal" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Assemble context preview" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The preview does not match this saved configuration. Refresh the workspace and try again.",
    );
    expect(
      screen.queryByRole("region", { name: "Assembled instructions" }),
    ).not.toBeInTheDocument();
  });
});
