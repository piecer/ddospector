import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { api } from "../../lib/api";
import type { PageProps, WorkspaceSnapshot } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { TargetsPage } from "./index";

afterEach(() => vi.unstubAllGlobals());

// Synthetic responses are test fixtures only; no equipment is contacted.
function props(overrides: Partial<PageProps> = {}): PageProps {
  return {
    data: workspaceFixture(),
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function enterTarget(name = "Test DUT", address = "dut.example.test") {
  fireEvent.click(screen.getByRole("button", { name: "Add target" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: name } });
  fireEvent.change(screen.getByLabelText("IP address or hostname"), {
    target: { value: address },
  });
}

describe("TargetsPage", () => {
  it.each([
    "",
    "https://dut.test",
    "999.1.2.3",
    "host name",
    "bad\u0001host",
    "-bad.test",
    "a".repeat(256),
  ])("rejects invalid addresses without a request: %j", async (address) => {
    const fetch = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetch);
    render(<TargetsPage {...props()} />);
    enterTarget("Test DUT", address);
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter a valid IP address or hostname",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["   ", "a".repeat(121)])(
    "enforces required bounded names: %j",
    async (name) => {
      const fetch = vi.fn(() => new Promise(() => {}));
      vi.stubGlobal("fetch", fetch);
      render(<TargetsPage {...props()} />);
      enterTarget(name);
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Name must contain 1–120 characters",
      );
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("keeps failed API drafts editable, shows an error, and never refreshes", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ message: "Synthetic rejection" }), {
          status: 503,
        }),
      );
    vi.stubGlobal("fetch", fetch);
    const page = props();
    render(<TargetsPage {...page} />);
    enterTarget();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not save the draft",
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Test DUT");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
    expect(page.refresh).not.toHaveBeenCalled();
  });

  it("retries a failed refresh without creating a second draft", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    const refresh = vi
      .fn()
      .mockRejectedValueOnce(new Error("Synthetic refresh failure"))
      .mockResolvedValueOnce(undefined);
    render(<TargetsPage {...props({ refresh })} />);
    enterTarget();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Draft saved, but the workspace could not refresh",
    );
    expect(
      screen.queryByRole("button", { name: "Save draft" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry refresh" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("blocks duplicate submission while saving", () => {
    const fetch = vi.fn(() => new Promise(() => {}));
    vi.stubGlobal("fetch", fetch);
    render(<TargetsPage {...props()} />);
    enterTarget();
    const submit = screen.getByRole("button", { name: "Save draft" });
    fireEvent.click(submit);
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    fireEvent.click(submit);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("shows the draft cap instead of offering an impossible create action", () => {
    const data = workspaceFixture();
    data.targets = Array.from({ length: 100 }, (_, i) => ({
      id: `synthetic-${i}`,
      name: `Synthetic ${i}`,
      address: "host.test",
      kind: "DUT",
      status: "draft",
      created_at: "",
    }));
    render(<TargetsPage {...props({ data })} />);
    expect(screen.getByRole("button", { name: "Add target" })).toBeDisabled();
    expect(
      screen.getByText("Target limit reached (100 drafts)."),
    ).toBeInTheDocument();
  });

  it.each([
    ["en", "No target drafts yet", "Add target"],
    ["ko", "등록된 시험 대상 초안이 없습니다", "시험 대상 추가"],
  ] as const)(
    "keeps an empty workspace honest in %s",
    (locale, heading, action) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      render(<TargetsPage {...props({ locale })} />);
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: action })).toBeEnabled();
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("keeps a Korean target draft after an API failure", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 500 }));
    vi.stubGlobal("fetch", fetch);
    const page = props({ locale: "ko" });
    render(<TargetsPage {...page} />);
    fireEvent.click(screen.getByRole("button", { name: "시험 대상 추가" }));
    fireEvent.change(screen.getByLabelText("이름"), {
      target: { value: "테스트 대상" },
    });
    fireEvent.change(screen.getByLabelText("IP 주소 또는 호스트 이름"), {
      target: { value: "2001:db8::1" },
    });
    fireEvent.change(screen.getByLabelText("역할"), {
      target: { value: "SINK" },
    });
    fireEvent.click(screen.getByRole("button", { name: "초안 저장" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "초안을 저장하지 못했습니다",
    );
    expect(screen.getByLabelText("이름")).toHaveValue("테스트 대상");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/targets",
      expect.objectContaining({
        body: JSON.stringify({
          name: "테스트 대상",
          address: "2001:db8::1",
          kind: "SINK",
        }),
      }),
    );
    expect(page.refresh).not.toHaveBeenCalled();
  });

  it("does not insert a POST response into a snapshot the parent has not refreshed", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ id: "synthetic-only-post", name: "Test DUT" }),
          { status: 201 },
        ),
      );
    vi.stubGlobal("fetch", fetch);
    const page = props();
    render(<TargetsPage {...page} />);
    enterTarget();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("heading", { name: "No target drafts yet" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("cell", { name: "Test DUT" }),
    ).not.toBeInTheDocument();
  });

  it("saves through the draft API and displays only the refreshed snapshot", async () => {
    const initial = workspaceFixture();
    const refreshed: WorkspaceSnapshot = {
      ...initial,
      targets: [
        {
          id: "synthetic-target",
          name: "Test DUT",
          address: "dut.example.test",
          kind: "DUT",
          status: "draft",
          created_at: "2026-10-09T00:00:00Z",
        },
      ],
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(refreshed.targets[0]), { status: 201 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(refreshed)));
    vi.stubGlobal("fetch", fetch);
    function Harness() {
      const [data, setData] = useState(initial);
      return (
        <TargetsPage
          {...props({
            data,
            refresh: async () => setData(await api.getWorkspace()),
          })}
        />
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add target" }));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Test DUT" },
    });
    fireEvent.change(screen.getByLabelText("IP address or hostname"), {
      target: { value: "dut.example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/targets",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Test DUT",
          address: "dut.example.test",
          kind: "DUT",
        }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/workspace",
      expect.objectContaining({ method: "GET" }),
    );
    expect(screen.getByRole("cell", { name: "Test DUT" })).toBeInTheDocument();
    expect(screen.getByText("Draft · not verified")).toBeInTheDocument();
  });
});
