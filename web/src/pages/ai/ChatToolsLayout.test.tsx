import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToolRecords } from "./ToolRecords";
import { parseTurn } from "./chat-wire";
import { turn, response, tid } from "./chat-test-fixtures";
import { call, cid, transcript, hash } from "./chat-tool-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("ships explicit narrow-layout containment without truncating literal tool values (static CSS, not browser geometry)", () => {
  const css = readFileSync("src/pages/ai/chat.css", "utf8");
  expect(css).toContain(".chat-tool-diff");
  expect(css).toMatch(
    /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/,
  );
  expect(css).toMatch(/@media\s*\(max-width:\s*600px\)/);
  expect(css).toContain(".chat-tool-consent");
});
it("Korean tool facts stay plain text, unavailable workspace blocks approval, and keyboard denial sends only the exact proposal", async () => {
  const name = "<img src=x onerror=alert(1)> literal 한글";
  const args = { ...call.arguments, name };
  const proposal = {
    ...call.proposal,
    after: { ...call.proposal.after, name },
  };
  proposal.digest = hash({
    call_id: cid,
    grant_id: call.grant_id,
    expected_draft_revision: proposal.expected_draft_revision,
    before: proposal.before,
    after: proposal.after,
    expires_at: proposal.expires_at,
  });
  const witness = {
    ...call,
    arguments: args,
    args_digest: hash(args),
    proposal,
  };
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST")
      return response(
        {
          schema_version: 1,
          ...JSON.parse(init.body as string),
          call_id: cid,
          accepted_at: call.started_at,
        },
        201,
      );
    return response({ ...transcript, calls: [witness] });
  });
  vi.stubGlobal("fetch", fetch);
  const view = render(
    <ToolRecords
      turn={parseTurn(turn)}
      locale="ko"
      enabled
      viewEpoch={0}
      canWrite={false}
    />,
  );
  expect(await screen.findByTestId(`chat-tool-approve-${cid}`)).toBeDisabled();
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveTextContent(name);
  expect(view.container.querySelector("img,script,a")).toBeNull();
  const deny = screen.getByTestId(`chat-tool-deny-${cid}`);
  deny.focus();
  await userEvent.keyboard("{Enter}");
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(([, i]) => i?.method === "POST"),
    ).toHaveLength(1),
  );
  const input = JSON.parse(
    fetch.mock.calls.find(([, i]) => i?.method === "POST")![1]!.body as string,
  );
  expect(input).toEqual({
    request_id: expect.any(String),
    proposal_digest: proposal.digest,
    decision: "deny",
  });
  fireEvent.click(screen.getByTestId(`chat-tools-refresh-${tid}`));
  expect(screen.getByTestId(`chat-tool-${cid}`)).not.toHaveTextContent(
    "저장됨 ·",
  );
});
