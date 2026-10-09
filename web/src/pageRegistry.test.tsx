import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { pages } from "./pageRegistry";
import { navigation } from "./lib/navigation";
import { workspaceFixture } from "./test/fixtures";
describe("integrated page registry", () => {
  it("binds every menu entry to exactly one actual component", () => {
    expect(Object.keys(pages).sort()).toEqual(
      navigation.map((item) => item.id).sort(),
    );
  });
  for (const item of navigation)
    it(`renders the actual ${item.id} page without fabricated workspace data`, () => {
      const Page = pages[item.id];
      render(
        <Page
          data={workspaceFixture()}
          locale="en"
          navigate={vi.fn()}
          refresh={vi.fn().mockResolvedValue(undefined)}
        />,
      );
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    });
});
