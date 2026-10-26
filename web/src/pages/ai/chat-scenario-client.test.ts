import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { scenarioAPI } from "../scenarios/client";

// Actual Python-model bytes, not HTTP/backend integration captures.
const candidate = resolve(import.meta.dirname, "../../../..");
const corpus: { bodies: Record<string, string> } = JSON.parse(
  execFileSync(
    resolve(candidate, ".venv/bin/python"),
    ["-m", "tests.chat.scenario_model_wire"],
    {
      cwd: candidate,
      env: {
        ...process.env,
        PYTHONPATH: `${candidate}/src:${candidate}`,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONNOUSERSITE: "1",
      },
      encoding: "utf8",
      timeout: 30000,
    },
  ),
);
async function client() {
  const files = import.meta.glob("./chat-scenario-client.ts");
  expect(
    Object.keys(files),
    "fixed P-owned read wrappers must exist",
  ).toHaveLength(1);
  return (await files[
    "./chat-scenario-client.ts"
  ]()) as typeof import("./chat-scenario-client");
}
function response(body: string) {
  return new Response(body, {
    headers: { "content-type": "application/json" },
  });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each([
  "UPPER",
  "../scenario",
  "a/b",
  "x?offset=2",
  "x#fragment",
  " padded ",
  "",
  "a".repeat(65),
  "한글",
])("literal Identifier %s is refused before any fetch", async (id) => {
  const { chatScenarioClient } = await client(),
    fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await expect(chatScenarioClient.history(id)).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  [-1, 50],
  [101, 50],
  [0, 0],
  [0, 101],
  [1.5, 50],
])(
  "fixed paging rejects offset %i limit %i before fetch",
  async (offset, limit) => {
    const { chatScenarioClient } = await client(),
      fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(chatScenarioClient.read(offset, limit)).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it.each([
  ["ScenarioHistoryV4", 262144],
  ["ScenarioPageV4", 1048576],
] as const)(
  "wrapper %s preserves exact/+1 raw byte cap and UTF8 count",
  async (name, cap) => {
    const { chatScenarioClient } = await client(),
      body = corpus.bodies[name];
    const exact =
      body + " ".repeat(cap - new TextEncoder().encode(body).length);
    const fetcher = vi.fn(async () => response(exact));
    vi.stubGlobal("fetch", fetcher);
    const read = () =>
      name === "ScenarioHistoryV4"
        ? chatScenarioClient.history("legacy-scenario")
        : chatScenarioClient.read();
    expect(await read()).toEqual(JSON.parse(body));
    fetcher.mockImplementation(async () => response(exact + " "));
    await expect(read()).rejects.toThrow();
    // The model output includes Korean/emoji: character count is not the raw byte count.
    expect(new TextEncoder().encode(body).length).toBeGreaterThan(body.length);
  },
);
it.each([
  "duplicate",
  "alias",
  "float",
  "depth33",
  "wrong-id",
  "unselected-version",
  "wrong-digest",
])(
  "history wrapper rejects %s without retry or latest fallback",
  async (kind) => {
    const { chatScenarioClient } = await client();
    let body = corpus.bodies.ScenarioHistoryV4;
    if (kind === "duplicate")
      body = body.replace('"revision":2', '"revision":2,"revision":2');
    if (kind === "alias")
      body = body.replace('"revision":2', '"revision":2,"rev\\u0069sion":2');
    if (kind === "float") body = body.replace('"revision":2', '"revision":2.0');
    if (kind === "depth33") body = "[".repeat(33) + "0" + "]".repeat(33);
    if (kind === "wrong-id")
      body = body.replace(
        '"scenario_id":"legacy-scenario"',
        '"scenario_id":"other"',
      );
    if (kind === "unselected-version" || kind === "wrong-digest") {
      const v = JSON.parse(body);
      if (kind === "unselected-version")
        v.versions[1].definition.name = "tampered unselected newer version";
      else v.versions[0].digest = "f".repeat(64);
      body = JSON.stringify(v);
    }
    const fetcher = vi.fn(async () => response(body));
    vi.stubGlobal("fetch", fetcher);
    await expect(
      chatScenarioClient.history("legacy-scenario"),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);
it("history preserves explicit older version instead of selecting latest", async () => {
  const { chatScenarioClient } = await client();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(corpus.bodies.ScenarioHistoryV4)),
  );
  const history = await chatScenarioClient.history("legacy-scenario");
  expect(history.versions.map((r) => r.version)).toEqual([1, 2]);
  expect(history.versions.find((r) => r.version === 1)).toEqual(
    JSON.parse(corpus.bodies.ScenarioVersion),
  );
});
it("unavailable history never fetches workspace, grant, latest, or another page", async () => {
  const { chatScenarioClient } = await client();
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          code: "SCENARIO_STATE_UNAVAILABLE",
          message: "unavailable",
        }),
        { status: 503, headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(
    chatScenarioClient.history("legacy-scenario"),
  ).rejects.toMatchObject({ code: "SCENARIO_STATE_UNAVAILABLE" });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("fixed history accepts literal legacy Identifier and preserves old manual UUID rejection", async () => {
  const { chatScenarioClient } = await client();
  const fetcher = vi.fn(async () => response(corpus.bodies.ScenarioHistoryV4));
  vi.stubGlobal("fetch", fetcher);
  expect(await chatScenarioClient.history("legacy-scenario")).toEqual(
    JSON.parse(corpus.bodies.ScenarioHistoryV4),
  );
  expect(fetcher.mock.calls).toHaveLength(1);
  expect(fetcher.mock.calls[0]).toEqual([
    "/api/v1/scenarios/legacy-scenario",
    expect.objectContaining({
      method: "GET",
      redirect: "error",
      cache: "no-store",
      credentials: "same-origin",
    }),
  ]);
  await expect(scenarioAPI.history("legacy-scenario")).rejects.toThrow();
});
it("fixed page uses exact selectors/defaults with no history or metadata fanout", async () => {
  const { chatScenarioClient } = await client();
  const fetcher = vi.fn(async () => response(corpus.bodies.ScenarioPageV4));
  vi.stubGlobal("fetch", fetcher);
  expect(await chatScenarioClient.read()).toEqual(
    JSON.parse(corpus.bodies.ScenarioPageV4),
  );
  expect(fetcher.mock.calls).toEqual([
    [
      "/api/v1/scenarios?offset=0&limit=50",
      expect.objectContaining({ method: "GET" }),
    ],
  ]);
});
