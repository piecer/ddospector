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
import { useToolAuthority } from "./useToolAuthority";
import { useToolTranscript } from "./useToolTranscript";
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
  skillCall,
  skillSaved,
  skillRuntime,
  skillTranscript,
  draft as skill,
} from "./chat-skill-test-fixtures";
function asSkill(g: typeof grant) {
  const { proposal_fields: fields, ...rest } = g;
  void fields;
  return {
    ...rest,
    schema_version: 3,
    scope: "skill_create",
    read_scope: ["skills", "skill"],
    proposal_tools: ["skill_create"],
  };
}
afterEach(() => vi.unstubAllGlobals());
function mockChat(runtime: unknown = skillRuntime) {
  let current: unknown = { ...skillTranscript, calls: [skillCall] };
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
        asSkill({
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
        ...skillTranscript,
        revision: 2,
        calls: [
          {
            ...skillSaved,
            decision: { ...skillSaved.decision, request_id: input.request_id },
          },
        ],
      };
      return response(
        { ...skillSaved.decision, request_id: input.request_id },
        201,
      );
    }
    throw Error("Synthetic unavailable " + url);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
it.each(["en", "ko"] as const)(
  "U3 U4 Skill consent remains separate from exact inert approval (%s)",
  async (locale) => {
    const fetch = mockChat();
    const view = vi.fn();
    render(<ChatPanel locale={locale} onViewSkill={view} />);
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
          name: locale === "en" ? "Create Skill" : "스킬 생성",
        }),
      ).toBeEnabled(),
    );
    fireEvent.change(screen.getByTestId("chat-tool-scope"), {
      target: { value: "skill_create_v3" },
    });
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    fireEvent.change(screen.getByTestId("chat-input"), {
      target: { value: "create literal skill" },
    });
    fireEvent.click(screen.getByTestId("chat-tools-toggle"));
    await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
    fireEvent.click(screen.getByTestId("chat-send"));
    const approve = await screen.findByTestId(`chat-tool-approve-${cid}`);
    const proposal = screen.getByTestId(`chat-tool-proposal-${cid}`);
    expect(proposal.textContent).toContain(skill.instructions.en);
    expect(proposal.querySelector("script, a, img")).toBeNull();
    expect(
      screen.getByTestId(`chat-tool-proposal-${cid}`),
    ).not.toHaveTextContent("complete Skill list");
    expect(screen.getByTestId("chat-tool-scope")).toBeDisabled();
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/decision")),
    ).toHaveLength(0);
    fireEvent.click(approve);
    fireEvent.click(approve);
    const link = await screen.findByTestId(`chat-tool-view-saved-${cid}`);
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/decision")),
    ).toHaveLength(1);
    fireEvent.click(link);
    expect(view).toHaveBeenCalledWith({ skill, after_revision: 3 });
    expect(
      JSON.parse(
        fetch.mock.calls.find(([u]) => u.endsWith("/tool-grants"))![1]!
          .body as string,
      ).scope,
    ).toBe("skill_create");
  },
);
it("legacy metadata disables skill mode", async () => {
  mockChat(toolRuntime);
  render(<ChatPanel locale="en" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "Create Skill" })).toBeDisabled(),
  );
});
it("retains captured skill authority across delayed response and selector rerender", async () => {
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
        scope: "skill_create_v3" as "agent_v1" | "skill_create_v3",
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
        asSkill({
          ...grant,
          request_id: input.request_id as string,
          turn_request_id: input.turn_request_id as string,
        }),
        201,
      ),
    );
    await send;
  });
  expect(input.scope).toBe("skill_create");
  expect(
    fetch.mock.calls.filter(([u]) => u.endsWith("/tool-turns")),
  ).toHaveLength(1);
  expect(result.current.toolTurns).toEqual([tid]);
});
it.each(["agent_v1", "skill_create_v3"] as const)(
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
          (scope === "skill_create_v3") === correct ? asSkill(g) : g,
        );
      }
      return original(u, i);
    });
    const { result, rerender } = renderHook(
      ({ selected }) => useChat("en", true, true, selected),
      { initialProps: { selected: scope as "agent_v1" | "skill_create_v3" } },
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
      selected: scope === "agent_v1" ? "skill_create_v3" : "agent_v1",
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
it("U5 saved Skill fact and navigation survive failed final prose", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(skillTranscript)),
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
      onViewSkill={view}
    />,
  );
  fireEvent.click(await screen.findByTestId(`chat-tool-view-saved-${cid}`));
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent("Saved ·");
  expect(view).toHaveBeenCalledWith({ skill, after_revision: 3 });
});
it.each([1, 2, 3])(
  "U3 finite runtime %s capability matrix preserves Target on v3",
  async (version) => {
    const rt = {
      ...skillRuntime,
      schema_version: version,
      tools: skillRuntime.tools.slice(0, version + 1),
    };
    mockChat(rt);
    const { result } = renderHook(() => useToolAuthority(true));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.canGrant).toBe(true);
    expect(result.current.targetSupported).toBe(version === 2 || version === 3);
    expect(result.current.skillSupported).toBe(version === 3);
  },
);

it("U5 lost Skill decision ACK keeps exact proposal blocked across GET-only reload", async () => {
  const awaiting = { ...skillTranscript, calls: [skillCall] };
  const fetch = vi.fn(async (_u: string, i?: RequestInit) => {
    if (i?.method === "POST") throw Error("synthetic lost ACK");
    return response(awaiting);
  });
  vi.stubGlobal("fetch", fetch);
  const { result, rerender } = renderHook(
    ({ epoch }) => useToolTranscript(parseTurn(turn), true, epoch),
    { initialProps: { epoch: 0 } },
  );
  await waitFor(() => expect(result.current.record?.calls).toHaveLength(1));
  await act(async () => {
    await result.current.decide(
      result.current.record!.calls[0],
      "approve",
      true,
    );
  });
  expect(result.current.decisionState).toBe("unknown");
  rerender({ epoch: 1 });
  await waitFor(() => expect(result.current.record?.calls).toHaveLength(1));
  await act(async () => {
    await result.current.decide(
      result.current.record!.calls[0],
      "approve",
      true,
    );
  });
  expect(fetch.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(
    1,
  );
  expect(result.current.decisionBlocked).toBe(true);
});
it("U5 immutable saved Skill survives stale transcript on explicit reload", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(response({ ...skillTranscript, revision: 2 }))
    .mockImplementation(async () =>
      response({ ...skillTranscript, calls: [skillCall] }),
    );
  vi.stubGlobal("fetch", fetch);
  const { result, rerender } = renderHook(
    ({ epoch }) => useToolTranscript(parseTurn(turn), true, epoch),
    { initialProps: { epoch: 0 } },
  );
  await waitFor(() =>
    expect(result.current.record?.calls[0].status).toBe("succeeded"),
  );
  rerender({ epoch: 1 });
  await waitFor(() => expect(result.current.stale).toBe(true));
  expect(result.current.record?.calls[0].result).toEqual(skillSaved.result);
});

it("U3 selecting Skill alone sends no grant; unchecked next message is plain text only", async () => {
  const fetch = mockChat();
  const original = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (u, i) => {
    if (u.endsWith("/turns") && i?.method === "POST") {
      const input = JSON.parse(i.body as string);
      return response(
        { ...turn, request_id: input.request_id, user_text: input.text },
        202,
      );
    }
    return original(u, i);
  });
  render(<ChatPanel locale="en" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId("chat-new-session"));
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "Create Skill" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByTestId("chat-tool-scope"), {
    target: { value: "skill_create_v3" },
  });
  expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
  expect(
    fetch.mock.calls.some(
      ([u]) => u.endsWith("tool-grants") || u.endsWith("tool-turns"),
    ),
  ).toBe(false);
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "plain" },
  });
  fireEvent.click(screen.getByTestId("chat-send"));
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(
        ([u, i]) => u.endsWith("/turns") && i?.method === "POST",
      ),
    ).toHaveLength(1),
  );
  expect(
    fetch.mock.calls.some(
      ([u]) => u.includes("tool-grants") || u.includes("tool-turns"),
    ),
  ).toBe(false);
});
