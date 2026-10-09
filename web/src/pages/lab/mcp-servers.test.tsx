import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { api } from "../../lib/api";
import type { McpServer, PageProps } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { McpServersPage } from "./index";

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
// Explicitly synthetic: saved endpoint text must never become a network destination.
const server: McpServer = {
  id: "synthetic-mcp",
  name: "Synthetic observer",
  endpoint: "https://mcp.example.test/mcp",
  transport: "streamable_http",
  usage_instructions:
    "Read measurements only. Ask for approval before any operation.",
  status: "draft",
  tools_count: 0,
  created_at: "2026-10-09T00:00:00Z",
};
function enterServer() {
  fireEvent.click(screen.getByRole("button", { name: "Add MCP server" }));
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: server.name },
  });
  fireEvent.change(screen.getByLabelText("HTTP(S) endpoint"), {
    target: { value: server.endpoint },
  });
  fireEvent.change(screen.getByLabelText("AI usage instructions"), {
    target: { value: server.usage_instructions },
  });
}

describe("McpServersPage", () => {
  it.each([
    "",
    "ftp://mcp.test",
    "https://u:p@mcp.test",
    "https://mcp.test/#fragment",
    "https://mcp.test/#",
    "https://@mcp.test",
    "not a URL",
    "https://mcp.test/" + "x".repeat(512),
  ])(
    "rejects unsafe HTTP endpoint %j without calling the API",
    async (endpoint) => {
      const fetch = vi.fn(() => new Promise(() => {}));
      vi.stubGlobal("fetch", fetch);
      render(<McpServersPage {...props()} />);
      enterServer();
      fireEvent.change(screen.getByLabelText("HTTP(S) endpoint"), {
        target: { value: endpoint },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Enter an HTTP(S) URL",
      );
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("switches to a registry identifier and saves stdio metadata, never a command", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const page = props();
    render(<McpServersPage {...page} />);
    enterServer();
    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "stdio" },
    });
    expect(screen.getByLabelText("Registered server ID")).toHaveValue("");
    expect(screen.queryByLabelText("HTTP(S) endpoint")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Use a registered identifier, not an executable path or shell command.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Registered server ID"), {
      target: { value: "lab-observer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(page.refresh).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/mcp-servers",
      expect.objectContaining({
        body: JSON.stringify({
          name: server.name,
          endpoint: "lab-observer",
          transport: "stdio",
          usage_instructions: server.usage_instructions,
        }),
      }),
    );
  });

  it.each([
    "node server.js",
    "/usr/bin/python",
    "UPPER",
    "bad_id",
    "a".repeat(65),
  ])("rejects non-registry stdio endpoint %j", async (endpoint) => {
    const fetch = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetch);
    render(<McpServersPage {...props()} />);
    enterServer();
    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "stdio" },
    });
    fireEvent.change(screen.getByLabelText("Registered server ID"), {
      target: { value: endpoint },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Use 1–64 lowercase letters, digits, or hyphens",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    ["Name", " ", "Name must contain 1–120 characters"],
    ["Name", "x".repeat(121), "Name must contain 1–120 characters"],
    [
      "AI usage instructions",
      "  ",
      "Usage instructions must contain 1–8,000 characters",
    ],
    [
      "AI usage instructions",
      "x".repeat(8001),
      "Usage instructions must contain 1–8,000 characters",
    ],
  ])("bounds required %s", async (label, value, error) => {
    const fetch = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetch);
    render(<McpServersPage {...props()} />);
    enterServer();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(error);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps a rejected draft and reports the failure in Korean", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ message: "Synthetic API rejection" }), {
          status: 400,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    const page = props({ locale: "ko" });
    render(<McpServersPage {...page} />);
    fireEvent.click(screen.getByRole("button", { name: "MCP 서버 추가" }));
    fireEvent.change(screen.getByLabelText("이름"), {
      target: { value: server.name },
    });
    fireEvent.change(screen.getByLabelText("HTTP(S) 엔드포인트"), {
      target: { value: server.endpoint },
    });
    fireEvent.change(screen.getByLabelText("AI 사용 지침"), {
      target: { value: server.usage_instructions },
    });
    fireEvent.click(screen.getByRole("button", { name: "초안 저장" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "초안을 저장하지 못했습니다",
    );
    expect(screen.getByLabelText("AI 사용 지침")).toHaveValue(
      server.usage_instructions,
    );
    expect(page.refresh).not.toHaveBeenCalled();
  });

  it("offers only a refresh retry after a successful create and failed refresh", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const refresh = vi
      .fn()
      .mockRejectedValueOnce(new Error("Synthetic refresh failure"))
      .mockResolvedValueOnce(undefined);
    render(<McpServersPage {...props({ refresh })} />);
    enterServer();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Draft saved, but the workspace could not refresh",
    );
    expect(screen.getByLabelText("AI usage instructions")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry refresh" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("enforces the registry draft count limit", () => {
    const data = workspaceFixture();
    data.mcp_servers = Array.from({ length: 100 }, (_, index) => ({
      ...server,
      id: `synthetic-${index}`,
    }));
    render(<McpServersPage {...props({ data })} />);
    expect(
      screen.getByRole("button", { name: "Add MCP server" }),
    ).toBeDisabled();
    expect(
      screen.getByText("MCP server limit reached (100 drafts)."),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "en",
      "No MCP server drafts yet",
      "Connect",
      "MCP connections are unavailable in this local draft workspace.",
    ],
    [
      "ko",
      "등록된 MCP 서버 초안이 없습니다",
      "연결",
      "이 로컬 초안 워크스페이스에서는 MCP 연결을 사용할 수 없습니다.",
    ],
  ] as const)(
    "shows an honest empty state and disabled connection in %s",
    (locale, heading, connect, reason) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      render(<McpServersPage {...props({ locale })} />);
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: connect })).toBeDisabled();
      expect(screen.getByText(reason)).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("saves usage instructions through the actual wrapper and reads back real workspace data", async () => {
    const initial = workspaceFixture();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(server), { status: 201 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...initial, mcp_servers: [server] })),
      );
    vi.stubGlobal("fetch", fetch);
    const navigate = vi.fn();
    function Harness() {
      const [data, setData] = useState(initial);
      return (
        <McpServersPage
          {...props({
            data,
            navigate,
            refresh: async () => setData(await api.getWorkspace()),
          })}
        />
      );
    }
    render(<Harness />);
    enterServer();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/mcp-servers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: server.name,
          endpoint: server.endpoint,
          transport: server.transport,
          usage_instructions: server.usage_instructions,
        }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspace",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getByText("Draft · not connected")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: `View instructions: ${server.name}` }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(server.usage_instructions),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Instructions are context, not execution authority.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Assign in Agent workspace" }),
    );
    expect(navigate).toHaveBeenCalledWith("agent");
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
