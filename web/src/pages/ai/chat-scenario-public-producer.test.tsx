// Fresh public ASGI producer -> shipped raw codecs/client/hook/render.
// Controlled native provider; neither historical fixture replay nor live-model acceptance.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ToolRecords } from "./ToolRecords";
import { ChatPanel } from "./ChatPanel";
import { parseTurn } from "./chat-wire";
import { parseV4JSON } from "./chat-scenario-wire";
import { chatScenarioClient } from "./chat-scenario-client";

let corpus: string;
beforeAll(() => {
  const source = resolve("..");
  const owned = mkdtempSync(resolve(tmpdir(), "scenario-http-"));
  for (const name of ["home", "tmp", "cache"]) mkdirSync(resolve(owned, name));
  const output = resolve(owned, "producer");
  execFileSync(
    process.env.DDOSPECTOR_PYTHON ?? resolve(source, ".venv/bin/python"),
    [resolve(source, "tests/chat/chat_scenario_capture.py"), "--out", output],
    {
      cwd: source,
      timeout: 30_000,
      env: {
        PATH: "/usr/bin:/bin",
        HOME: resolve(owned, "home"),
        TMPDIR: resolve(owned, "tmp"),
        XDG_CACHE_HOME: resolve(owned, "cache"),
        PYTHONPATH: ["src", "tests/api", "tests/chat"].map((p) => resolve(source, p)).join(":"),
        PYTHONNOUSERSITE: "1",
        PYTHONDONTWRITEBYTECODE: "1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1",
        UV_OFFLINE: "1",
        PIP_NO_INDEX: "1",
        HF_HUB_OFFLINE: "1",
        TRANSFORMERS_OFFLINE: "1",
      },
    },
  );
  const receipt = JSON.parse(readFileSync(resolve(output, "producer.json"), "utf8"));
  expect(receipt.raw_exit).toBe(0);
  expect(receipt.denied).toEqual([]);
  corpus = resolve(output, "corpus");
}, 40_000);
function wire(operation: string, name: string) {
  const dir = resolve(corpus, `public-${operation}`);
  const manifest = JSON.parse(readFileSync(resolve(dir, "manifest.json"), "utf8"));
  for (const [name, hash] of Object.entries(manifest.source_sha256)) {
    const raw = readFileSync(resolve("..", name));
    expect(createHash("sha256").update(raw).digest("hex")).toBe(hash);
  }
  const entry = manifest.bodies[name];
  const raw = readFileSync(resolve(dir, entry.path));
  expect(raw.length).toBe(entry.size);
  expect(createHash("sha256").update(raw).digest("hex")).toBe(entry.sha256);
  return raw.toString("utf8");
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
for (const operation of ["scenario_create", "scenario_append"] as const) {
  it.each(["en", "ko"] as const)(`${operation}: fresh proposal -> separate receipt -> Saved -> history (%s)`, async (locale) => {
    const turn = parseTurn(JSON.parse(wire(operation, "turn")));
    const grant = await parseV4JSON("GrantV4", wire(operation, "grant"));
    const proposal = await parseV4JSON("TranscriptV4", wire(operation, "proposal"));
    const saved = await parseV4JSON("TranscriptV4", wire(operation, "saved"));
    const state = await parseV4JSON("ScenarioStateInspection", wire(operation, "state-before"));
    const runtime = await parseV4JSON("RuntimeV4", wire(operation, "runtime"));
    const decision = await parseV4JSON("Decision", wire(operation, "decision"));
    const call = proposal.calls.at(-1);
    const result = saved.calls.at(-1)?.result;
    if (!call?.proposal || !result || !["scenario_created", "scenario_appended"].includes(result.kind) || !("after_scenario_revision" in result))
      throw new Error("Fresh producer omitted a required write witness");
    expect(runtime.tools).toContain(operation);
    expect(call.grant_id).toBe(grant.id);
    const origin = Date.parse(turn.created_at);
    const clock = performance.now();
    vi.spyOn(Date, "now").mockImplementation(() => origin + performance.now() - clock);
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      decision.request_id as ReturnType<typeof crypto.randomUUID>,
    );
    let current = "proposal";
    const fetcher = vi.fn(async (url: string) => new Response(
      wire(operation, url.endsWith("/decision") ? "decision" : url.includes("/scenarios/") ? "history" : current),
      { headers: { "content-type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetcher);
    const view = vi.fn();
    render(<ToolRecords turn={turn} locale={locale} enabled viewEpoch={0} canWrite
      scenarioState={state} draftRevision={call.proposal.expected_draft_revision}
      onScenarioSaved={view} />);
    fireEvent.click(await screen.findByTestId(`chat-tool-approve-${call.id}`));
    await waitFor(() => expect(screen.getByText(locale === "en"
      ? "Acknowledged — authority only, not proof of saving."
      : "접수 확인 — 승인 권한만 확인되었으며 저장 증거가 아닙니다.")).toBeInTheDocument());
    expect(screen.queryByTestId(`chat-tool-view-saved-${call.id}`)).toBeNull();
    expect(view).not.toHaveBeenCalled();
    current = "saved";
    fireEvent.click(screen.getByTestId(`chat-tools-refresh-${turn.id}`));
    fireEvent.click(await screen.findByTestId(`chat-tool-view-saved-${call.id}`));
    expect(view).toHaveBeenCalledWith({ scenario: result.scenario, after_scenario_revision: result.after_scenario_revision });
    const history = await chatScenarioClient.history(result.scenario.id);
    expect(history.versions).toContainEqual(result.scenario);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/decision"))).toHaveLength(1);
  });
}
it("fresh public reconciliation never upgrades uncertainty into a save receipt", async () => {
  const uncertain = await parseV4JSON("TranscriptV4", wire("reconcile", "uncertain"));
  const receipt = await parseV4JSON("ReconcileReceiptV4", wire("reconcile", "reconcile"));
  expect(uncertain.calls.at(-1)?.status).toBe("uncertain");
  expect(uncertain.calls.at(-1)?.result).toBeNull();
  expect(receipt.prior_outcomes).toBe("remain_uncertain");
  expect(receipt.scenario_recovery).toBe("not_performed");
});

it("requires explicit availability reading before selecting the scenario scope", async () => {
  const paths: Record<string, string> = {
    "/api/v1/chat/runtime": "chat-runtime",
    "/api/v1/chat/sessions": "sessions",
    "/api/v1/chat/tools/runtime": "runtime",
    "/api/v1/chat/tools/fence": "fence",
    "/api/v1/chat/tools/scenarios/state": "state-before",
  };
  const fetcher = vi.fn(async (url: string) => {
    if (!paths[url]) throw new Error("Unexpected request: " + url);
    return new Response(wire("scenario_create", paths[url]), {
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ChatPanel locale="en" mutationsEnabled />);
  await waitFor(() => expect(screen.getByTestId("chat-new-session")).toBeEnabled());
  const scope = screen.getByTestId("chat-tool-scope");
  expect(screen.getByRole("option", { name: "Scenario definition" })).toBeDisabled();
  fireEvent.change(scope, { target: { value: "scenario_write_v4" } });
  expect(scope).toHaveValue("agent_v1");
  expect(screen.queryByRole("combobox", { name: "Scenario operation" })).toBeNull();
  expect(fetcher.mock.calls.some(([url]) => url === "/api/v1/chat/tools/runtime")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Read tool availability / fence" }));
  await waitFor(() => expect(screen.getByRole("option", { name: "Scenario definition" })).toBeEnabled());
  expect(fetcher.mock.calls.filter(([url]) => url.startsWith("/api/v1/chat/tools/"))
    .map(([url]) => url)).toEqual([
      "/api/v1/chat/tools/runtime", "/api/v1/chat/tools/fence", "/api/v1/chat/tools/scenarios/state",
    ]);
  fireEvent.change(scope, { target: { value: "scenario_write_v4" } });
  expect(scope).toHaveValue("scenario_write_v4");
  expect(screen.getByRole("combobox", { name: "Scenario operation" })).toBeVisible();
  expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
});
