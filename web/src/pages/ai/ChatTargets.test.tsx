// Synthetic component controls, not API/model acceptance.
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
import { ToolRecords } from "./ToolRecords";
import { parseTurn } from "./chat-wire";
import { useChat } from "./useChat";
import {
  response,
  runtimeFixture,
  session,
  turn,
  tid,
} from "./chat-test-fixtures";
import {
  grant,
  fence,
  textHash,
  toolRuntime,
  cid,
} from "./chat-tool-test-fixtures";
import {
  targetCall,
  targetSaved,
  targetRuntime,
  targetTranscript,
  target,
} from "./chat-target-test-fixtures";
function asTarget(g: typeof grant) {
  const { proposal_fields: fields, ...rest } = g;
  void fields;
  return {
    ...rest,
    schema_version: 2,
    scope: "target_create",
    read_scope: ["targets", "target"],
    proposal_tools: ["target_create"],
  };
}
afterEach(() => vi.unstubAllGlobals());
function mockChat(runtime = targetRuntime) {
  let current: unknown = { ...targetTranscript, calls: [targetCall] };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const input = init?.body ? JSON.parse(init.body as string) : {};
    if (url.endsWith("/tools/runtime")) return response(runtime);
    if (url.endsWith("/tools/fence")) return response(fence);
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions"))
      return response(
        {
          ...session,
          locale: input.locale,
          request_id: input.request_id,
          sequence: 0,
          active_turn_id: null,
        },
        201,
      );
    if (url.endsWith("/tool-grants"))
      return response(
        asTarget({
          ...grant,
          request_id: input.request_id,
          turn_request_id: input.turn_request_id,
          text_sha256: textHash(input.text),
        }),
        201,
      );
    if (url.endsWith("/tool-turns"))
      return response(
        { ...turn, request_id: input.request_id, user_text: input.text },
        202,
      );
    if (url.endsWith("/tools")) return response(current);
    if (url.endsWith("/decision")) {
      current = {
        ...targetTranscript,
        revision: 2,
        calls: [
          {
            ...targetSaved,
            decision: { ...targetSaved.decision, request_id: input.request_id },
          },
        ],
      };
      return response(
        { ...targetSaved.decision, request_id: input.request_id },
        201,
      );
    }
    throw Error("Synthetic unavailable " + url);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
it.each(["en", "ko"] as const)(
  "target consent remains separate from exact approval (%s)",
  async (locale) => {
    const fetch = mockChat();
    const view = vi.fn();
    render(<ChatPanel locale={locale} onViewTarget={view} />);
    await waitFor(() =>
      expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
    );
    expect(screen.getByTestId("chat-tool-scope")).toHaveValue("agent_v1");
    fireEvent.click(screen.getByTestId("chat-new-session"));
    fireEvent.click(screen.getByTestId("chat-start-confirm"));
    await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
    fireEvent.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() =>
      expect(
        screen.getByRole("option", {
          name: locale === "en" ? "Create target" : "대상 생성",
        }),
      ).toBeEnabled(),
    );
    fireEvent.change(screen.getByTestId("chat-tool-scope"), {
      target: { value: "target_create_v2" },
    });
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "create literal target" },
    });
    fireEvent.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
    fireEvent.click(screen.getByTestId("chat-send"));
    const approve = await screen.findByTestId(`chat-tool-approve-${cid}`);
    expect(screen.getByTestId(`chat-tool-proposal-${cid}`)).toHaveTextContent(
      target.address,
    );
    expect(
      screen.getByTestId(`chat-tool-proposal-${cid}`),
    ).not.toHaveTextContent("complete Skill list");
    expect(screen.getByTestId("chat-tool-scope")).toBeDisabled();
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/decision")),
    ).toHaveLength(0);
    fireEvent.click(approve);
    const link = await screen.findByTestId(`chat-tool-view-saved-${cid}`);
    fireEvent.click(link);
    expect(view).toHaveBeenCalledWith({ target, after_revision: 3 });
    expect(
      JSON.parse(
        fetch.mock.calls.find(([u]) => u.endsWith("/tool-grants"))![1]!
          .body as string,
      ).scope,
    ).toBe("target_create");
  },
);
it("legacy metadata disables target mode", async () => {
  mockChat(toolRuntime);
  render(<ChatPanel locale="en" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: "Create target" }),
    ).toBeDisabled(),
  );
});
it("retains captured target authority across delayed response and selector rerender", async () => {
  let release!: (r: Response) => void;
  let input: Record<string, unknown> = {};
  const fetch = mockChat();
  const original = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (u, i) => {
    if (u.endsWith("/tool-grants")) {
      input = JSON.parse(i!.body as string);
      return new Promise<Response>((r) => {
        release = r;
      });
    }
    return original(u, i);
  });
  const { result, rerender } = renderHook(
    ({ scope }) => useChat("en", true, true, scope),
    {
      initialProps: {
        scope: "target_create_v2" as "agent_v1" | "target_create_v2",
      },
    },
  );
  await waitFor(() => expect(result.current.runtime?.supported).toBe(true));
  await act(async () => {
    await result.current.start();
  });
  act(() => result.current.setInput("hello"));
  let send!: Promise<void>;
  act(() => {
    send = result.current.send(true);
  });
  rerender({ scope: "agent_v1" });
  await act(async () => {
    release(
      response(
        asTarget({
          ...grant,
          request_id: input.request_id as string,
          turn_request_id: input.turn_request_id as string,
        }),
        201,
      ),
    );
    await send;
  });
  expect(input.scope).toBe("target_create");
  expect(
    fetch.mock.calls.filter(([u]) => u.endsWith("/tool-turns")),
  ).toHaveLength(1);
  expect(result.current.toolTurns).toEqual([tid]);
});
it.each(["agent_v1", "target_create_v2"] as const)(
  "unknown grant ACK retains immutable %s through GET-only recovery and explicit continuation",
  async (scope) => {
    const fetch = mockChat();
    const original = fetch.getMockImplementation()!;
    let captured: Record<string, unknown> = {},
      correct = false;
    fetch.mockImplementation(async (u, i) => {
      if (u.endsWith("/tool-grants")) {
        captured = JSON.parse(i!.body as string);
        throw Error("Synthetic lost ACK");
      }
      if (u.includes("tool-grants/by-request")) {
        const g = {
          ...grant,
          request_id: captured.request_id as string,
          turn_request_id: captured.turn_request_id as string,
        };
        return response(
          (scope === "target_create_v2") === correct ? asTarget(g) : g,
        );
      }
      return original(u, i);
    });
    const { result, rerender } = renderHook(
      ({ selected }) => useChat("en", true, true, selected),
      { initialProps: { selected: scope as "agent_v1" | "target_create_v2" } },
    );
    await waitFor(() => expect(result.current.runtime?.supported).toBe(true));
    await act(async () => {
      await result.current.start();
    });
    act(() => result.current.setInput("hello"));
    await act(async () => {
      await result.current.send(true);
    });
    expect(result.current.phase).toBe("unknown-send");
    rerender({
      selected: scope === "agent_v1" ? "target_create_v2" : "agent_v1",
    });
    await act(async () => {
      await result.current.recoverSubmission();
    });
    expect(result.current.phase).toBe("unknown-send");
    correct = true;
    await act(async () => {
      await result.current.recoverSubmission();
    });
    expect(result.current.phase).toBe("grant-recovered");
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/tool-turns")),
    ).toHaveLength(0);
    act(() => result.current.setInput("dirty editor preserved"));
    await act(async () => {
      await result.current.continueGrant();
    });
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/tool-turns")),
    ).toHaveLength(1);
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/tool-grants")),
    ).toHaveLength(1);
    expect(result.current.input).toBe("dirty editor preserved");
  },
);
it("saved target fact and navigation survive failed final prose", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(targetTranscript)),
  );
  const failed = parseTurn({
    ...turn,
    status: "failed",
    error_code: "CHAT_TIMEOUT",
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  });
  const view = vi.fn();
  render(
    <ToolRecords
      turn={failed}
      locale="en"
      enabled
      viewEpoch={0}
      canWrite={false}
      onViewTarget={view}
    />,
  );
  fireEvent.click(await screen.findByTestId(`chat-tool-view-saved-${cid}`));
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent("Saved ·");
  expect(view).toHaveBeenCalledWith({ target, after_revision: 3 });
});
