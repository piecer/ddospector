import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
import {
  after,
  call,
  cid,
  decision,
  fence,
  transcript,
  toolRuntime,
} from "./chat-tool-test-fixtures";
import { aiFixture } from "./testFixtures";
afterEach(() => vi.unstubAllGlobals());
it("reviews immutable uncertainty and independent current Agent/revision, then old clear receipt cannot clear newer fence B", async () => {
  const uncertain = {
    ...call,
    status: "uncertain",
    decision,
    error_code: "CHAT_TOOL_UNCERTAIN",
    finished_at: call.started_at,
  };
  let currentFence = { ...fence, generation: 1, fenced: true, call_ids: [cid] };
  let reconcileResolve: (r: Response) => void = () => undefined;
  let reconciliationInput: Record<string, unknown> = {};
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/tools/runtime")) return response(toolRuntime);
    if (url.endsWith("/tools/fence")) return response(currentFence);
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions"))
      return response({
        schema_version: 1,
        sessions: [{ ...session, active_turn_id: null }],
      });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session: { ...session, active_turn_id: null },
        turns: [
          {
            ...turn,
            status: "failed",
            error_code: "CHAT_TOOL_UNCERTAIN",
            transport: "closed",
            provider_stop: "unknown",
            finished_at: turn.created_at,
          },
        ],
        next_before_sequence: null,
      });
    if (url.endsWith("/tools"))
      return response({ ...transcript, revision: 2, calls: [uncertain] });
    if (url === "/api/v1/workspace")
      return response({
        ...aiFixture().data,
        agent_profile: {
          ...aiFixture().data.agent_profile,
          name: after.name,
          skill_ids: after.skill_ids,
        },
      });
    if (url.endsWith("/reconcile")) {
      reconciliationInput = JSON.parse(init!.body as string);
      return new Promise<Response>((resolve) => {
        reconcileResolve = resolve;
      });
    }
    throw Error("Unexpected " + url);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="en" />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await screen.findByTestId(`chat-tool-${cid}`);
  fireEvent.click(screen.getByTestId("chat-tools-reconcile-review"));
  await waitFor(() =>
    expect(screen.getByTestId("chat-tools-reconcile-confirm")).toBeEnabled(),
  );
  expect(screen.getByTestId("chat-tools-current-agent")).toHaveTextContent(
    after.name.trim(),
  );
  expect(screen.getByTestId("chat-tools-current-agent")).toHaveTextContent("2");
  fireEvent.click(screen.getByTestId("chat-tools-reconcile-confirm"));
  expect(reconciliationInput).toEqual({
    request_id: expect.any(String),
    expected_generation: 1,
    expected_draft_revision: 2,
    acknowledge_uncertain: true,
  });
  currentFence = { ...currentFence, generation: 3 };
  fireEvent.click(
    screen.getByRole("button", { name: "Read tool availability / fence" }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("chat-tools-status")).toHaveTextContent("3"),
  );
  await act(async () =>
    reconcileResolve(
      response({
        schema_version: 1,
        request_id: reconciliationInput.request_id,
        acknowledged_call_ids: [cid],
        generation: 2,
        write_fenced: false,
        prior_outcomes: "remain_uncertain",
      }),
    ),
  );
  await waitFor(() =>
    expect(screen.getByTestId("chat-tools-status")).toHaveTextContent("3"),
  );
  expect(screen.getByTestId("chat-tools-status")).toHaveTextContent("fenced");
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveAttribute(
    "data-tool-status",
    "uncertain",
  );
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/reconcile")),
  ).toHaveLength(1);
  expect(
    fetch.mock.calls.some(([url]) => url === `/api/v1/chat/turns/${tid}/tools`),
  ).toBe(true);
});
