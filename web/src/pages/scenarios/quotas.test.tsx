import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProfilesPage } from "../lab/profiles";
import { workspaceFixture } from "../../test/fixtures";
import { recordFixture } from "./testRecords";
const response = (value: unknown) => new Response(JSON.stringify(value));
afterEach(() => vi.unstubAllGlobals());
it("disables create at the identity quota and preserves access to the complete last history", async () => {
  const records = await Promise.all(
    Array.from({ length: 50 }, (_, i) =>
      recordFixture(1, {
        id: `${String(i).padStart(8, "0")}-1111-4111-8111-111111111111`,
      }),
    ),
  );
  const versions = await Promise.all(
    Array.from({ length: 10 }, (_, i) =>
      recordFixture(i + 1, { id: records[0].id }),
    ),
  );
  records[0] = versions[9];
  const fetcher = vi.fn(async (url: string) =>
    response(
      url.includes("?")
        ? {
            revision: 109,
            total: 100,
            offset: 0,
            limit: 50,
            items: records,
            execution_enabled: false,
          }
        : {
            revision: 109,
            scenario_id: records[0].id,
            versions,
            execution_enabled: false,
          },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const data = workspaceFixture();
  data.targets = [records[0].target_snapshot, records[0].sink_snapshot];
  render(
    <ProfilesPage
      data={data}
      locale="en"
      navigate={vi.fn()}
      refresh={vi.fn()}
    />,
  );
  expect(
    await screen.findByText(
      "The limit of 100 scenario identities has been reached.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New scenario" })).toBeDisabled();
  fireEvent.click(
    screen.getAllByRole("button", { name: "Scenario history" })[0],
  );
  const select = await screen.findByLabelText("Revision");
  expect(select.querySelectorAll("option")).toHaveLength(10);
  expect(screen.getByRole("button", { name: "Edit scenario" })).toBeDisabled();
  fireEvent.change(select, { target: { value: "1" } });
  expect(screen.getByText(versions[0].digest)).toBeInTheDocument();
});
it("does not reopen a closed history when its ignored-abort response arrives late", async () => {
  const record = await recordFixture();
  let finish!: (v: Response) => void;
  const fetcher = vi.fn((url: string) =>
    url.includes("?")
      ? Promise.resolve(
          response({
            revision: 1,
            total: 1,
            offset: 0,
            limit: 50,
            items: [record],
            execution_enabled: false,
          }),
        )
      : new Promise<Response>((resolve) => {
          finish = resolve;
        }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(
    <ProfilesPage
      data={workspaceFixture()}
      locale="en"
      navigate={vi.fn()}
      refresh={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Scenario history" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  const focus = screen.getByRole("button", { name: "Reload scenarios" });
  focus.focus();
  finish(
    response({
      revision: 1,
      scenario_id: record.id,
      versions: [record],
      execution_enabled: false,
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(focus).toHaveFocus();
});
