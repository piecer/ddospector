import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AISettingsPage } from "./index";
import { workspaceFixture } from "../../test/fixtures";
import { empty, profile, response } from "./testFixtures";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const styles = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "ai-settings.css"),
  "utf8",
);
afterEach(() => vi.unstubAllGlobals());
it("allows long model/URL text to wrap and keeps controls touch-sized", async () => {
  const model = "model-" + "a".repeat(190);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        response({ ...empty(), profiles: [profile({ model })] }),
      ),
  );
  const stylesheet = document.createElement("style");
  stylesheet.textContent = styles;
  document.head.append(stylesheet);
  try {
    render(
      <AISettingsPage
        data={workspaceFixture()}
        locale="en"
        navigate={vi.fn()}
        refresh={vi.fn()}
      />,
    );
    const text = await screen.findByText(model);
    expect(getComputedStyle(text).overflowWrap).toBe("anywhere");
    expect(
      getComputedStyle(
        screen.getByRole("button", { name: "Edit Review model" }),
      ).minHeight,
    ).toBe("44px");
    expect(text).not.toHaveAttribute("title");
  } finally {
    stylesheet.remove();
  }
});
