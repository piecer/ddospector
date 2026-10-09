import { describe, expect, it } from "vitest";
import { validAddress, validEndpoint, validName } from "./validation";

describe("draft validation boundaries", () => {
  it.each(["https:///mcp.test", "https:////mcp.test", "http://?mcp.test"])(
    "rejects a missing HTTP authority instead of allowing URL normalization: %s",
    (value) => {
      expect(validEndpoint(value, "streamable_http")).toBe(false);
    },
  );
  it.each(["observer\n", "observer\r", "observer\t"])(
    "rejects control characters in registry IDs: %j",
    (value) => {
      expect(validEndpoint(value, "stdio")).toBe(false);
    },
  );
  it.each([
    "192.0.2.1",
    "2001:db8::1",
    "::1",
    "dut.example.test",
    "sink-1.test.",
  ])(
    "accepts syntactically valid draft addresses without resolution: %s",
    (value) => {
      expect(validAddress(value)).toBe(true);
    },
  );
  it.each([
    "192.168.00.1",
    "1.2.3",
    "[::1]",
    "::zzz",
    "a".repeat(64) + ".test",
    "host.test:443",
  ])("rejects malformed IP and hostname forms: %s", (value) => {
    expect(validAddress(value)).toBe(false);
  });
  it("rejects query strings and userinfo in metadata-only MCP endpoints", () => {
    expect(
      validEndpoint("https://mcp.test?label=team@lab", "streamable_http"),
    ).toBe(false);
    expect(validEndpoint("https://team@lab/mcp", "streamable_http")).toBe(
      false,
    );
  });
  it.each(["version=1", "owner=team@lab"])(
    "rejects query strings before draft submission: %s",
    (query) => {
      expect(
        validEndpoint(
          `https://mcp.example.test/mcp?${query}`,
          "streamable_http",
        ),
      ).toBe(false);
    },
  );
  it("admits exact metadata limits and rejects their overflow", () => {
    expect(validName("가".repeat(120))).toBe(true);
    expect(validName("가".repeat(121))).toBe(false);
    expect(validEndpoint("a".repeat(64), "stdio")).toBe(true);
    expect(validEndpoint("a".repeat(65), "stdio")).toBe(false);
    const prefix = "https://mcp.example.test/";
    expect(
      validEndpoint(
        prefix + "x".repeat(512 - prefix.length),
        "streamable_http",
      ),
    ).toBe(true);
    expect(
      validEndpoint(
        prefix + "x".repeat(513 - prefix.length),
        "streamable_http",
      ),
    ).toBe(false);
  });
});
