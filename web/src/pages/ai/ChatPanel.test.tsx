import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";
import {
  response,
  runtimeFixture,
  session,
  turn,
  sid,
  tid,
} from "./chat-test-fixtures";
import { AgentPage } from "./AgentPage";
import { aiFixture } from "./testFixtures";
afterEach(() => vi.unstubAllGlobals());
it("requires endpoint/model consent then sends to the API and renders only plain text", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions") && init?.method === "POST")
      return response(
        {
          ...session,
          sequence: 0,
          active_turn_id: null,
          request_id: JSON.parse(init.body as string).request_id,
        },
        201,
      );
    if (url.endsWith("/turns"))
      return response(
        { ...turn, request_id: JSON.parse(init!.body as string).request_id },
        202,
      );
    if (url.includes("/events?")) {
      const request = JSON.parse(
        fetch.mock.calls.find((c) => c[0].endsWith("/turns"))![1]!
          .body as string,
      ).request_id;
      const final = {
        ...turn,
        request_id: request,
        revision: 3,
        status: "succeeded",
        assistant_text: "<img src=x> https://example.invalid/ **plain**",
        transport: "closed",
        provider_stop: "unknown",
        finished_at: turn.created_at,
      };
      return new Response(
        `event: chat\ndata: ${JSON.stringify({ schema_version: 1, turn_id: tid, revision: 3, type: "snapshot", turn: final, text: null })}\n\n`,
        { headers: { "Content-Type": "text/event-stream" } },
      );
    }
    throw new Error("Unexpected test URL: " + url);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="en" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  expect(fetch.mock.calls.every((c) => c[1]?.method === "GET")).toBe(true);
  fireEvent.click(screen.getByTestId("chat-new-session"));
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).getByText(runtimeFixture.profile.endpoint),
  ).toBeVisible();
  expect(within(dialog).getByText(runtimeFixture.profile.model)).toBeVisible();
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "hello" },
  });
  fireEvent.click(screen.getByTestId("chat-send"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-status")).toHaveTextContent("Succeeded"),
  );
  expect(screen.getByTestId("chat-transcript")).toHaveTextContent(
    "<img src=x> https://example.invalid/ **plain**",
  );
  expect(
    screen.getByTestId("chat-transcript").querySelector("img,a,strong"),
  ).toBeNull();
  expect(screen.getByTestId("chat-input")).toHaveValue("");
  expect(
    fetch.mock.calls.filter(
      (c) => c[0] === `/api/v1/chat/sessions/${sid}/turns`,
    ),
  ).toHaveLength(1);
  expect(screen.getByTestId("chat-transcript")).not.toHaveAttribute(
    "aria-live",
  );
});
it("reopens persistent history with bounded older/newest pages and preserves text on a read failure", async () => {
  const saved = { ...session, sequence: 5, active_turn_id: null };
  const makeTurn = (n: number) => ({
    ...turn,
    id: `22222222-2222-4222-8222-${String(n).padStart(12, "0")}`,
    sequence: n,
    status: "succeeded",
    assistant_text: `answer ${n}`,
    user_text: `question ${n}`,
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  });
  let fail = false;
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions"))
      return response({ schema_version: 1, sessions: [saved] });
    if (fail) throw new Error("read failed");
    const before = new URL(url, "http://localhost").searchParams.get(
      "before_sequence",
    );
    const nums = before === "4" ? [2, 3] : before === "2" ? [1] : [4, 5];
    return response({
      schema_version: 1,
      session: saved,
      turns: nums.map(makeTurn),
      next_before_sequence: nums[0] === 1 ? null : nums[0],
    });
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="ko" />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await screen.findByText("answer 5");
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "보존할 입력" },
  });
  fireEvent.click(screen.getByTestId("chat-older"));
  await screen.findByText("answer 2");
  expect(screen.queryByText("answer 5")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("chat-older"));
  await screen.findByText("answer 1");
  expect(screen.getByTestId("chat-older")).toBeDisabled();
  fireEvent.click(screen.getByTestId("chat-newest"));
  await screen.findByText("answer 5");
  fail = true;
  fireEvent.click(screen.getByTestId("chat-older"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-status")).toHaveTextContent(
      "읽을 수 없습니다",
    ),
  );
  expect(screen.getByText("answer 5")).toBeVisible();
  expect(screen.getByTestId("chat-input")).toHaveValue("보존할 입력");
  expect(
    screen.getByTestId("chat-transcript").querySelectorAll("article"),
  ).toHaveLength(2);
});
it("Stop uses independent cancellation and authoritative readback even when writes are disabled", async () => {
  const running = {
    ...turn,
    status: "running",
    transport: "open",
    provider_stop: "unknown",
  };
  const done = {
    ...running,
    revision: 3,
    status: "cancelled",
    error_code: "CHAT_CANCELLED",
    finished_at: turn.created_at,
    transport: "closed",
    assistant_text: "partial retained",
  };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions"))
      return response({ schema_version: 1, sessions: [session] });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session,
        turns: [running],
        next_before_sequence: null,
      });
    if (url.includes("events?")) throw new Error("observation interrupted");
    if (url.endsWith("/cancel")) return response(done);
    if (url.endsWith(tid))
      return response(
        fetch.mock.calls.some((c) => c[0].endsWith("/cancel")) ? done : running,
      );
    throw new Error(String(init));
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="en" mutationsEnabled={false} />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await waitFor(() => expect(screen.getByTestId("chat-stop")).toBeEnabled());
  fireEvent.click(screen.getByTestId("chat-stop"));
  fireEvent.click(screen.getByTestId("chat-stop"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-status")).toHaveTextContent(
      "Cancelled locally",
    ),
  );
  expect(screen.getByText("partial retained")).toBeVisible();
  expect(fetch.mock.calls.filter((c) => c[0].endsWith("/cancel"))).toHaveLength(
    1,
  );
  expect(screen.getByTestId("chat-new-session")).toBeDisabled();
  expect(screen.getByTestId("chat-send")).toBeDisabled();
  await act(async () => {});
});
it("keeps assignment/preview collapsed without discarding edits", () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("test offline")));
  render(<AgentPage {...aiFixture()} />);
  expect(screen.getByLabelText("Agent name")).not.toBeVisible();
  fireEvent.click(screen.getByText("Assignment and deterministic preview"));
  const name = screen.getByLabelText("Agent name");
  fireEvent.change(name, { target: { value: "unsaved assignment" } });
  fireEvent.click(screen.getByText("Assignment and deterministic preview"));
  expect(name).not.toBeVisible();
  fireEvent.click(screen.getByText("Assignment and deterministic preview"));
  expect(name).toHaveValue("unsaved assignment");
  expect(screen.getByRole("button", { name: "Run agent" })).toBeDisabled();
});
it("uses UTF8 input bounds and IME-safe Enter without sending on Shift+Enter", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions"))
      return response({
        schema_version: 1,
        sessions: [{ ...session, sequence: 0, active_turn_id: null }],
      });
    if (init?.method === "POST")
      return response({ code: "CHAT_CONTEXT_LIMIT", message: "fixed" }, 409);
    return response({
      schema_version: 1,
      session: { ...session, sequence: 0, active_turn_id: null },
      turns: [],
      next_before_sequence: null,
    });
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="ko" />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
  const input = screen.getByTestId("chat-input");
  fireEvent.change(input, { target: { value: "한".repeat(2731) } });
  expect(screen.getByTestId("chat-send")).toBeDisabled();
  expect(screen.getByText(/8192 UTF-8/)).toBeVisible();
  fireEvent.change(input, { target: { value: "hello" } });
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    0,
  );
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() =>
    expect(screen.getByTestId("chat-status")).toHaveTextContent(
      "CHAT_CONTEXT_LIMIT",
    ),
  );
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    1,
  );
  expect(input).toHaveValue("hello");
});
it("keeps a full 64-turn conversation readable and requires a new conversation to send", async () => {
  const saved = { ...session, sequence: 64, active_turn_id: null };
  const turns = [63, 64].map((n) => ({
    ...turn,
    sequence: n,
    id: `22222222-2222-4222-8222-${String(n).padStart(12, "0")}`,
    status: "succeeded",
    assistant_text: "saved answer",
    transport: "closed",
    provider_stop: "unknown",
    finished_at: turn.created_at,
  }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [saved] });
      return response({
        schema_version: 1,
        session: saved,
        turns,
        next_before_sequence: 63,
      });
    }),
  );
  render(<ChatPanel locale="en" />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "unsent" },
  });
  expect(screen.getByTestId("chat-send")).toBeDisabled();
  expect(screen.getByText(/64 turns.*new conversation/)).toBeVisible();
  expect(screen.getByTestId("chat-older")).toBeEnabled();
});
it("makes Agent chat-first with visible input and explicit new-session consent", () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("test offline")));
  render(<AgentPage {...aiFixture()} />);
  expect(screen.getByRole("textbox", { name: "Message" })).toBeVisible();
  expect(
    screen.getByRole("button", { name: "New conversation" }),
  ).toBeVisible();
});
