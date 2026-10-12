import { afterEach, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunsPage } from "../operations/RunsPage";
import { workspaceFixture } from "../../test/fixtures";
import { receiptFixture } from "./testFixtures";
afterEach(() => vi.restoreAllMocks());
it("retains the workspace refresh pending/error/retry contract independently of run reads", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
  let reject!: (e: Error) => void;
  const refresh = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((_ok, fail) => {
          reject = fail;
        }),
    )
    .mockResolvedValue(undefined);
  const { container } = render(
    <RunsPage
      locale="en"
      data={workspaceFixture()}
      navigate={vi.fn()}
      refresh={refresh}
    />,
  );
  const area = within(
    container.querySelector(".operations-refresh") as HTMLElement,
  );
  await userEvent.click(
    area.getByRole("button", { name: "Refresh workspace" }),
  );
  expect(area.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
  expect(area.getByRole("status")).toHaveTextContent(
    "Loading the latest workspace snapshot…",
  );
  await act(async () => reject(new Error("offline")));
  expect(area.getByRole("alert")).toHaveTextContent(
    "Could not refresh. Displayed data may be stale. Retry when the local API is available.",
  );
  await userEvent.click(area.getByRole("button", { name: "Retry refresh" }));
  await waitFor(() =>
    expect(area.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(area.getByRole("status")).toHaveTextContent("Workspace refreshed.");
  expect(refresh).toHaveBeenCalledTimes(2);
});
it.each(["en", "ko"] as const)(
  "real routed Runs selects saved versions and starts OFFLINE only (%s)",
  async (locale) => {
    const { d } = await receiptFixture();
    const record = d.snapshot.scenario;
    let acknowledged = d;
    const fetched = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url, options) => {
        const path = String(url);
        if (path.startsWith("/api/v1/scenarios?"))
          return new Response(
            JSON.stringify({
              revision: 1,
              total: 1,
              offset: 0,
              limit: 20,
              items: [record],
              execution_enabled: false,
            }),
          );
        if (path === "/api/v1/scenarios/" + record.id)
          return new Response(
            JSON.stringify({
              revision: 1,
              scenario_id: record.id,
              versions: [record],
              execution_enabled: false,
            }),
          );
        if (path.startsWith("/api/v1/offline-runs?"))
          return new Response(
            JSON.stringify({
              schema_version: 1,
              after: 0,
              through: 0,
              limit: 20,
              total: 0,
              items: [],
              next_after: null,
            }),
          );
        if (path === "/api/v1/offline-runs" && options?.method === "POST") {
          acknowledged = {
            ...d,
            run: {
              ...d.run,
              request_id: JSON.parse(options.body as string).request_id,
            },
          };
          return new Response(JSON.stringify(acknowledged), { status: 202 });
        }
        if (path === "/api/v1/offline-runs/" + d.run.id)
          return new Response(JSON.stringify(acknowledged));
        return new Response(
          JSON.stringify({
            code: "RUN_DB_UNAVAILABLE",
            message: "Offline run storage is unavailable.",
          }),
          { status: 503 },
        );
      });
    render(
      <RunsPage
        locale={locale}
        data={workspaceFixture()}
        navigate={vi.fn()}
        refresh={vi.fn()}
      />,
    );
    const start = await screen.findByRole("button", {
      name: locale === "en" ? "Start OFFLINE preparation" : "OFFLINE 준비 시작",
    });
    expect(start).toBeDisabled();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", {
          name: locale === "en" ? "Saved scenario" : "저장된 시나리오",
        }),
      ).toBeEnabled(),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", {
        name: locale === "en" ? "Saved scenario" : "저장된 시나리오",
      }),
      record.id,
    );
    await waitFor(() => expect(start).toBeEnabled());
    expect(
      screen.getByRole("button", {
        name: locale === "en" ? "Start run" : "실행 시작",
      }),
    ).toBeDisabled();
    expect(screen.getByText("NOT_EVALUATED")).toBeVisible();
    await userEvent.click(start);
    await waitFor(() =>
      expect(
        fetched.mock.calls.some(
          ([url, opts]) =>
            url === "/api/v1/offline-runs" && opts?.method === "POST",
        ),
      ).toBe(true),
    );
    const [, options] = fetched.mock.calls.find(
      ([url, opts]) =>
        url === "/api/v1/offline-runs" && opts?.method === "POST",
    )!;
    expect(JSON.parse(options!.body as string)).toMatchObject({
      mode: "OFFLINE",
      scenario_id: record.id,
      scenario_digest: record.digest,
      scenario_version: 1,
    });
    await screen.findByRole("button", {
      name: locale === "en" ? "View submitted run" : "제출한 실행 보기",
    });
    expect(
      fetched.mock.calls.filter(
        ([url, opts]) =>
          url === "/api/v1/offline-runs" && opts?.method === "POST",
      ),
    ).toHaveLength(1);
  },
);
