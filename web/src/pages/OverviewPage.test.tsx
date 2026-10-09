import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OverviewPage } from "./OverviewPage";
import { workspaceFixture } from "../test/fixtures";
describe("honest initial overview", () => {
  it("shows setup and an explicitly planned topology, not measured traffic", async () => {
    const navigate = vi.fn();
    render(
      <OverviewPage
        data={workspaceFixture()}
        locale="en"
        navigate={navigate}
        refresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Validation workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Planned data path · not live telemetry"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/128 tests/)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Add test target" }),
    );
    expect(navigate).toHaveBeenCalledWith("targets");
  });
  it("derives draft counts from the actual API snapshot", () => {
    const data = workspaceFixture();
    data.targets = [
      {
        id: "target-test",
        name: "Test-only target",
        address: "192.0.2.1",
        kind: "DUT",
        status: "draft",
        created_at: "2026-01-01T00:00:00Z",
      },
    ];
    render(
      <OverviewPage
        data={data}
        locale="ko"
        navigate={vi.fn()}
        refresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getByTestId("target-count")).toHaveTextContent("1");
    expect(screen.getByText("구성도 · 실시간 계측 아님")).toBeInTheDocument();
  });
  it("shows the newest actual audit events when the producer returns oldest first", () => {
    const data = workspaceFixture();
    data.audit = Array.from({ length: 6 }, (_, i) => ({
      id: `test-${i}`,
      action: `test_action_${i}`,
      entity_id: `test_entity_${i}`,
      created_at: `2026-01-01T00:00:0${i}Z`,
      origin: "local_operator" as const,
    }));
    render(
      <OverviewPage
        data={data}
        locale="en"
        navigate={vi.fn()}
        refresh={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getByText("test_action_5")).toBeInTheDocument();
    expect(screen.queryByText("test_action_0")).not.toBeInTheDocument();
    expect(data.audit[0].id).toBe("test-0");
  });
});
