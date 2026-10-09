import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentPage } from "./pages/ai";
import { SettingsPage } from "./pages/lab";
import { workspaceFixture } from "./test/fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("AI model settings entry points", () => {
  for (const Page of [AgentPage, SettingsPage]) {
    it.each(["en", "ko"] as const)(
      `${Page.name} opens model settings in %s without calling a model`,
      async (locale) => {
        const navigate = vi.fn();
        const fetch = vi.fn();
        vi.stubGlobal("fetch", fetch);
        render(
          <Page
            data={workspaceFixture()}
            locale={locale}
            navigate={navigate}
            refresh={vi.fn().mockResolvedValue(undefined)}
          />,
        );
        await userEvent.click(
          screen.getByRole("button", {
            name: locale === "ko" ? "AI 설정" : "AI settings",
          }),
        );
        expect(navigate).toHaveBeenCalledExactlyOnceWith("ai-settings");
        expect(fetch).not.toHaveBeenCalled();
      },
    );
  }
});
