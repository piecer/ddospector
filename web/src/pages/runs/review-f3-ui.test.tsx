import { afterEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RunsPage } from "../operations/RunsPage";
import { runsController } from "./controller";
import { workspaceFixture } from "../../test/fixtures";
import { receiptFixture } from "./testFixtures";

afterEach(() => { runsController().leave(); vi.restoreAllMocks(); });

it.each([
  ["en", "recover"], ["ko", "recover"], ["en", "replay"], ["ko", "replay"],
] as const)("F3 %s submitted-run link selects verified B after lost ACK and %s", async (locale, recovery) => {
  const { d } = await receiptFixture();
  const record = d.snapshot.scenario;
  let a = d, b = d, posts = 0;
  const submittedBodies: string[] = [];
  const fetched = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => {
    const path = String(url);
    const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
    if (path.startsWith("/api/v1/scenarios?")) return reply({ revision: 1, total: 1, offset: 0, limit: 20, items: [record], execution_enabled: false });
    if (path === "/api/v1/scenarios/" + record.id) return reply({ revision: 1, scenario_id: record.id, versions: [record], execution_enabled: false });
    if (path.startsWith("/api/v1/offline-runs?")) return reply({ schema_version: 1, after: 0, through: 0, limit: 20, total: 0, items: [], next_after: null });
    if (path === "/api/v1/offline-runs" && options?.method === "POST") {
      posts++;
      submittedBodies.push(options.body as string);
      const request = JSON.parse(options.body as string);
      if (posts === 1) {
        a = { ...d, run: { ...d.run, request_id: request.request_id } };
        return reply(a, 202);
      }
      if (posts === 2) {
        b = { ...d, run: { ...d.run, id: "b0000000-0000-4000-8000-000000000001", request_id: request.request_id, ordinal: 2 } };
        throw Error("lost B acknowledgement");
      }
      return reply(b);
    }
    if (path === "/api/v1/offline-runs/by-request/" + b.run.request_id) return reply(b);
    if (path === "/api/v1/offline-runs/" + a.run.id) return reply(a);
    if (path === "/api/v1/offline-runs/" + b.run.id) return reply(b);
    return reply({ code: "RUN_DB_UNAVAILABLE", message: "Offline run storage is unavailable." }, 503);
  });
  render(<RunsPage locale={locale} data={workspaceFixture()} navigate={vi.fn()} refresh={vi.fn()} />);
  const start = screen.getByRole("button", { name: locale === "en" ? "Start OFFLINE preparation" : "OFFLINE 준비 시작" });
  const scenario = screen.getByRole("combobox", { name: locale === "en" ? "Saved scenario" : "저장된 시나리오" });
  await waitFor(() => expect(scenario).toBeEnabled());
  await userEvent.selectOptions(scenario, record.id);
  await waitFor(() => expect(start).toBeEnabled());
  await userEvent.click(start);
  const linkName = locale === "en" ? "View submitted run" : "제출한 실행 보기";
  await screen.findByRole("button", { name: linkName });
  await waitFor(() => expect(start).toBeEnabled());
  await userEvent.click(start);
  const readName = locale === "en" ? "Retry saved request read" : "저장된 요청 읽기 재시도";
  const replayName = locale === "en" ? "Retry identical saved request" : "동일한 저장 요청 재시도";
  const retry = await screen.findByRole("button", { name: recovery === "recover" ? readName : replayName });
  await waitFor(() => expect(retry).toBeEnabled());
  expect(screen.queryByRole("button", { name: linkName })).not.toBeInTheDocument();
  const heldRequest = runsController().store.receipt!.request;
  expect(heldRequest.request_id).toBe(b.run.request_id);
  await userEvent.click(retry);
  const link = await screen.findByRole("button", { name: linkName });
  expect(runsController().store.receipt).toBeNull();
  await userEvent.click(link);
  await waitFor(() => expect(runsController().view!.detail).not.toBeNull());
  expect.soft(runsController().view!.id).toBe(b.run.id);
  expect.soft(runsController().view!.detail!.run.request_id).toBe(heldRequest.request_id);
  expect.soft(fetched.mock.calls.some(([url]) => url === "/api/v1/offline-runs/" + b.run.id)).toBe(true);
  expect(posts).toBe(recovery === "recover" ? 2 : 3);
  if (recovery === "replay") expect(submittedBodies[2]).toBe(submittedBodies[1]);
});
