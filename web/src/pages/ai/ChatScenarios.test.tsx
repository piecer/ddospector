// Scripted fetch controls using real clients/components; no backend execution.
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";
import { response, runtimeFixture, session } from "./chat-test-fixtures";
import { fence } from "./chat-tool-test-fixtures";
const runtime = {
  schema_version: 4,
  mode: "operator_approved_settings",
  supported: true,
  reason: null,
  tools: [
    "configuration_read",
    "agent_profile_update",
    "target_create",
    "skill_create",
    "scenario_create",
    "scenario_append",
  ],
  max_calls: 3,
  max_writes: 1,
  requires_write_approval: true,
};
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function setup() {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/tools/runtime")) return response(runtime);
    if (url.endsWith("/tools/fence")) return response(fence);
    if (url.endsWith("/tools/scenarios/state"))
      return response({
        schema_version: 4,
        scenario_revision: 0,
        registry_write_status: "available",
      });
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions"))
      return response(
        {
          ...session,
          request_id: JSON.parse(init!.body as string).request_id,
          sequence: 0,
          active_turn_id: null,
        },
        201,
      );
    throw Error("Unexpected " + url);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
it.each(["en", "ko"] as const)(
  "runtime4 keeps Target/Skill and offers explicit scenario inputs (%s)",
  async (locale) => {
    const fetcher = setup();
    render(<ChatPanel locale={locale} />);
    await waitFor(() =>
      expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name:
          locale === "en"
            ? "Read tool availability / fence"
            : "도구 사용 가능 여부 / 차단 읽기",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("option", {
          name: locale === "en" ? "Create target" : "대상 생성",
        }),
      ).toBeEnabled(),
    );
    expect(
      screen.getByRole("option", {
        name: locale === "en" ? "Create Skill" : "스킬 생성",
      }),
    ).toBeEnabled();
    const option = screen.getByRole("option", {
      name: locale === "en" ? "Scenario definition" : "시나리오 정의",
    });
    expect(option).toBeEnabled();
    fireEvent.change(screen.getByTestId("chat-tool-scope"), {
      target: { value: "scenario_write_v4" },
    });
    expect(
      screen.getByRole("group", {
        name: locale === "en" ? "Scenario inputs" : "시나리오 입력",
      }),
    ).toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([u]) => u.includes("/tools/")).map(([u]) => u),
    ).toEqual([
      "/api/v1/chat/tools/runtime",
      "/api/v1/chat/tools/fence",
      "/api/v1/chat/tools/scenarios/state",
    ]);
  },
);

import { useChat } from "./useChat";
import { toolClient } from "./chat-tool-client";
import { grant } from "./chat-tool-test-fixtures";
import { turn } from "./chat-test-fixtures";
import { definitionFixture } from "../scenarios/testFixtures";
import { scenarioInputDraftFromVersion } from "./scenario-grant-inputs";
import { recordFixture } from "../scenarios/testRecords";
it("Pending captures complete authority before await and retains it through GET recovery and Continue", async () => {
  setup();
  const record = await recordFixture(1, { definition: definitionFixture() });
  const inputs = scenarioInputDraftFromVersion(record).selection!.inputs;
  const spec = {
    intent: {
      operation: "scenario_create" as const,
      expected_scenario_revision: 0,
      expected_draft_revision: 0,
      base: null,
      input_source: { source: "operator" as const, inputs },
    },
    resolved_inputs: inputs,
  };
  const original = structuredClone(spec);
  const granting = vi
    .spyOn(toolClient, "grant")
    .mockRejectedValue(Error("lost ACK"));
  const recovery = vi
    .spyOn(toolClient, "recoverGrant")
    .mockResolvedValue(grant as never);
  const submit = vi
    .spyOn(toolClient, "submit")
    .mockResolvedValue({
      ...turn,
      status: "succeeded",
      finished_at: turn.created_at,
    } as never);
  const { result, rerender } = renderHook(
    ({ value }) => useChat("en", true, true, "scenario_write_v4", value),
    { initialProps: { value: spec } },
  );
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.start());
  act(() => result.current.setInput("operator request"));
  await act(() => result.current.send(true));
  expect(granting).toHaveBeenCalledTimes(1);
  const captured = granting.mock.calls[0][4];
  expect(captured).toEqual({
    requestedAuthority: "scenario_write_v4",
    settings_revision: session.settings_revision,
    profile_id: session.profile_id,
    resolved_inputs: original.resolved_inputs,
    request: {
      schema_version: 4,
      scope: "scenario_write",
      request_id: granting.mock.calls[0][1],
      session_id: session.id,
      turn_request_id: granting.mock.calls[0][2],
      expected_sequence: 0,
      text: "operator request",
      intent: original.intent,
    },
  });
  spec.resolved_inputs.traffic_budget.max_pps = 999;
  rerender({ value: spec });
  act(() => result.current.setInput("different text"));
  await act(() => result.current.recoverSubmission());
  expect(recovery.mock.calls[0][4]).toBe(captured);
  await act(() => result.current.continueGrant());
  expect(submit.mock.calls[0][4]).toBe(captured);
  expect(captured).toMatchObject({
    request: { intent: original.intent },
    resolved_inputs: original.resolved_inputs,
  });
});

import { useToolAuthority } from "./useToolAuthority";
import { readFileSync } from "node:fs";
import { parseTranscriptV4 } from "./chat-scenario-wire";
const captures =
  "/home/piecer/dev/src/ddospector/.hermes/artifacts/chat-agent/chat02b3/implementation/integration/p-client/review/producer-bytes/";
it("uncertainty inspection uses two fences and acknowledgement never clears scenario quarantine", async () => {
  const v = (n: string) =>
    JSON.parse(readFileSync(captures + n + ".bin", "utf8"));
  const wire = v("uncertain-transcript"),
    transcript = await parseTranscriptV4(wire, wire.turn_id);
  let cleared = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/runtime")) return response(v("runtime"));
    if (url.endsWith("/fence"))
      return response(v(cleared ? "fence-cleared" : "fence-uncertain"));
    if (url.endsWith("/state")) return response(v("state-quarantined"));
    if (url.includes("/api/v1/scenarios?"))
      return response(v("quarantined-page"));
    if (url.endsWith("/reconcile")) {
      cleared = true;
      return response(
        {
          ...v("reconcile"),
          request_id: JSON.parse(init!.body as string).request_id,
        },
        201,
      );
    }
    throw Error(url);
  });
  vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() => useToolAuthority(true));
  await act(() => result.current.refresh());
  act(() => result.current.observe(transcript));
  await waitFor(() => expect(result.current.ready).toBe(true));
  fetcher.mockClear();
  await act(() => result.current.inspect());
  expect(fetcher.mock.calls.map(([u]) => u)).toEqual([
    "/api/v1/chat/tools/fence",
    "/api/v1/chat/tools/scenarios/state",
    "/api/v1/scenarios?offset=0&limit=50",
    "/api/v1/chat/tools/scenarios/state",
    "/api/v1/chat/tools/fence",
  ]);
  expect(result.current.canReconcile).toBe(true);
  await act(() => result.current.acknowledge());
  expect(result.current.receipt).toMatchObject({
    schema_version: 4,
    scenario_recovery: "not_performed",
    prior_outcomes: "remain_uncertain",
  });
  expect(result.current.scenarioState?.registry_write_status).toBe(
    "quarantined",
  );
  expect(result.current.canScenarioWrite).toBe(false);
  const sent = JSON.parse(
    fetcher.mock.calls.find(([u]) => u.endsWith("/reconcile"))![1]!
      .body as string,
  );
  expect(sent).toMatchObject({
    schema_version: 4,
    expected_scenario_revision: v("state-quarantined").scenario_revision,
  });
});

import { chatClient } from "./chat-client";
import { parseTurn } from "./chat-wire";
it("cold uncertain UI offers bounded explicit page inspection and never a Saved link", async () => {
  const v = (n: string) =>
    JSON.parse(readFileSync(captures + n + ".bin", "utf8"));
  const wire = v("uncertain-transcript"),
    t = parseTurn({
      ...v("uncertain-turn"),
      status: "cancelled",
      error_code: "CHAT_CANCELLED",
      revision: 2,
      finished_at: wire.calls.at(-1).finished_at,
    });
  const s = {
    ...session,
    id: t.session_id,
    sequence: t.sequence,
    active_turn_id: null,
  };
  vi.spyOn(chatClient, "runtime").mockResolvedValue(runtimeFixture as never);
  vi.spyOn(chatClient, "sessions").mockResolvedValue([s] as never);
  vi.spyOn(chatClient, "history").mockResolvedValue({
    schema_version: 1,
    session: s,
    turns: [t],
    next_before_sequence: null,
  } as never);
  const page = v("quarantined-page");
  const fetcher = vi.fn(async (u: string) =>
    response(
      u.endsWith("/tools")
        ? wire
        : u.endsWith("/runtime")
          ? v("runtime")
          : u.endsWith("/fence")
            ? v("fence-uncertain")
            : u.endsWith("/state")
              ? v("state-quarantined")
              : page,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<ChatPanel locale="en" targets={[]} />);
  fireEvent.click(await screen.findByTestId(`chat-session-${s.id}`));
  await screen.findByText(
    "Execution remains uncertain. Matching current values do not prove this operation saved.",
  );
  fireEvent.click(screen.getByTestId("chat-tools-reconcile-review"));
  expect(
    await screen.findByRole("button", {
      name: "Inspect scenario " + page.items[0].id,
    }),
  ).toBeEnabled();
  expect(screen.queryByText("View saved scenario version")).toBeNull();
  expect(
    screen.getByText(/Chat acknowledgement does not recover scenario storage/),
  ).toBeInTheDocument();
  expect(
    fetcher.mock.calls.filter(([u]) => u.startsWith("/api/v1/scenarios/")),
  ).toHaveLength(0);
});

it.each(["en", "ko"] as const)(
  "scenario state CHAT_BUSY uses one retry owner, three attempts spaced at least 500ms (%s)",
  async (locale) => {
    vi.useFakeTimers();
    try {
      const times: number[] = [];
      const base = setup();
      const normal = base.getMockImplementation()!;
      base.mockImplementation(async (u, i) => {
        if (u.endsWith("/tools/scenarios/state")) {
          times.push(Date.now());
          return response({ code: "CHAT_BUSY", message: "Chat is busy." }, 429);
        }
        return normal(u, i);
      });
      const view = render(<ChatPanel locale={locale} />);
      await act(async () => {});
      fireEvent.click(
        screen.getByRole("button", {
          name:
            locale === "en"
              ? "Read tool availability / fence"
              : "도구 사용 가능 여부 / 차단 읽기",
        }),
      );
      await act(async () => {});
      await act(async () => vi.advanceTimersByTimeAsync(499));
      expect(times).toHaveLength(1);
      await act(async () => vi.advanceTimersByTimeAsync(1));
      expect(times).toHaveLength(2);
      await act(async () => vi.advanceTimersByTimeAsync(500));
      expect(times).toHaveLength(3);
      await act(async () => vi.advanceTimersByTimeAsync(10000));
      expect(times).toHaveLength(3);
      expect(times[1] - times[0]).toBeGreaterThanOrEqual(500);
      expect(times[2] - times[1]).toBeGreaterThanOrEqual(500);
      expect(
        screen.getByRole("option", {
          name: locale === "en" ? "Scenario definition" : "시나리오 정의",
        }),
      ).toBeDisabled();
      view.unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  },
);

// UA-01: user-visible transitions retire unused authority, not just hide it.
import userEvent from "@testing-library/user-event";
import { AgentPage } from "./AgentPage";
import { workspaceFixture } from "../../test/fixtures";
import { label } from "../scenarios/labels";
import type { Locale, Target } from "../../lib/contracts";
async function consentReady(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  await user.click(screen.getByTestId("chat-new-session"));
  await user.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-input")).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "Read tool availability / fence" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: "Scenario definition" }),
    ).toBeEnabled(),
  );
  await user.selectOptions(
    screen.getByTestId("chat-tool-scope"),
    "scenario_write_v4",
  );
  const definition = definitionFixture();
  await user.selectOptions(
    screen.getByRole("combobox", { name: label("en", "target_id") }),
    definition.target_id,
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: label("en", "sink_id") }),
    definition.sink_id,
  );
  for (const key of [
    "max_pps",
    "max_bps",
    "max_packets",
    "max_bytes",
    "max_connections",
    "duration_seconds",
  ] as const) {
    const value = definition.traffic_budget[key];
    if (value !== null)
      await user.type(
        screen.getByRole("textbox", { name: label("en", key) }),
        String(value),
      );
  }
  for (const key of [
    "max_legitimate_loss_pct",
    "max_service_latency_ms",
  ] as const) {
    const value = definition.stop_conditions[key];
    if (value !== null)
      await user.type(
        screen.getByRole("textbox", { name: label("en", key) }),
        String(value),
      );
  }
  for (const key of ["dut_version", "policy_version"] as const)
    await user.type(
      screen.getByRole("textbox", { name: label("en", key) }),
      definition[key],
    );
  await user.type(screen.getByTestId("chat-input"), "original");
  await user.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-send")).toBeEnabled(),
  );
  expect(screen.getByTestId("chat-tools-toggle")).toBeChecked();
}
it.each(["text", "context", "targets", "workspace"] as const)(
  "UA-01 %s A-B-A cannot resurrect consent; only explicit reconsent can",
  async (kind) => {
    const fetcher = setup(),
      user = userEvent.setup();
    const record = await recordFixture();
    const targets: Target[] = [
      record.target_snapshot,
      record.sink_snapshot,
    ];
    const data = { ...workspaceFixture(), targets };
    const navigate = vi.fn(),
      refresh = vi.fn(async () => {});
    const view = (contextKey = "A", ts = targets, locale: Locale = "en") =>
      kind === "workspace" ? (
        <AgentPage
          data={{ ...data, targets: ts }}
          locale={locale}
          navigate={navigate}
          refresh={refresh}
        />
      ) : (
        <ChatPanel locale={locale} targets={ts} contextKey={contextKey} />
      );
    const v = render(view());
    await consentReady(user);
    // Ordinary rerenders and presentation-only locale changes retain consent.
    v.rerender(view("A", structuredClone(targets), "ko"));
    expect(screen.getByTestId("chat-tools-toggle")).toBeChecked();
    v.rerender(view());
    expect(screen.getByTestId("chat-tools-toggle")).toBeChecked();
    if (kind === "text")
      await user.type(screen.getByTestId("chat-input"), "x");
    else
      v.rerender(
        kind === "context"
          ? view("B")
          : view("A", [{ ...targets[0], name: "changed" }, targets[1]]),
      );
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    if (kind === "text")
      await user.type(screen.getByTestId("chat-input"), "{Backspace}");
    else v.rerender(view());
    expect(screen.getByTestId("chat-input")).toHaveValue("original");
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          init?.method === "POST" && !url.endsWith("/sessions"),
      ),
    ).toHaveLength(0);
    await user.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("chat-send")).toBeEnabled(),
    );
    expect(screen.getByTestId("chat-tools-toggle")).toBeChecked();
  },
);

it.each([
  "settings",
  "profile",
  "draft-revision",
  "scenario-revision",
  "generation",
] as const)(
  "UA-01 observed %s metadata retires unused consent without sending",
  async (kind) => {
    const fetcher = setup(),
      user = userEvent.setup();
    const normal = fetcher.getMockImplementation()!;
    const record = await recordFixture();
    render(
      <ChatPanel
        locale="en"
        targets={[record.target_snapshot, record.sink_snapshot]}
      />,
    );
    await consentReady(user);
    fetcher.mockImplementation(async (url, init) => {
      if (kind === "settings" && url === "/api/v1/chat/runtime")
        return response({ ...runtimeFixture, settings_revision: 1 });
      if (kind === "profile" && url === "/api/v1/chat/runtime")
        return response({
          ...runtimeFixture,
          profile: {
            ...runtimeFixture.profile,
            id: "other-profile",
            model: "different:model",
          },
        });
      if (kind === "draft-revision" && url.endsWith("/tools/fence"))
        return response({
          ...fence,
          current_draft_revision: fence.current_draft_revision! + 1,
        });
      if (kind === "generation" && url.endsWith("/tools/fence"))
        return response({ ...fence, generation: fence.generation + 1 });
      if (
        kind === "scenario-revision" &&
        url.endsWith("/tools/scenarios/state")
      )
        return response({
          schema_version: 4,
          scenario_revision: 1,
          registry_write_status: "available",
        });
      return normal(url, init);
    });
    const refresh = () =>
      user.click(
        screen.getByRole("button", {
          name:
            kind === "settings" || kind === "profile"
              ? "Refresh chat metadata"
              : "Read tool availability / fence",
        }),
      );
    await refresh();
    await waitFor(() =>
      expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked(),
    );
    await refresh();
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          init?.method === "POST" && !url.endsWith("/sessions"),
      ),
    ).toHaveLength(0);
  },
);
it("UA-01 legacy consent keeps its ordinary text/context semantics", async () => {
  setup();
  const user = userEvent.setup();
  const view = render(<ChatPanel locale="en" contextKey="A" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  await user.click(screen.getByTestId("chat-new-session"));
  await user.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-input")).toBeEnabled(),
  );
  await user.type(screen.getByTestId("chat-input"), "legacy");
  await user.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-send")).toBeEnabled(),
  );
  await user.type(screen.getByTestId("chat-input"), " text");
  view.rerender(<ChatPanel locale="ko" contextKey="B" />);
  expect(screen.getByTestId("chat-tools-toggle")).toBeChecked();
});
