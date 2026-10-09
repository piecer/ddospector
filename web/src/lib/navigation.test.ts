import { describe, it, expect } from "vitest";
import { navigation, routeFromPath } from "./navigation";

describe("workspace navigation contract", () => {
  it("provides every approved menu once with both languages", () => {
    expect(navigation.map((item) => item.id)).toEqual([
      "overview",
      "campaigns",
      "runs",
      "findings",
      "evidence",
      "targets",
      "instruments",
      "mcp-servers",
      "profiles",
      "agent",
      "ai-settings",
      "skills",
      "approvals",
      "audit",
      "settings",
    ]);
    expect(new Set(navigation.map((item) => item.id)).size).toBe(15);
    for (const item of navigation) {
      expect(item.label.en.trim()).not.toBe("");
      expect(item.label.ko.trim()).not.toBe("");
    }
  });
  it("resolves only the documented root alias to overview", () => {
    expect(routeFromPath("/")).toBe("overview");
    expect(routeFromPath("")).toBeNull();
    expect(routeFromPath("//")).toBeNull();
    expect(routeFromPath("/overview/extra")).toBeNull();
  });
  it("resolves deep links but does not silently turn unknown routes into overview", () => {
    expect(routeFromPath("/skills")).toBe("skills");
    expect(routeFromPath("/ai-settings")).toBe("ai-settings");
    expect(routeFromPath("/not-a-route")).toBeNull();
  });
});
