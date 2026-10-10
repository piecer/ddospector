import { afterEach, expect, it, vi } from "vitest";
import { recordFixture } from "./testRecords";
import { canonical, utf8Length } from "./json";
import { scenarioAPI } from "./client";
import { parseVersion, parsePage } from "./wire";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("admits exactly 8192 record bytes and rejects limit+1 using literal UTF-8", async () => {
  const base = await recordFixture();
  base.definition.objective = "";
  const room = 8192 - utf8Length(canonical(base));
  const text = "🧪".repeat(Math.floor(room / 4)) + "a".repeat(room % 4);
  const exact = await recordFixture(1, {
    definition: { ...base.definition, objective: text },
  });
  expect(utf8Length(canonical(exact))).toBe(8192);
  expect(await parseVersion(exact)).toEqual(exact);
  const over = await recordFixture(1, {
    definition: { ...base.definition, objective: text + "a" },
  });
  expect(utf8Length(canonical(over))).toBe(8193);
  await expect(parseVersion(over)).rejects.toThrow();
});
it("counts actual streamed bytes at page/history/mutation limits, including no Content-Length", async () => {
  const one = await recordFixture();
  const page = {
    revision: 0,
    total: 0,
    offset: 0,
    limit: 50,
    items: [],
    execution_enabled: false,
  };
  const history = {
    revision: 1,
    scenario_id: one.id,
    versions: [one],
    execution_enabled: false,
  };
  const receipt = { revision: 1, scenario: one, execution_enabled: false };
  const body = (v: unknown, budget: number) => {
    const text = JSON.stringify(v);
    return text + " ".repeat(budget - utf8Length(text));
  };
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  for (const [value, max, status, run] of [
    [page, 1048576, 200, () => scenarioAPI.read()],
    [history, 262144, 200, () => scenarioAPI.history(one.id)],
    [
      receipt,
      262144,
      201,
      () =>
        scenarioAPI.save({
          revision: 0,
          definition: one.definition,
          opened: null,
        }),
    ],
  ] as const) {
    fetcher.mockResolvedValueOnce(new Response(body(value, max), { status }));
    expect(await run()).toEqual(value);
    fetcher.mockResolvedValueOnce(
      new Response(body(value, max + 1), { status }),
    );
    await expect(run()).rejects.toThrow();
  }
});
it("includes delayed semantic digest verification in the 10 second deadline", async () => {
  const one = await recordFixture();
  vi.useFakeTimers();
  vi.spyOn(crypto.subtle, "digest").mockImplementation(
    () => new Promise(() => {}),
  );
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            revision: 1,
            total: 1,
            offset: 0,
            limit: 50,
            items: [one],
            execution_enabled: false,
          }),
        ),
      ),
  );
  const request = scenarioAPI.read();
  const denied = expect(request).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(10001);
  await denied;
});
it("rejects unencodable timestamp surrogates despite a forged JavaScript digest", async () => {
  const record = await recordFixture(1, {
    created_at: "2026-10-09\ud80012:34:56+00:00",
  });
  await expect(parseVersion(record)).rejects.toThrow();
});
it("rejects invalid numeric pagination even at the direct parser boundary", async () => {
  for (const [offset, limit] of [
    [-1, 50],
    [101, 50],
    [0, 0],
    [0, 101],
  ])
    await expect(
      parsePage(
        {
          revision: 0,
          total: 0,
          offset,
          limit,
          items: [],
          execution_enabled: false,
        },
        offset,
        limit,
      ),
    ).rejects.toThrow();
});
