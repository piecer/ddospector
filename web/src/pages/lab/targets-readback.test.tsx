// Synthetic current-store observations; receipt bytes never seed inventory.
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { TargetsPage } from "./targets";
import { workspaceFixture } from "../../test/fixtures";
import { target, inspection } from "../ai/chat-target-test-fixtures";
import { response } from "../ai/chat-test-fixtures";
import type { PageProps } from "../../lib/contracts";
afterEach(() => vi.unstubAllGlobals());
it("ID-only missing selection never claims a saved receipt exists", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response({ ...inspection, targets: [] })),
  );
  render(<TargetsPage {...props()} targetSelection={{ id: target.id }} />);
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "mismatch",
    ),
  );
  expect(screen.getByTestId("target-readback-status")).toHaveTextContent(
    "Selected ID is absent",
  );
  expect(screen.getByTestId("target-readback-status")).not.toHaveTextContent(
    "saved receipt remains",
  );
});
function props(): PageProps {
  return {
    data: workspaceFixture(),
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn(),
    targetSelection: {
      id: target.id,
      expectation: { target: { ...target }, after_revision: 3 },
    },
  };
}
it("independently reads and focuses exact full target row, never injects a receipt", async () => {
  let release!: (r: Response) => void;
  const fetch = vi.fn(
    () =>
      new Promise<Response>((r) => {
        release = r;
      }),
  );
  vi.stubGlobal("fetch", fetch);
  render(<TargetsPage {...props()} />);
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "loading",
  );
  expect(
    screen.queryByTestId(`target-row-${target.id}`),
  ).not.toBeInTheDocument();
  await act(async () => {});
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => release(response(inspection)));
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
  const row = screen.getByTestId(`target-row-${target.id}`);
  expect(row).toHaveAttribute("data-selected", "true");
  expect(row).toHaveFocus();
  for (const v of Object.values(target)) expect(row.textContent).toContain(v);
  expect(fetch.mock.calls).toHaveLength(1);
});
it.each(["changed", "missing", "revision"])(
  "reports discrepancy, not lost saved fact: %s",
  async (reason) => {
    const value = {
      ...inspection,
      draft_revision: reason === "revision" ? 2 : 3,
      targets:
        reason === "missing"
          ? []
          : [
              reason === "changed"
                ? { ...target, address: "changed.test" }
                : target,
            ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(value)),
    );
    render(<TargetsPage {...props()} />);
    await waitFor(() =>
      expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
        "data-readback",
        "mismatch",
      ),
    );
    expect(screen.getByTestId("target-readback-status")).toHaveTextContent(
      "saved receipt remains",
    );
  },
);
it("ID-only navigation observes current only and GET retry does not create", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(Error("unavailable"))
    .mockImplementation(async () => response(inspection));
  vi.stubGlobal("fetch", fetch);
  render(<TargetsPage {...props()} targetSelection={{ id: target.id }} />);
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "unavailable",
    ),
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Read selected target again (GET only)",
    }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  expect(
    fetch.mock.calls.every(
      ([u, i]) => u === "/api/v1/chat/tools/targets" && i.method === "GET",
    ),
  ).toBe(true);
});
it("workspace refresh invalidates proof but cannot overwrite inspected bytes or dirty add draft", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response(inspection))
    .mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetch);
  const p = props();
  const { rerender } = render(<TargetsPage {...p} />);
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add target" }));
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "dirty draft" },
  });
  rerender(
    <TargetsPage
      {...p}
      data={{
        ...p.data,
        targets: [{ ...target, address: "stale-workspace.test" }],
      }}
    />,
  );
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "stale",
  );
  expect(screen.getByTestId(`target-row-${target.id}`)).toHaveTextContent(
    target.address,
  );
  expect(screen.getByTestId(`target-row-${target.id}`)).not.toHaveTextContent(
    "stale-workspace.test",
  );
  expect(screen.getByLabelText("Name")).toHaveValue("dirty draft");
});
it("late inspection for old selection cannot publish into a new selection", async () => {
  let release!: (r: Response) => void;
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    )
    .mockResolvedValueOnce(
      response({ ...inspection, targets: [{ ...target, id: "other-id" }] }),
    );
  vi.stubGlobal("fetch", fetch);
  const p = props();
  const { rerender } = render(<TargetsPage {...p} />);
  await act(async () => {});
  expect(fetch).toHaveBeenCalledTimes(1);
  rerender(<TargetsPage {...p} targetSelection={{ id: "other-id" }} />);
  await waitFor(() =>
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  await act(async () => release(response(inspection)));
  expect(screen.getByTestId("target-row-other-id")).toHaveAttribute(
    "data-selected",
    "true",
  );
  expect(
    screen.queryByTestId(`target-row-${target.id}`),
  ).not.toBeInTheDocument();
});
