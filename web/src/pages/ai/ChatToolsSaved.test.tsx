import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AgentPage } from "./AgentPage";
import { aiFixture } from "./testFixtures";
import {
  response,
  runtimeFixture,
  session,
  turn,
  sid,
} from "./chat-test-fixtures";
import {
  after,
  cid,
  fence,
  savedCall,
  toolRuntime,
  transcript,
} from "./chat-tool-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
function install() {
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/tools/runtime")) return response(toolRuntime);
    if (url.endsWith("/tools/fence")) return response(fence);
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions"))
      return response({
        schema_version: 1,
        sessions: [{ ...session, active_turn_id: null }],
      });
    if (url.endsWith("/tools"))
      return response({ ...transcript, revision: 3, calls: [savedCall] });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session: { ...session, active_turn_id: null },
        turns: [
          {
            ...turn,
            status: "cancelled",
            error_code: "CHAT_CANCELLED",
            transport: "closed",
            provider_stop: "unknown",
            finished_at: turn.created_at,
          },
        ],
        next_before_sequence: null,
      });
    throw Error("Unexpected " + url);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
it("saved tool result refreshes workspace once, opens existing Agent form, and preserves dirty assignment", async () => {
  const fetch = install();
  const props = aiFixture();
  const view = render(<AgentPage {...props} />);
  fireEvent.click(screen.getByText("Assignment and deterministic preview"));
  fireEvent.change(screen.getByLabelText("Agent name"), {
    target: { value: "my dirty draft" },
  });
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await waitFor(() => expect(props.refresh).toHaveBeenCalledTimes(1));
  const data = {
    ...props.data,
    agent_profile: {
      ...props.data.agent_profile,
      name: after.name,
      skill_ids: after.skill_ids,
    },
  };
  view.rerender(<AgentPage {...props} data={data} />);
  fireEvent.click(await screen.findByTestId(`chat-tool-view-saved-${cid}`));
  expect(screen.getByLabelText("Agent name")).toHaveValue("my dirty draft");
  expect(
    screen.getByText(/saved profile changed while you were editing/),
  ).toBeVisible();
  expect(screen.getByLabelText("Agent name")).toHaveFocus();
  expect(fetch.mock.calls.some(([url]) => url.endsWith("/decision"))).toBe(
    false,
  );
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent("Saved ·");
});
it("saved-but-stale warning offers only workspace refresh and never repeats a write", async () => {
  install();
  const props = aiFixture();
  props.refresh = vi
    .fn()
    .mockRejectedValueOnce(Error("offline"))
    .mockResolvedValue(undefined);
  render(<AgentPage {...props} />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await screen.findByText(
    "Saved, but workspace view is stale. Your unsaved assignment is preserved.",
  );
  fireEvent.click(screen.getByTestId("chat-tools-workspace-refresh"));
  await waitFor(() => expect(props.refresh).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent("Saved ·");
});
