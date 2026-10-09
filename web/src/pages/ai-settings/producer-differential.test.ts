import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { profile } from "./testFixtures";
import { profileIssue, validBaseURL } from "./validation";
import { assertSettingsInput, parseSettingsSnapshot } from "./wire";

const root = resolve(process.cwd(), "..");
const tools = resolve(process.cwd(), "src/pages/ai-settings/tools");
const input = (overrides: Parameters<typeof profile>[0]) => ({
  revision: 0,
  profiles: [profile(overrides)],
  default_profile_id: null,
  agent_profile_id: null,
});
function producer(
  cases: unknown[],
): { status: number; body: string; get: string }[] {
  return JSON.parse(
    execFileSync(
      resolve(root, ".venv/bin/python"),
      [resolve(tools, "producer_oracle.py")],
      {
        input: JSON.stringify(cases),
        encoding: "utf8",
        maxBuffer: 16 * 1024 * 1024,
      },
    ),
  );
}

const acceptedURLs = [
  "https://model.123/v1",
  "https://model.0xabc/v1",
  "https://a.0/v1",
  "https://0xabc/v1",
  "https://model.0123./v1",
  "https://model\u2024example/v1",
  "https://\u0378.example/v1",
  "https://예시.한국/모델",
  "https://faß.de/v1",
  "https://xn--a.example/v1",
  "https://[2001:DB8::1]:8443/v1",
  "https://[::ffff:192.0.2.1]/v1",
  "HTTP://Example.COM.:00080/%not-an-escape",
  "http://127.0.0.1/v1",
  "https://example.test/" + "🧪".repeat(491),
];
const rejectedURLs = [
  "http://1.2.3/v1",
  "http://0127.0.0.1/v1",
  "http://127.0.0.1./v1",
  "http://123/v1",
  "https://xn--invalid-.example/v1",
  "https://a:0/v1",
  "https://a:65536/v1",
  "https://a:/v1",
  "https://a:1:2/v1",
  "https://@a/v1",
  "https://u:p@a/v1",
  "https://%61.example/v1",
  "https://a/v1?",
  "https://a/v1#",
  "https://a\\b/v1",
  "https:///v1",
  "https://[::1]suffix/v1",
  "https://[1.2.3.4]/v1",
  "https://[::1%25zone]/v1",
  "https://[::ffff:0127.0.0.1]/v1",
  "https://[1:2:3:4:5:6:7]/v1",
  "https://a\u200b.example/v1",
  "https://a/v\u200b1",
  "https://a\uff0fb/v1",
  "https://example.test/" + "🧪".repeat(492),
];
it("matches real producer URL syntax, not navigation-host reinterpretation", () => {
  const urls = [...acceptedURLs, ...rejectedURLs];
  const cases = urls.map((base_url) => input({ base_url }));
  const replies = producer(cases);
  expect(replies.map((r) => r.status)).toEqual([
    ...acceptedURLs.map(() => 200),
    ...rejectedURLs.map(() => 422),
  ]);
  const mismatches: string[] = [];
  for (const [i, url] of urls.entries()) {
    const accepted = replies[i].status === 200;
    if (validBaseURL(url) !== accepted) mismatches.push(url);
    if (accepted && validBaseURL(url)) {
      const actual = parseSettingsSnapshot(JSON.parse(replies[i].body));
      expect(actual.profiles).toEqual(cases[i].profiles);
      expect(parseSettingsSnapshot(JSON.parse(replies[i].get))).toEqual(actual);
      expect(() => assertSettingsInput(cases[i])).not.toThrow();
    }
  }
  expect(mismatches).toEqual([]);
});

it("keeps Python casefold uniqueness, literal text boundaries and the 20-profile cap", () => {
  const pairs: [string, string, boolean][] = [
    ["Case \u1c89", "Case \u1c8a", true],
    ["Case \ua7cb", "Case \u0264", true],
    ["ß", "ss", false],
    ["Σ", "ς", false],
    ["K", "k", false],
    ["\u13a0", "\uab70", false],
    ["ﬃ", "ffi", false],
    ["İ", "i\u0307", false],
    ["é", "e\u0301", true],
    ["Ａ", "A", true],
  ];
  const cases = pairs.map(([a, b]) => ({
    ...input({}),
    profiles: [profile({ id: "a", name: a }), profile({ id: "b", name: b })],
  }));
  const expected = pairs.map(([, , accepted]) => accepted);
  for (const n of [120, 121]) {
    cases.push(input({ name: "🧪".repeat(n) }));
    expected.push(n === 120);
  }
  for (const n of [200, 201]) {
    cases.push(input({ model: "🧪".repeat(n) }));
    expected.push(n === 200);
  }
  for (const n of [20, 21]) {
    cases.push({
      ...input({}),
      profiles: Array.from({ length: n }, (_, i) =>
        profile({ id: `p-${i}`, name: `Profile ${i}` }),
      ),
    });
    expected.push(n === 20);
  }
  for (const space of [
    "\u0085",
    "\u00a0",
    "\u2003",
    "\u2028",
    "\u2029",
    "\u3000",
  ]) {
    for (const [name, accepted] of [
      [`x${space}y`, space !== "\u0085"],
      [`${space}x`, false],
      [`x${space}`, false],
    ] as const) {
      cases.push(input({ name }));
      expected.push(accepted);
    }
  }
  const replies = producer(cases);
  for (const [i, value] of cases.entries()) {
    expect(replies[i].status, JSON.stringify(value)).toBe(
      expected[i] ? 200 : 422,
    );
    if (expected[i]) {
      expect(() => assertSettingsInput(value)).not.toThrow();
      const actual = parseSettingsSnapshot(JSON.parse(replies[i].body));
      expect(actual.profiles).toEqual(value.profiles);
      for (const p of actual.profiles)
        expect(profileIssue(p, actual.profiles)).toBeNull();
    } else {
      expect(() => assertSettingsInput(value)).toThrow();
    }
  }
});

it("rejects producer-forbidden Cf text in names/models and URLs", () => {
  const cases = ["name", "model", "base_url"].flatMap((field) =>
    ["\u00ad", "\u200b", "\u202e", "\ufeff", "\u{13439}"].map((c) =>
      input({ [field]: field === "base_url" ? `https://a/v${c}1` : `x${c}y` }),
    ),
  );
  expect(producer(cases).map((r) => r.status)).toEqual(cases.map(() => 422));
  for (const value of cases) {
    expect(profileIssue(value.profiles[0])).not.toBeNull();
    expect(() => assertSettingsInput(value)).toThrow();
  }
});
