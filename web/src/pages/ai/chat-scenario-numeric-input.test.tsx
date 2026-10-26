// Actual UI + accepted U1 parsing; scripted transport, synthetic domain records.
import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "./ChatPanel";
import { toolClient } from "./chat-tool-client";
import { response, runtimeFixture, session } from "./chat-test-fixtures";
import { fence } from "./chat-tool-test-fixtures";
import { label } from "../scenarios/labels";
import type { Target, Locale } from "../../lib/contracts";
const targets: Target[] = ["DUT", "SINK"].map((kind) => ({
  id: kind.toLowerCase(),
  kind: kind as Target["kind"],
  name: kind,
  address: "lab.test",
  status: "draft",
  created_at: "2026-01-01T00:00:00Z",
}));
function setup() {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/tools/runtime"))
      return response({
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
      });
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
          locale: JSON.parse(init!.body as string).locale,
          sequence: 0,
          active_turn_id: null,
        },
        201,
      );
    throw Error(url);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function open(locale: Locale) {
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId("chat-new-session"));
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
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
        name: locale === "en" ? "Scenario definition" : "시나리오 정의",
      }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByTestId("chat-tool-scope"), {
    target: { value: "scenario_write_v4" },
  });
}
it.each(["en", "ko"] as const)(
  "explicit operator controls carry zero/nulls and never prefill from text (%s)",
  async (locale) => {
    const fetcher = setup();
    const granting = vi
      .spyOn(toolClient, "grant")
      .mockRejectedValue(Error("synthetic loss"));
    render(<ChatPanel locale={locale} targets={targets} />);
    await open(locale);
    const user = userEvent.setup();
    await user.type(
      screen.getByTestId("chat-input"),
      "use 999 PPS from this prose",
    );
    expect(
      screen.getByRole("textbox", { name: label(locale, "max_pps") }),
    ).toHaveValue("");
    fireEvent.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() => expect(screen.getByTestId("chat-send")).toBeDisabled());
    expect(
      fetcher.mock.calls.filter(([, i]) => i?.method === "POST"),
    ).toHaveLength(1);
    await user.selectOptions(
      screen.getByRole("combobox", { name: label(locale, "target_id") }),
      "dut",
    );
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    await user.selectOptions(
      screen.getByRole("combobox", { name: label(locale, "sink_id") }),
      "sink",
    );
    for (const key of [
      "dut_version",
      "policy_version",
      "max_pps",
      "max_bps",
      "max_packets",
      "max_bytes",
      "max_connections",
      "duration_seconds",
      "max_legitimate_loss_pct",
      "max_service_latency_ms",
    ] as const) {
      await user.type(
        screen.getByRole("textbox", { name: label(locale, key) }),
        key === "max_legitimate_loss_pct" ? "0" : "1",
      );
    }
    fireEvent.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() => expect(granting).toHaveBeenCalledTimes(1));
    expect(granting.mock.calls[0][4]).toMatchObject({
      requestedAuthority: "scenario_write_v4",
      request: {
        intent: {
          operation: "scenario_create",
          expected_scenario_revision: 0,
          expected_draft_revision: fence.current_draft_revision,
          base: null,
          input_source: { source: "operator" },
        },
      },
      resolved_inputs: {
        target_id: "dut",
        sink_id: "sink",
        pcap_asset: null,
        traffic_budget: { max_pps: 1 },
        stop_conditions: {
          max_legitimate_loss_pct: 0,
          max_cpu_pct: null,
          max_memory_pct: null,
          max_sessions: null,
          management_loss: true,
        },
      },
    });
    expect(
      screen.getByRole("textbox", { name: label(locale, "max_pps") }),
    ).toBeDisabled();
  },
);

import { recordFixture } from "../scenarios/testRecords";
it("explicit old source is independent from latest append base; offered records are not applied", async () => {
  const fetcher = setup(),
    base = fetcher.getMockImplementation()!;
  const first = await recordFixture(1, {
    id: "legacy-scenario",
    definition: (await recordFixture()).definition,
  });
  const latest = await recordFixture(2, {
    id: first.id,
    definition: first.definition,
  });
  fetcher.mockImplementation(async (u, i) =>
    u.includes("/api/v1/scenarios")
      ? response(
          u.includes("?")
            ? {
                revision: 2,
                total: 1,
                offset: 0,
                limit: 50,
                items: [latest],
                execution_enabled: false,
              }
            : {
                revision: 2,
                scenario_id: first.id,
                versions: [first, latest],
                execution_enabled: false,
              },
        )
      : u.endsWith("/tools/scenarios/state")
        ? response({
            schema_version: 4,
            scenario_revision: 2,
            registry_write_status: "available",
          })
        : base(u, i),
  );
  const granting = vi
    .spyOn(toolClient, "grant")
    .mockRejectedValue(Error("synthetic loss"));
  render(
    <ChatPanel
      locale="en"
      targets={targets.map((t) => ({ ...t, id: t.id + "-test" }))}
    />,
  );
  await open("en");
  fireEvent.change(
    screen.getByRole("combobox", { name: "Scenario operation" }),
    { target: { value: "scenario_append" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Browse scenario sources / bases" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Read history legacy-scenario" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Use latest as append base" }),
    ).toBeEnabled(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Use latest as append base" }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Source version" }), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Input source" }), {
    target: { value: "scenario_version" },
  });
  expect(screen.getByText(/No version selected/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Offer exact source version" }),
  );
  expect(screen.queryByText("Captured scenario ID")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Use selected version" }));
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "append" },
  });
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
  fireEvent.click(screen.getByTestId("chat-send"));
  await waitFor(() => expect(granting).toHaveBeenCalled());
  expect(granting.mock.calls[0][4]).toMatchObject({
    request: {
      intent: {
        operation: "scenario_append",
        base: { id: first.id, version: 2, digest: latest.digest },
        input_source: {
          source: "scenario_version",
          reference: { id: first.id, version: 1, digest: first.digest },
        },
      },
    },
  });
  expect(
    fetcher.mock.calls
      .filter(([u]) => u.startsWith("/api/v1/scenarios"))
      .map(([u]) => u),
  ).toEqual([
    "/api/v1/scenarios?offset=0&limit=50",
    "/api/v1/scenarios/legacy-scenario",
  ]);
});

it("session and scope transitions deliberately reset transient inputs; invalid consent never silently sends CHAT_ONLY", async () => {
  const fetcher = setup();
  render(<ChatPanel locale="en" targets={targets} />);
  await open("en");
  fireEvent.change(screen.getByRole("textbox", { name: "Maximum PPS" }), {
    target: { value: "42" },
  });
  fireEvent.change(screen.getByTestId("chat-tool-scope"), {
    target: { value: "agent_v1" },
  });
  fireEvent.change(screen.getByTestId("chat-tool-scope"), {
    target: { value: "scenario_write_v4" },
  });
  expect(screen.getByRole("textbox", { name: "Maximum PPS" })).toHaveValue("");
  fireEvent.change(screen.getByRole("textbox", { name: "Maximum PPS" }), {
    target: { value: "43" },
  });
  fireEvent.click(screen.getByTestId("chat-new-session"));
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "Maximum PPS" })).toHaveValue(
      "",
    ),
  );
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "clarify" },
  });
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() => expect(screen.getByTestId("chat-send")).toBeDisabled());
  fireEvent.submit(screen.getByRole("form", { name: "Send a message" }));
  expect(
    fetcher.mock.calls.filter(
      ([u]) => u.endsWith("/tool-grants") || u.endsWith("/turns"),
    ),
  ).toHaveLength(0);
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  expect(screen.getByTestId("chat-send")).toBeEnabled();
});

it("all authority-bearing controls are locked when mutations are unavailable while read-only inspection stays available", async () => {
  setup();
  const { rerender } = render(<ChatPanel locale="en" targets={targets} />);
  await open("en");
  rerender(
    <ChatPanel locale="en" targets={targets} mutationsEnabled={false} />,
  );
  expect(screen.getByRole("textbox", { name: "Maximum PPS" })).toBeDisabled();
  expect(
    screen.getByRole("combobox", { name: "Scenario operation" }),
  ).toBeDisabled();
  expect(screen.getByTestId("chat-tools-toggle")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Read tool availability / fence" }),
  ).toBeEnabled();
});

async function completeInputs() {
  fireEvent.change(screen.getByRole("combobox", { name: "DUT target" }), {
    target: { value: "dut" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Sink target" }), {
    target: { value: "sink" },
  });
  for (const key of [
    "dut_version",
    "policy_version",
    "max_pps",
    "max_bps",
    "max_packets",
    "max_bytes",
    "max_connections",
    "duration_seconds",
    "max_legitimate_loss_pct",
    "max_service_latency_ms",
  ] as const)
    fireEvent.change(screen.getByRole("textbox", { name: label("en", key) }), {
      target: { value: key === "max_legitimate_loss_pct" ? "0" : "1" },
    });
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "exact original" },
  });
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
}
it("rechecks current target kinds in the send handler immediately before constructing a grant", async () => {
  setup();
  const currentTargets = structuredClone(targets);
  const granting = vi
    .spyOn(toolClient, "grant")
    .mockRejectedValue(Error("lost"));
  render(<ChatPanel locale="en" targets={currentTargets} />);
  await open("en");
  await completeInputs();
  currentTargets[0].kind = "SINK"; // external mutation before a React render
  fireEvent.click(screen.getByTestId("chat-send"));
  await new Promise((r) => setTimeout(r, 20));
  expect(granting).not.toHaveBeenCalled();
});
it.each([
  "text",
  "targets",
  "context",
  "operation",
  "reset",
  "copy-mode",
  "numeric",
] as const)(
  "authority-bearing %s change clears unused consent",
  async (kind) => {
    setup();
    const { rerender } = render(<ChatPanel locale="en" targets={targets} />);
    await open("en");
    await completeInputs();
    if (kind === "text")
      fireEvent.change(screen.getByTestId("chat-input"), {
        target: { value: "different" },
      });
    if (kind === "targets") rerender(<ChatPanel locale="en" targets={[]} />);
    if (kind === "context")
      rerender(
        <ChatPanel locale="en" targets={targets} contextKey="new settings" />,
      );
    if (kind === "operation")
      fireEvent.change(
        screen.getByRole("combobox", { name: "Scenario operation" }),
        { target: { value: "scenario_append" } },
      );
    if (kind === "reset")
      fireEvent.click(screen.getByRole("button", { name: "Reset inputs" }));
    if (kind === "copy-mode")
      fireEvent.change(screen.getByRole("combobox", { name: "Input source" }), {
        target: { value: "scenario_version" },
      });
    if (kind === "numeric")
      fireEvent.change(screen.getByRole("textbox", { name: "Maximum PPS" }), {
        target: { value: "2" },
      });
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    expect(screen.getByText("CHAT_ONLY")).toBeInTheDocument();
  },
);

import { grant } from "./chat-tool-test-fixtures";
it("unused context changes do not replace or discard a recovered captured grant", async () => {
  setup();
  const granting = vi
    .spyOn(toolClient, "grant")
    .mockRejectedValue(Error("lost"));
  vi.spyOn(toolClient, "recoverGrant").mockResolvedValue(grant as never);
  const submitting = vi
    .spyOn(toolClient, "submit")
    .mockRejectedValue(Error("lost send"));
  const { rerender } = render(<ChatPanel locale="en" targets={targets} />);
  await open("en");
  await completeInputs();
  fireEvent.click(screen.getByTestId("chat-send"));
  await waitFor(() => expect(granting).toHaveBeenCalled());
  const captured = granting.mock.calls[0][4];
  rerender(<ChatPanel locale="en" targets={[]} contextKey="changed" />);
  fireEvent.click(
    screen.getByRole("button", { name: "Read uncertain submission" }),
  );
  const proceed = await screen.findByTestId("chat-tools-grant-continue");
  await waitFor(() => expect(proceed).toBeEnabled());
  fireEvent.click(proceed);
  await waitFor(() => expect(submitting).toHaveBeenCalled());
  expect(submitting.mock.calls[0][4]).toBe(captured);
});
