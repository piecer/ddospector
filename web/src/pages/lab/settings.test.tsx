import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { PageProps } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { SettingsPage } from "./index";

afterEach(() => vi.unstubAllGlobals());
function props(overrides: Partial<PageProps> = {}): PageProps {
  return {
    data: workspaceFixture(),
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("SettingsPage", () => {
  it.each([
    [
      "en",
      "Settings",
      "Use the language selector in the top bar to switch between English and Korean.",
      "Local development only — not production authentication.",
    ],
    [
      "ko",
      "설정",
      "상단 바의 언어 선택기로 영어와 한국어를 전환하세요.",
      "로컬 개발 전용이며 운영 환경 인증을 제공하지 않습니다.",
    ],
  ] as const)(
    "reports local capabilities without fake toggles in %s",
    (locale, heading, language, boundary) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const data = workspaceFixture();
      data.meta.version = "synthetic-version";
      render(<SettingsPage {...props({ data, locale })} />);
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(screen.getByText(language)).toBeInTheDocument();
      expect(screen.getByText(boundary)).toBeInTheDocument();
      expect(screen.getByText("synthetic-version")).toBeInTheDocument();
      expect(screen.getByText("/api/v1")).toBeInTheDocument();
      expect(screen.queryByRole("switch")).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
      const row = screen.getByRole("row", {
        name: locale === "en" ? /Live execution/ : /실제 실행/,
      });
      expect(
        within(row).getByText(locale === "en" ? "Unavailable" : "사용 불가"),
      ).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("refreshes actual workspace state and reports failures without success claims", async () => {
    const refresh = vi
      .fn()
      .mockRejectedValueOnce(new Error("Synthetic outage"))
      .mockResolvedValueOnce(undefined);
    const page = props({ refresh });
    render(<SettingsPage {...page} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not refresh the workspace",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Workspace refreshed",
    );
    expect(refresh).toHaveBeenCalledTimes(2);
    fireEvent.click(
      screen.getByRole("button", { name: "View local audit log" }),
    );
    expect(page.navigate).toHaveBeenCalledWith("audit");
  });
});
