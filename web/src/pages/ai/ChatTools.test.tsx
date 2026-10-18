import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  call,
  cid,
  decision,
  drid,
  fence,
  grant,
  savedCall,
  toolRuntime,
  transcript,
  textHash,
} from "./chat-tool-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("requires unchecked per-message read/propose consent, sends native route and separate exact approval, never calls ACK Saved", async () => {
  let submitted = { ...turn };
  let current = { ...transcript };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const input = init?.body ? JSON.parse(init.body as string) : null;
    if (url.endsWith("/tools/runtime")) return response(toolRuntime);
    if (url.endsWith("/tools/fence")) return response(fence);
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions") && init?.method === "POST")
      return response(
        {
          ...session,
          request_id: input.request_id,
          sequence: 0,
          active_turn_id: null,
        },
        201,
      );
    if (url.endsWith("/tool-grants"))
      return response(
        {
          ...grant,
          request_id: input.request_id,
          turn_request_id: input.turn_request_id,
          text_sha256: textHash(input.text),
        },
        201,
      );
    if (url.endsWith("/tool-turns")) {
      submitted = {
        ...turn,
        request_id: input.request_id,
        user_text: input.text,
      };
      return response(submitted, 202);
    }
    if (url.includes("/events?")) return new Response("", { status: 503 });
    if (url === `/api/v1/chat/turns/${tid}`) return response(submitted);
    if (url.endsWith("/tools")) return response(current);
    if (url.endsWith("/decision")) {
      current = {
        ...transcript,
        revision: 2,
        calls: [
          {
            ...call,
            status: "executing",
            decision: { ...decision, request_id: input.request_id },
          } as unknown as typeof call,
        ],
      };
      return response({ ...decision, request_id: input.request_id }, 201);
    }
    throw Error("Unexpected URL " + url);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="en" />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  expect(
    fetch.mock.calls.some(
      ([url]) => url.includes("/tools") || url.includes("tool-grants"),
    ),
  ).toBe(false);
  expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
  fireEvent.click(screen.getByTestId("chat-new-session"));
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
  fireEvent.click(screen.getByTestId("chat-tools-toggle"));
  fireEvent.change(screen.getByTestId("chat-input"), {
    target: { value: "Change my Agent name" },
  });
  await waitFor(() => expect(screen.getByTestId("chat-send")).toBeEnabled());
  fireEvent.click(screen.getByTestId("chat-send"));
  const approve = await screen.findByTestId(`chat-tool-approve-${cid}`);
  expect(screen.getByTestId(`chat-tool-proposal-${cid}`)).toHaveTextContent(
    call.proposal.after.name.trim(),
  );
  expect(
    fetch.mock.calls.filter(
      ([url, i]) => url.endsWith("/decision") && i?.method === "POST",
    ),
  ).toHaveLength(0);
  expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
  fireEvent.click(approve);
  await waitFor(() =>
    expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent(
      "Acknowledged",
    ),
  );
  expect(screen.getByTestId(`chat-tool-${cid}`)).not.toHaveTextContent(
    "Saved ·",
  );
  const post = fetch.mock.calls.find(([url]) => url.endsWith("/decision"))!;
  expect(JSON.parse(post[1]!.body as string)).toEqual({
    request_id: expect.any(String),
    proposal_digest: call.proposal.digest,
    decision: "approve",
  });
  const acceptedDecision = current.calls[0].decision;
  current = {
    ...transcript,
    revision: 3,
    calls: [
      { ...savedCall, decision: acceptedDecision } as unknown as typeof call,
    ],
  };
  fireEvent.click(screen.getByTestId(`chat-tools-refresh-${tid}`));
  await waitFor(() =>
    expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent("Saved ·"),
  );
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/decision")),
  ).toHaveLength(1);
  expect(
    fetch.mock.calls.some(
      ([url]) => url === `/api/v1/chat/sessions/${sid}/turns`,
    ),
  ).toBe(false);
  expect(drid).not.toBe("");
});
