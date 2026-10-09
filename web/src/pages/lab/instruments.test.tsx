import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { PageProps } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { InstrumentsPage } from "./index";

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

describe("InstrumentsPage", () => {
  it.each([
    [
      "en",
      "No instruments configured",
      "Prepare an MCP server draft",
      "Discover instruments",
      "Instrument discovery and hardware control are not implemented.",
    ],
    [
      "ko",
      "구성된 계측기가 없습니다",
      "MCP 서버 초안 준비",
      "계측기 검색",
      "계측기 검색과 하드웨어 제어는 구현되지 않았습니다.",
    ],
  ] as const)(
    "provides an honest next step without device access in %s",
    (locale, empty, next, discover, reason) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const page = props({ locale });
      render(<InstrumentsPage {...page} />);
      expect(screen.getByRole("heading", { name: empty })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: discover })).toBeDisabled();
      expect(screen.getByText(reason)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: next }));
      expect(page.navigate).toHaveBeenCalledWith("mcp-servers");
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("renders supplied inventory without inventing connectivity", () => {
    const data = workspaceFixture();
    data.instruments = [
      {
        id: "synthetic-instrument",
        name: "Synthetic capture node",
        role: "observer",
        status: "unconfigured",
      },
    ];
    render(<InstrumentsPage {...props({ data })} />);
    expect(
      screen.getByRole("cell", { name: "Synthetic capture node" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Inventory records are not live connection evidence."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No instruments configured"),
    ).not.toBeInTheDocument();
  });
});
