// Immutable actual ASGI positive bytes from the accepted P-client review.
// These are replayed in JSDOM, not a new backend or browser acceptance run.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ToolRecords } from "./ToolRecords";
import { parseTurn } from "./chat-wire";
import type { ScenarioExpectation } from "./chat-scenario-types";
const root =
  "/home/piecer/dev/src/ddospector/.hermes/artifacts/chat-agent/chat02b3/implementation/integration/p-client/review/";
const manifest = JSON.parse(
  readFileSync(root + "producer-byte-manifest.json", "utf8"),
);
function bytes(name: string) {
  const entry = manifest.bodies[name];
  const b = readFileSync(root + entry.path);
  expect(createHash("sha256").update(b).digest("hex")).toBe(entry.sha256);
  return b.toString("utf8");
}
function value(name: string) {
  return JSON.parse(bytes(name));
}
function response(name: string) {
  return new Response(bytes(name), {
    headers: { "content-type": "application/json" },
  });
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each(["en", "ko"] as const)(
  "actual create proposal shows full source/snapshots and only durable receipt enables Saved (%s)",
  async (locale) => {
    const t = parseTurn(value("create-turn")),
      proposal = value("create-proposal"),
      saved = value("create-saved"),
      decision = value("create-decision");
    const call = proposal.calls.find(
      (c: { tool: string }) => c.tool === "scenario_create",
    );
    const clock = performance.now(),
      anchor = Date.parse(t.created_at);
    vi.spyOn(Date, "now").mockImplementation(
      () => anchor + performance.now() - clock,
    );
    vi.spyOn(crypto, "randomUUID").mockReturnValue(decision.request_id);
    let current = "create-proposal";
    const fetcher = vi.fn(async (url: string) =>
      url.endsWith("/decision")
        ? response("create-decision")
        : response(current),
    );
    vi.stubGlobal("fetch", fetcher);
    const onSaved = vi.fn<(e: ScenarioExpectation) => void>();
    const { container } = render(
      <ToolRecords
        turn={t}
        locale={locale}
        enabled
        viewEpoch={0}
        canWrite
        scenarioState={value("state-empty")}
        draftRevision={3}
        onScenarioSaved={onSaved}
      />,
    );
    const approve = await screen.findByTestId(`chat-tool-approve-${call.id}`);
    const panel = screen.getByTestId(`chat-tool-proposal-${call.id}`);
    expect(panel.textContent).toContain(call.proposal.inputs_digest);
    expect(panel.textContent).toContain(
      call.proposal.snapshots.target_snapshot.address,
    );
    expect(panel.textContent).toContain("max_cpu_pct");
    expect(panel.textContent).toContain("null");
    expect(container.querySelector("script, img, a")).toBeNull();
    fireEvent.click(approve);
    await waitFor(() =>
      expect(
        screen.getByText(
          locale === "en"
            ? "Acknowledged — authority only, not proof of saving."
            : "접수 확인 — 승인 권한만 확인되었으며 저장 증거가 아닙니다.",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId(`chat-tool-view-saved-${call.id}`)).toBeNull();
    expect(onSaved).not.toHaveBeenCalled();
    current = "create-saved";
    fireEvent.click(screen.getByTestId(`chat-tools-refresh-${t.id}`));
    fireEvent.click(
      await screen.findByTestId(`chat-tool-view-saved-${call.id}`),
    );
    const result = saved.calls.find(
      (c: { tool: string }) => c.tool === "scenario_create",
    ).result;
    expect(onSaved).toHaveBeenCalledWith({
      scenario: result.scenario,
      after_scenario_revision: result.after_scenario_revision,
    });
  },
);
it("cold append success needs no grant cache and survives a cancelled narrative", async () => {
  const wire = value("append-old-source-saved"),
    base = value("append-old-source-turn");
  // Synthetic turn-status derivative; transcript bytes remain literal ASGI.
  const t = parseTurn({
    ...base,
    status: "cancelled",
    revision: 2,
    finished_at: wire.calls.at(-1).finished_at,
    error_code: "CHAT_CANCELLED",
  });
  const fetcher = vi.fn(async () => response("append-old-source-saved"));
  vi.stubGlobal("fetch", fetcher);
  const view = vi.fn();
  render(
    <ToolRecords
      turn={t}
      locale="en"
      enabled
      viewEpoch={0}
      canWrite={false}
      onScenarioSaved={view}
    />,
  );
  const saved = wire.calls.find(
    (c: { tool: string }) => c.tool === "scenario_append",
  );
  fireEvent.click(
    await screen.findByTestId(`chat-tool-view-saved-${saved.id}`),
  );
  expect(view).toHaveBeenCalledWith({
    scenario: saved.result.scenario,
    after_scenario_revision: saved.result.after_scenario_revision,
  });
  expect(fetcher.mock.calls).toHaveLength(1);
});

import { act, renderHook } from "@testing-library/react";
import { useChat } from "./useChat";
import { chatClient } from "./chat-client";
import { toolClient } from "./chat-tool-client";
import { runtimeFixture } from "./chat-test-fixtures";
import type { GrantV4 } from "./chat-scenario-types";
it("actual admission timestamp retains all microseconds in the captured live binding deadline", async () => {
  const context = JSON.parse(
    readFileSync(root + "producer-bytes/create-context.json", "utf8"),
  );
  const g = value("create-grant"),
    t = parseTurn(value("create-turn"));
  vi.spyOn(chatClient, "runtime").mockResolvedValue(runtimeFixture as never);
  vi.spyOn(chatClient, "sessions").mockResolvedValue([]);
  vi.spyOn(chatClient, "start").mockResolvedValue(context.session);
  vi.spyOn(toolClient, "grant").mockResolvedValue(g);
  vi.spyOn(toolClient, "submit").mockResolvedValue(t);
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(Error("no observations")));
  const spec = {
    intent: context.commitment.request.intent,
    resolved_inputs: context.commitment.resolved_inputs,
  };
  const { result } = renderHook(() =>
    useChat("en", true, true, "scenario_write_v4", spec),
  );
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.start());
  act(() => result.current.setInput(context.commitment.request.text));
  await act(() => result.current.send(true));
  expect(result.current.scenarioContexts.get(t.id)).toEqual({
    grant: g,
    deadlineAt: context.deadlineAt,
  });
  g.resolved_inputs.dut_version = "mutated response object";
  expect(
    result.current.scenarioContexts.get(t.id)?.grant.resolved_inputs
      .dut_version,
  ).toBe(context.commitment.resolved_inputs.dut_version);
});
it("live transcript rejects a self-consistent receipt that does not match captured grant", async () => {
  const t = parseTurn(value("create-turn")),
    context = JSON.parse(
      readFileSync(root + "producer-bytes/create-context.json", "utf8"),
    );
  const g: GrantV4 = value("create-grant");
  g.intent.expected_draft_revision++;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response("create-saved")),
  );
  const onRecord = vi.fn(),
    view = vi.fn();
  render(
    <ToolRecords
      turn={t}
      locale="en"
      enabled
      viewEpoch={0}
      canWrite
      onRecord={onRecord}
      onScenarioSaved={view}
      scenarioContext={{ grant: g, deadlineAt: context.deadlineAt }}
    />,
  );
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByText("Saved definition ·", { exact: false })).toBeNull();
  expect(onRecord).not.toHaveBeenCalled();
  expect(view).not.toHaveBeenCalled();
});

import { AgentPage } from "./AgentPage";
import { workspaceFixture } from "../../test/fixtures";
it("actual AgentPage supplies current targets and routes only a validated Saved receipt", async () => {
  const wire = value("create-saved"),
    rawTurn = value("create-turn"),
    context = JSON.parse(
      readFileSync(root + "producer-bytes/create-context.json", "utf8"),
    );
  const t = parseTurn({
    ...rawTurn,
    status: "cancelled",
    error_code: "CHAT_CANCELLED",
    revision: 2,
    finished_at: wire.calls.at(-1).finished_at,
  });
  const s = { ...context.session, sequence: t.sequence, active_turn_id: null };
  vi.spyOn(chatClient, "runtime").mockResolvedValue(runtimeFixture as never);
  vi.spyOn(chatClient, "sessions").mockResolvedValue([s]);
  vi.spyOn(chatClient, "history").mockResolvedValue({
    schema_version: 1,
    session: s,
    turns: [t],
    next_before_sequence: null,
  });
  const fetcher = vi.fn(async (u: string) =>
    u.endsWith("/tools")
      ? response("create-saved")
      : u.endsWith("/runtime")
        ? response("runtime")
        : u.endsWith("/fence")
          ? response("fence-empty")
          : response("state-empty"),
  );
  vi.stubGlobal("fetch", fetcher);
  const record = wire.calls.find(
    (c: { tool: string }) => c.tool === "scenario_create",
  ).result.scenario;
  const data = workspaceFixture();
  data.targets = [record.target_snapshot, record.sink_snapshot];
  const navigate = vi.fn();
  render(
    <AgentPage
      data={data}
      locale="en"
      navigate={navigate}
      refresh={async () => {}}
    />,
  );
  fireEvent.click(await screen.findByTestId(`chat-session-${s.id}`));
  const call = wire.calls.find(
    (c: { tool: string }) => c.tool === "scenario_create",
  );
  fireEvent.click(await screen.findByTestId(`chat-tool-view-saved-${call.id}`));
  expect(navigate).toHaveBeenCalledWith("profiles", {
    id: record.id,
    version: record.version,
    expectation: { scenario: record, after_scenario_revision: 1 },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Read tool availability / fence" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: "Scenario definition" }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByTestId("chat-tool-scope"), {
    target: { value: "scenario_write_v4" },
  });
  expect(
    screen
      .getByRole("combobox", { name: "DUT target" })
      .querySelector(`option[value="${record.target_snapshot.id}"]`)
      ?.textContent,
  ).toBe(record.target_snapshot.name + " · " + record.target_snapshot.id);
});

it.each(["quarantined", "revision"] as const)(
  "scenario approval refuses stale %s observations but keeps Deny and GET available",
  async (kind) => {
    const t = parseTurn(value("create-turn")),
      wire = value("create-proposal"),
      call = wire.calls.find(
        (c: { tool: string }) => c.tool === "scenario_create",
      );
    const clock = performance.now(),
      anchor = Date.parse(t.created_at);
    vi.spyOn(Date, "now").mockImplementation(
      () => anchor + performance.now() - clock,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response("create-proposal")),
    );
    render(
      <ToolRecords
        turn={t}
        locale="en"
        enabled
        viewEpoch={0}
        canWrite
        scenarioState={{
          schema_version: 4,
          scenario_revision: kind === "revision" ? 1 : 0,
          registry_write_status:
            kind === "quarantined" ? "quarantined" : "available",
        }}
        draftRevision={3}
      />,
    );
    expect(
      await screen.findByTestId(`chat-tool-approve-${call.id}`),
    ).toBeDisabled();
    expect(screen.getByTestId(`chat-tool-deny-${call.id}`)).toBeEnabled();
    expect(screen.getByTestId(`chat-tools-refresh-${t.id}`)).toBeEnabled();
  },
);

it.each([
  "foreign-turn",
  "foreign-call",
  "wrong-record",
  "wrong-proposal",
  "uncertain",
] as const)(
  "no callback/navigation from %s transcript evidence",
  async (kind) => {
    const original = value(
        kind === "uncertain" ? "uncertain-turn" : "create-turn",
      ),
      wire = value(
        kind === "uncertain" ? "uncertain-transcript" : "create-saved",
      );
    const t = parseTurn({
      ...original,
      status: "cancelled",
      error_code: "CHAT_CANCELLED",
      revision: 2,
      finished_at: wire.calls.at(-1).finished_at,
    });
    // Deliberately malformed synthetic derivatives, never relabeled ASGI evidence.
    if (kind === "foreign-turn")
      wire.turn_id = "11111111-1111-4111-8111-111111111111";
    if (kind === "foreign-call")
      wire.calls.at(-1).decision.call_id =
        "11111111-1111-4111-8111-111111111111";
    if (kind === "wrong-record")
      wire.calls.at(-1).result.scenario.definition.name = "foreign";
    if (kind === "wrong-proposal")
      wire.calls.at(-1).proposal.expected_draft_revision++;
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify(wire), {
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    const view = vi.fn(),
      record = vi.fn();
    render(
      <ToolRecords
        turn={t}
        locale="en"
        enabled
        viewEpoch={0}
        canWrite
        onScenarioSaved={view}
        onRecord={record}
      />,
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByText("View saved scenario version")).toBeNull();
    expect(view).not.toHaveBeenCalled();
    if (kind !== "uncertain") expect(record).not.toHaveBeenCalled();
  },
);
