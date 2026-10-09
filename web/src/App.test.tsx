import type { ComponentType } from "react";
import { useState } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Application } from "./App";
import { api } from "./lib/api";
import { navigation } from "./lib/navigation";
import type { RouteId } from "./lib/navigation";
import type { PageProps } from "./lib/contracts";
import { workspaceFixture } from "./test/fixtures";
import { TargetsPage } from "./pages/lab/targets";
import { McpServersPage } from "./pages/lab/mcp-servers";
import { CampaignsPage } from "./pages/operations/CampaignsPage";
const pages = Object.fromEntries(
  navigation.map((item) => [
    item.id,
    ({ data }: PageProps) => (
      <h1>
        {item.id} · {data.meta.mode}
      </h1>
    ),
  ]),
) as Record<RouteId, ComponentType<PageProps>>;
beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/overview");
});
afterEach(() => vi.restoreAllMocks());
describe("real workspace startup boundary", () => {
  for (const item of [
    {
      Page: TargetsPage,
      add: "Add target",
      field: "Name",
      create: "createTarget",
    },
    {
      Page: McpServersPage,
      add: "Add MCP server",
      field: "Name",
      create: "createMcpServer",
    },
    {
      Page: CampaignsPage,
      add: "New campaign",
      field: "Campaign name",
      create: "createCampaign",
    },
  ] as const) {
    it(`keeps an unrelated open ${item.add} draft fail-closed during loading and stale snapshots`, async () => {
      const data = workspaceFixture();
      data.targets = [
        {
          id: "target-1",
          name: "Lab target",
          address: "192.0.2.10",
          kind: "DUT",
          status: "draft",
          created_at: "2026-10-09T00:00:00Z",
        },
      ];
      data.profiles = [
        {
          id: "profile-1",
          name: { en: "Policy replay", ko: "정책 재생" },
          description: { en: "Template", ko: "템플릿" },
          engine: "tcpreplay",
          layer: "L3",
          status: "template",
        },
      ];
      let rejectRead!: (reason: Error) => void;
      vi.spyOn(api, "getWorkspace")
        .mockResolvedValueOnce(data)
        .mockImplementationOnce(
          () =>
            new Promise((_, reject) => {
              rejectRead = reject;
            }),
        )
        .mockResolvedValue(data);
      const create = vi.spyOn(api, item.create);
      let refresh!: PageProps["refresh"];
      function OwningPage(props: PageProps) {
        refresh = props.refresh;
        return <item.Page {...props} />;
      }
      render(<Application pages={{ ...pages, overview: OwningPage }} />);
      await userEvent.click(
        await screen.findByRole("button", { name: item.add }),
      );
      const dialog = screen.getByRole("dialog");
      const field = within(dialog).getByRole("textbox", {
        name: item.field,
      });
      await userEvent.type(field, "Retained unsaved draft");
      const save = within(dialog).getByRole("button", {
        name: "Save draft",
      });
      expect(save).toBeEnabled();
      let read!: Promise<void>;
      act(() => {
        read = refresh().catch(() => undefined);
      });
      expect(field).toBeDisabled();
      expect(save).toBeDisabled();
      await userEvent.click(save);
      expect(create).not.toHaveBeenCalled();
      await act(async () => {
        rejectRead(new Error("workspace unavailable"));
        await read;
      });
      expect(field).toBeDisabled();
      expect(save).toBeDisabled();
      await userEvent.click(save);
      expect(create).not.toHaveBeenCalled();
      // The full browser suite covers native modal dismissal; jsdom does not model inertness.
      await userEvent.click(
        screen.getByRole("button", { name: "Retry connection" }),
      );
      expect(field).toBeEnabled();
      expect(field).toHaveValue("Retained unsaved draft");
      expect(save).toBeEnabled();
      expect(create).not.toHaveBeenCalled();
    });
  }
  it("requests the workspace before rendering API-backed content", async () => {
    const get = vi
      .spyOn(api, "getWorkspace")
      .mockResolvedValue(workspaceFixture());
    render(<Application pages={pages} />);
    expect(
      await screen.findByRole("heading", { name: "overview · OFFLINE" }),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(1);
  });
  it("shows an actual API failure instead of fabricated empty data and supports retry", async () => {
    vi.spyOn(api, "getWorkspace")
      .mockRejectedValueOnce(new Error("internal-path-must-not-leak"))
      .mockResolvedValue(workspaceFixture());
    render(<Application pages={pages} />);
    expect(
      await screen.findByRole("heading", { name: "Local API is unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("internal-path-must-not-leak"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "overview · OFFLINE" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Retry connection" }),
    );
    expect(
      await screen.findByRole("heading", { name: "overview · OFFLINE" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Local API is unavailable" }),
    ).not.toBeInTheDocument();
  });
  it("persists the language selection without changing the saved server configuration", async () => {
    vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
    const first = render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "overview · OFFLINE" });
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Interface language" }),
      "ko",
    );
    expect(localStorage.getItem("aegis.locale")).toBe("ko");
    first.unmount();
    render(<Application pages={pages} />);
    expect(screen.getByRole("combobox", { name: "화면 언어" })).toHaveValue(
      "ko",
    );
    await screen.findByRole("heading", { name: "overview · OFFLINE" });
  });
  it("does not turn an unknown deep link into an endless loading screen", async () => {
    window.history.replaceState(null, "", "/unknown-page");
    vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
    render(<Application pages={pages} />);
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Back to overview" }),
    );
    expect(
      await screen.findByRole("heading", { name: "overview · OFFLINE" }),
    ).toBeInTheDocument();
  });
  it("propagates a failed readback to the owning page rather than reporting refresh success", async () => {
    vi.spyOn(api, "getWorkspace")
      .mockResolvedValueOnce(workspaceFixture())
      .mockRejectedValueOnce(new Error("unavailable"));
    function RefreshingPage({ refresh }: PageProps) {
      const [status, setStatus] = useState("Read snapshot");
      async function read() {
        try {
          await refresh();
          setStatus("Refreshed");
        } catch {
          setStatus("Refresh rejected");
        }
      }
      return <button onClick={() => void read()}>{status}</button>;
    }
    render(<Application pages={{ ...pages, overview: RefreshingPage }} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Read snapshot" }),
    );
    expect(
      await screen.findByRole("button", { name: "Refresh rejected" }),
    ).toBeDisabled();
  });
});
