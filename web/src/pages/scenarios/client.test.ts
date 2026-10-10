import { afterEach, expect, it, vi } from "vitest";
import { recordFixture } from "./testRecords";
import type { Submission } from "./types";
import { scenarioAPI as api } from "./client";
const reply = (v: unknown, status = 200) =>
  new Response(JSON.stringify(v), {
    status,
    headers: { "Content-Type": "application/json" },
  });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("reads closed bounded pages with no redirect/cache and same-origin credentials", async () => {
  const page = {
    revision: 0,
    total: 0,
    offset: 0,
    limit: 50,
    items: [],
    execution_enabled: false,
  };
  const fetcher = vi.fn().mockResolvedValue(reply(page));
  vi.stubGlobal("fetch", fetcher);
  expect(await api.read()).toEqual(page);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/scenarios?offset=0&limit=50",
    expect.objectContaining({
      method: "GET",
      redirect: "error",
      credentials: "same-origin",
      cache: "no-store",
    }),
  );
});
it("binds mutation to captured literals, opened identity/version and CAS revision", async () => {
  const scenario = await recordFixture();
  const receipt = { revision: 1, scenario, execution_enabled: false };
  const fetcher = vi.fn().mockResolvedValue(reply(receipt, 201));
  vi.stubGlobal("fetch", fetcher);
  const input: Submission = {
    revision: 0,
    definition: scenario.definition,
    opened: null,
  };
  const pending = api.save(input);
  input.definition.name = "changed after send";
  const result = await pending;
  expect(result?.scenario.definition.name).toBe(" Policy 🧪 ");
  expect(JSON.parse(fetcher.mock.calls[0][1].body).definition.name).toBe(
    " Policy 🧪 ",
  );
  for (const [record, revision, status, opened] of [
    [
      await recordFixture(1, {
        definition: { ...scenario.definition, name: "wrong" },
      }),
      1,
      201,
      null,
    ],
    [await recordFixture(2), 1, 201, null],
    [await recordFixture(), 2, 201, null],
    [await recordFixture(1), 2, 200, { id: scenario.id, version: 1 }],
    [
      await recordFixture(2, { id: "22222222-2222-4222-8222-222222222222" }),
      2,
      200,
      { id: scenario.id, version: 1 },
    ],
  ] as const) {
    fetcher.mockResolvedValueOnce(
      reply({ revision, scenario: record, execution_enabled: false }, status),
    );
    await expect(
      api.save({
        revision: opened ? 1 : 0,
        definition: (await recordFixture()).definition,
        opened,
      }),
    ).rejects.toThrow();
  }
});
it("acknowledges identical record in history even when a newer revision is latest", async () => {
  const one = await recordFixture(),
    two = await recordFixture(2, {
      definition: { ...(await recordFixture()).definition, name: "newer" },
    });
  const history = {
    revision: 2,
    scenario_id: one.id,
    versions: [one, two],
    execution_enabled: false,
  };
  const fetcher = vi.fn().mockResolvedValue(reply(history));
  vi.stubGlobal("fetch", fetcher);
  expect(
    await api.verify({ revision: 1, scenario: one, execution_enabled: false }),
  ).toEqual(history);
  expect(
    fetcher.mock.calls.every(([, options]) => options.method === "GET"),
  ).toBe(true);
  fetcher.mockResolvedValue(
    reply({
      ...history,
      versions: [
        await recordFixture(1, {
          definition: { ...one.definition, name: "different" },
        }),
      ],
    }),
  );
  await expect(
    api.verify({ revision: 1, scenario: one, execution_enabled: false }),
  ).rejects.toThrow();
});
it("enforces byte, UTF-8, raw token, status and pagination boundaries", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  for (const response of [
    new Response(" ".repeat(1048577)),
    new Response(new Uint8Array([0xc0, 0xaf])),
    new Response('{"revision":0,"revision":0}'),
    new Response('{"revision":0.0}'),
    reply({}, 302),
    reply({ code: "UNKNOWN", message: "<raw error>" }, 503),
    new Response("{}", { headers: { "Content-Length": "1048577" } }),
  ]) {
    fetcher.mockResolvedValueOnce(response);
    await expect(api.read()).rejects.toThrow();
  }
  const before = fetcher.mock.calls.length;
  for (const offset of [-1, 101, 1.5, NaN])
    await expect(api.read(offset)).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(before);
});
it("deadline settles ignored abort, stalled body and external cancellation without replay", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const promise = api.read();
  const assertion = expect(promise).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(10001);
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockResolvedValue(
    new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(new TextEncoder().encode("{"));
        },
      }),
    ),
  );
  const stalled = api.read();
  const check = expect(stalled).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(10001);
  await check;
  fetcher.mockImplementation(() => new Promise(() => {}));
  const controller = new AbortController();
  const aborted = api.read(0, 50, controller.signal);
  const canceled = expect(aborted).rejects.toThrow();
  controller.abort();
  await canceled;
});
