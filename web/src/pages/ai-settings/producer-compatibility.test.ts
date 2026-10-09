import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { aiSettingsAPI } from "./client";
import { profileIssue } from "./validation";

// Exact independent-review TestClient/server response bytes; never reconstructed.
// Original hashes and provenance are retained in fix-evidence.
afterEach(() => vi.unstubAllGlobals());
it.each([
  "numeric-tld",
  "hex-looking-host",
  "unicode-cyrillic-casefold",
  "unicode-latin-casefold",
])(
  "accepts the real producer's %s response without changing literals",
  async (id) => {
    const body = readFileSync(
      `${process.cwd()}/src/pages/ai-settings/test-data/${id}-put-response.json`,
      "utf8",
    );
    const expected = JSON.parse(body);
    const fetcher = vi.fn().mockImplementation(() => new Response(body));
    vi.stubGlobal("fetch", fetcher);
    const actual = await aiSettingsAPI.read();
    expect(actual).toEqual(expected);
    for (const profile of actual.profiles)
      expect(profileIssue(profile, actual.profiles)).toBeNull();
    expect(await aiSettingsAPI.read()).toEqual(expected);
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ai-settings",
      "/api/v1/ai-settings",
    ]);
  },
);
