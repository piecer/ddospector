import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Application } from "./App";
import { pages } from "./pageRegistry";
import {
  response,
  runtimeFixture,
  session,
} from "./pages/ai/chat-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("keeps only Agent chat reads available on initial workspace failure", async () => {
  window.history.replaceState(null, "", "/agent");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("chat/runtime")) return response(runtimeFixture);
      if (url.endsWith("chat/sessions"))
        return response({ schema_version: 1, sessions: [session] });
      throw new Error("workspace down");
    }),
  );
  render(<Application pages={pages} />);
  await screen.findByRole("heading", { name: "Local API is unavailable" });
  expect(await screen.findByTestId(`chat-session-${session.id}`)).toBeEnabled();
  expect(screen.getByTestId("chat-new-session")).toBeDisabled();
  expect(screen.getByTestId("chat-send")).toBeDisabled();
  fireEvent.click(screen.getByRole("link", { name: "Skill library" }));
  await waitFor(() =>
    expect(screen.queryByTestId("chat-history")).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByRole("button", { name: "Create Skill" }),
  ).not.toBeInTheDocument();
});
