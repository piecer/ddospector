import { afterEach, describe, expect, it, vi } from "vitest";
import { recordFixture } from "./testRecords";
import type { Submission } from "./types";
import { scenarioAPI as api } from "./client";
import * as client from "./client";
import { digest } from "./json";
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

type HistoryRead = <T>(
  id: string,
  parse: (value: unknown, id: string) => Promise<T>,
  signal?: AbortSignal,
) => Promise<T>;
function historyBridge(): HistoryRead {
  const bridge = Reflect.get(client, "readScenarioHistoryWith");
  expect(bridge, "readScenarioHistoryWith export").toBeTypeOf("function");
  return bridge as HistoryRead;
}

it("history bridge reads the fixed encoded literal Identifier through the trusted parser", async () => {
  const read = historyBridge();
  const value = { payload: "decoded 🧪" };
  const result = Object.freeze({ parsed: true });
  const parse = vi.fn(async () => result);
  const fetcher = vi.fn().mockImplementation(async () => reply(value));
  vi.stubGlobal("fetch", fetcher);
  for (const id of ["legacy-scenario", "a", "-", "z".repeat(64)]) {
    expect(await read(id, parse)).toBe(result);
    expect(parse).toHaveBeenLastCalledWith(value, id);
    expect(fetcher).toHaveBeenLastCalledWith(
      "/api/v1/scenarios/" + encodeURIComponent(id),
      {
        method: "GET",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        signal: expect.any(AbortSignal),
        headers: { Accept: "application/json" },
      },
    );
  }
  expect(fetcher).toHaveBeenCalledTimes(4);
});

it("history bridge rejects invalid literal identifiers before fetch or parsing", async () => {
  const read = historyBridge();
  const fetcher = vi.fn().mockImplementation(async () => reply({}));
  const parse = vi.fn(async () => true);
  vi.stubGlobal("fetch", fetcher);
  for (const id of [
    "",
    "a".repeat(65),
    "Legacy-scenario",
    " legacy",
    "legacy ",
    "a/b",
    "../a",
    "a?offset=0",
    "a#fragment",
    "a%2fb",
    "https://example.test",
    "한글",
    "a\n",
    "a\u0000",
    null,
    1,
    {},
  ]) {
    await expect(read(id as string, parse)).rejects.toThrow(
      "Invalid scenario response.",
    );
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect(parse).not.toHaveBeenCalled();
});

type PageRead = <T>(
  offset: number,
  limit: number,
  parse: (value: unknown, offset: number, limit: number) => Promise<T>,
  signal?: AbortSignal,
) => Promise<T>;
function pageBridge(): PageRead {
  const bridge = Reflect.get(client, "readScenarioPageWith");
  expect(bridge, "readScenarioPageWith export").toBeTypeOf("function");
  return bridge as PageRead;
}

it("page bridge reads fixed bounds with the captured offset and limit", async () => {
  const read = pageBridge();
  const value = { payload: [1, 2] };
  const parse = vi.fn(async () => "parsed page");
  const fetcher = vi.fn().mockImplementation(async () => reply(value));
  vi.stubGlobal("fetch", fetcher);
  for (const [offset, limit] of [
    [0, 1],
    [99, 10],
    [100, 100],
  ]) {
    expect(await read(offset, limit, parse)).toBe("parsed page");
    expect(parse).toHaveBeenLastCalledWith(value, offset, limit);
    expect(fetcher).toHaveBeenLastCalledWith(
      `/api/v1/scenarios?offset=${offset}&limit=${limit}`,
      {
        method: "GET",
        credentials: "same-origin",
        redirect: "error",
        cache: "no-store",
        signal: expect.any(AbortSignal),
        headers: { Accept: "application/json" },
      },
    );
  }
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("page bridge refuses noninteger or out-of-bounds selectors without defaults or fetch", async () => {
  const read = pageBridge();
  const fetcher = vi.fn().mockImplementation(async () => reply({}));
  const parse = vi.fn(async () => true);
  vi.stubGlobal("fetch", fetcher);
  for (const offset of [
    -1,
    101,
    0.5,
    NaN,
    Infinity,
    "0",
    true,
    null,
    undefined,
  ]) {
    await expect(read(offset as number, 50, parse)).rejects.toThrow(
      "Invalid scenario response.",
    );
  }
  for (const limit of [
    0,
    -1,
    101,
    1.5,
    NaN,
    Infinity,
    "50",
    true,
    null,
    undefined,
  ]) {
    await expect(read(0, limit as number, parse)).rejects.toThrow(
      "Invalid scenario response.",
    );
  }
  expect(fetcher).not.toHaveBeenCalled();
  expect(parse).not.toHaveBeenCalled();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it("bridges retain selector values while fetch is pending", async () => {
  const historyResponse = deferred<Response>();
  const pageResponse = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockReturnValueOnce(historyResponse.promise)
    .mockReturnValueOnce(pageResponse.promise);
  vi.stubGlobal("fetch", fetcher);
  let id = "legacy-scenario",
    offset = 99,
    limit = 1;
  const historyParse = vi.fn(async () => "history");
  const pageParse = vi.fn(async () => "page");
  const history = historyBridge()(id, historyParse);
  const page = pageBridge()(offset, limit, pageParse);
  id = "changed";
  offset = 0;
  limit = 100;
  expect([id, offset, limit]).toEqual(["changed", 0, 100]);
  historyResponse.resolve(reply({ source: "history" }));
  pageResponse.resolve(reply({ source: "page" }));
  expect(await history).toBe("history");
  expect(await page).toBe("page");
  expect(historyParse).toHaveBeenCalledExactlyOnceWith(
    { source: "history" },
    "legacy-scenario",
  );
  expect(pageParse).toHaveBeenCalledExactlyOnceWith({ source: "page" }, 99, 1);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

// These characterize the inherited private transport through both new public
// entrypoints. No mock replaces request, raw decoding, or parser awaiting.
const bridges = [
  {
    name: "history",
    max: 262144,
    read: (parse: (value: unknown) => Promise<unknown>, signal?: AbortSignal) =>
      client.readScenarioHistoryWith("legacy-scenario", parse, signal),
  },
  {
    name: "page",
    max: 1048576,
    read: (parse: (value: unknown) => Promise<unknown>, signal?: AbortSignal) =>
      client.readScenarioPageWith(0, 50, parse, signal),
  },
];

describe.each(bridges)("$name bridge inherited transport", ({ read, max }) => {
  it("admits exactly the UTF-8 byte cap and refuses one extra streamed byte", async () => {
    const prefix = '"🧪"';
    const atCap = new TextEncoder().encode(
      prefix + " ".repeat(max - new TextEncoder().encode(prefix).length),
    );
    expect(atCap.byteLength).toBe(max);
    const fetcher = vi.fn();
    const parse = vi.fn(async (value: unknown) => value);
    vi.stubGlobal("fetch", fetcher);
    const streamed = (bytes: Uint8Array) =>
      new Response(
        new ReadableStream({
          start(controller) {
            // Split a multibyte codepoint across chunks, exercising streaming UTF-8.
            controller.enqueue(bytes.slice(0, 3));
            controller.enqueue(bytes.slice(3));
            controller.close();
          },
        }),
      );
    fetcher.mockResolvedValueOnce(streamed(atCap));
    expect(await read(parse)).toBe("🧪");
    const overCap = new Uint8Array(max + 1);
    overCap.set(atCap);
    overCap[max] = 32;
    fetcher.mockResolvedValueOnce(streamed(overCap));
    await expect(read(parse)).rejects.toThrow("Invalid scenario response.");
    expect(parse).toHaveBeenCalledExactlyOnceWith(
      "🧪",
      ...(max === 262144 ? ["legacy-scenario"] : [0, 50]),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("enforces Content-Length before parsing while retaining the exact cap", async () => {
    const fetcher = vi.fn();
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    fetcher.mockResolvedValueOnce(
      new Response("{}", { headers: { "Content-Length": String(max) } }),
    );
    expect(await read(parse)).toBe(true);
    for (const length of [String(max + 1), "-1", "1.0", "invalid"]) {
      fetcher.mockResolvedValueOnce(
        new Response("{}", { headers: { "Content-Length": length } }),
      );
      await expect(read(parse)).rejects.toThrow("Invalid scenario response.");
    }
    expect(parse).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it("rejects malformed raw bytes before the trusted parser", async () => {
    const fetcher = vi.fn();
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    for (const body of [
      new Uint8Array([0xc0, 0xaf]),
      '{"x":1,"x":2}',
      '{"x":1,"\\u0078":2}',
      '{"x":1.0}',
      '{"x":1e0}',
      "[".repeat(33) + "0" + "]".repeat(33),
      "{} trailing",
    ]) {
      fetcher.mockResolvedValueOnce(new Response(body));
      await expect(read(parse)).rejects.toThrow();
    }
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(7);
  });

  it("preserves fixed error codes without exposing server text or retrying", async () => {
    const fetcher = vi.fn();
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const errors = [
      ["SCENARIO_CONFLICT", 409],
      ["SCENARIO_NOT_FOUND", 404],
      ["SCENARIO_LIMIT_REACHED", 409],
      ["SCENARIO_STATE_CORRUPT", 503],
      ["SCENARIO_STATE_UNAVAILABLE", 503],
      ["SCENARIO_COMMIT_UNCERTAIN", 503],
      ["STATE_CORRUPT", 503],
      ["STATE_UNAVAILABLE", 503],
      ["INVALID_REFERENCE", 422],
      ["VALIDATION_ERROR", 422],
    ] as const;
    for (const [code, status] of errors) {
      fetcher.mockResolvedValueOnce(
        reply({ code, message: "private server detail" }, status),
      );
      await expect(read(parse)).rejects.toMatchObject({
        code,
        message: "Scenario request failed.",
      });
    }
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(errors.length);
    expect(
      fetcher.mock.calls.every(
        ([, options]) => options.method === "GET" && !("body" in options),
      ),
    ).toBe(true);
  });

  it("refuses redirects and unrecognized status envelopes before parsing", async () => {
    const fetcher = vi.fn();
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const redirected = reply({});
    Object.defineProperty(redirected, "redirected", { value: true });
    const responses = [
      redirected,
      reply({}, 302),
      reply({}, 201),
      reply({ code: "UNKNOWN", message: "private" }, 503),
      reply({ code: "SCENARIO_CONFLICT", message: "private" }, 503),
      reply(
        { code: "SCENARIO_CONFLICT", message: "private", extra: true },
        409,
      ),
    ];
    for (const response of responses) {
      fetcher.mockResolvedValueOnce(response);
      await expect(read(parse)).rejects.toThrow("Invalid scenario response.");
    }
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(responses.length);
  });

  it("propagates fetch and async parser errors without replay or writes", async () => {
    const fetcher = vi.fn();
    const parse = vi.fn(async () => {
      throw new Error("codec refused");
    });
    vi.stubGlobal("fetch", fetcher);
    const networkError = new TypeError("fetch refused");
    fetcher.mockRejectedValueOnce(networkError);
    await expect(read(parse)).rejects.toBe(networkError);
    expect(parse).not.toHaveBeenCalled();
    fetcher.mockResolvedValueOnce(reply({}));
    await expect(read(parse)).rejects.toThrow("codec refused");
    expect(parse).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("uses native pre-dispatch and in-flight AbortSignal reasons", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    controller.abort();
    await expect(read(parse, controller.signal)).rejects.toBe(
      controller.signal.reason,
    );
    expect(fetcher).not.toHaveBeenCalled();
    const live = new AbortController();
    const pending = read(parse, live.signal);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    const transportSignal = fetcher.mock.calls[0][1].signal as AbortSignal;
    live.abort();
    await assertion;
    expect(transportSignal.aborted).toBe(true);
    expect(transportSignal.reason).toBe(live.signal.reason);
    expect(vi.getTimerCount()).toBe(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(parse).not.toHaveBeenCalled();
  });

  it("cancels a pending streamed read and releases its reader on native abort", async () => {
    const entered = deferred<void>();
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.enqueue(new TextEncoder().encode("{"));
        entered.resolve();
        return new Promise<void>(() => {});
      },
      cancel,
    });
    const fetcher = vi.fn().mockResolvedValue(new Response(body));
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const pending = read(parse, controller.signal);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    await entered.promise;
    // Let request acquire the body reader before the operator abort.
    await Promise.resolve();
    controller.abort();
    await assertion;
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(body.locked).toBe(false);
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("discards a parser that finishes after external cancellation", async () => {
    vi.useFakeTimers();
    const entered = deferred<void>();
    const finish = deferred<string>();
    const parse = vi.fn(async () => {
      entered.resolve();
      return finish.promise;
    });
    const fetcher = vi.fn().mockResolvedValue(reply({}));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const delivered = vi.fn();
    const pending = read(parse, controller.signal).then(delivered);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    await entered.promise;
    controller.abort();
    await assertion;
    finish.resolve("late result");
    await vi.advanceTimersByTimeAsync(1);
    expect(delivered).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(parse).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("keeps one original 10000ms deadline across fetch and late async parsing", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>();
    const entered = deferred<void>();
    const finish = deferred<string>();
    const parse = vi.fn(async () => {
      entered.resolve();
      return finish.promise;
    });
    const fetcher = vi.fn().mockReturnValue(response.promise);
    vi.stubGlobal("fetch", fetcher);
    const delivered = vi.fn();
    const pending = read(parse).then(delivered);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "TimeoutError",
    });
    await vi.advanceTimersByTimeAsync(9000);
    response.resolve(reply({}));
    await entered.promise;
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    finish.resolve("late digest result");
    await vi.advanceTimersByTimeAsync(1);
    expect(delivered).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(parse).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("accepts async parsing completed before the original deadline", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>();
    const entered = deferred<void>();
    const finish = deferred<string>();
    const fetcher = vi.fn().mockReturnValue(response.promise);
    vi.stubGlobal("fetch", fetcher);
    const pending = read(async () => {
      entered.resolve();
      return finish.promise;
    });
    await vi.advanceTimersByTimeAsync(9000);
    response.resolve(reply({}));
    await entered.promise;
    await vi.advanceTimersByTimeAsync(999);
    finish.resolve("on-time digest result");
    expect(await pending).toBe("on-time digest result");
    expect(vi.getTimerCount()).toBe(0);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false);
  });

  it("checks monotonic expiry after parsing even before the timer callback runs", async () => {
    const clock = vi.spyOn(performance, "now").mockReturnValue(0);
    const fetcher = vi.fn().mockResolvedValue(reply({}));
    vi.stubGlobal("fetch", fetcher);
    try {
      await expect(
        read(async () => {
          clock.mockReturnValue(10000);
          return "late digest result";
        }),
      ).rejects.toMatchObject({ name: "TimeoutError" });
      expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    } finally {
      clock.mockRestore();
    }
  });

  it("includes actual digest completion within the original deadline", async () => {
    const expected = await digest({ payload: "literal" });
    vi.useFakeTimers();
    const fetcher = vi
      .fn()
      .mockImplementation(async () => reply({ payload: "literal" }));
    vi.stubGlobal("fetch", fetcher);
    for (const late of [false, true]) {
      const entered = deferred<void>();
      const finish = deferred<void>();
      const digested = deferred<void>();
      const delivered = vi.fn();
      const pending = read(async (value) => {
        entered.resolve();
        await finish.promise;
        const result = await digest(value);
        digested.resolve();
        return result;
      }).then((result) => {
        delivered(result);
        return result;
      });
      const assertion = late
        ? expect(pending).rejects.toMatchObject({ name: "TimeoutError" })
        : expect(pending).resolves.toBe(expected);
      await entered.promise;
      if (late) await vi.advanceTimersByTimeAsync(10000);
      finish.resolve();
      await digested.promise;
      await assertion;
      await vi.advanceTimersByTimeAsync(0);
      expect(delivered).toHaveBeenCalledTimes(late ? 0 : 1);
      expect(vi.getTimerCount()).toBe(0);
    }
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("times out a stalled body on the same fetch deadline and cancels its reader", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>();
    const fetcher = vi.fn().mockReturnValue(response.promise);
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const pending = read(parse);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "TimeoutError",
    });
    await vi.advanceTimersByTimeAsync(9000);
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("{"));
      },
      cancel,
    });
    response.resolve(new Response(body));
    await vi.advanceTimersByTimeAsync(999);
    expect(body.locked).toBe(true);
    expect(cancel).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await assertion;
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(body.locked).toBe(false);
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels a late response body after fetch ignored the deadline", async () => {
    vi.useFakeTimers();
    const response = deferred<Response>();
    const fetcher = vi.fn().mockReturnValue(response.promise);
    const parse = vi.fn(async () => true);
    vi.stubGlobal("fetch", fetcher);
    const pending = read(parse);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "TimeoutError",
    });
    await vi.advanceTimersByTimeAsync(10000);
    await assertion;
    const cancel = vi.fn();
    response.resolve(new Response(new ReadableStream({ cancel })));
    await vi.advanceTimersByTimeAsync(1);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(parse).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

it("manual history and page keep their UUID-only record codec", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  for (const id of [
    "11111111-1111-4111-8111-111111111111",
    "legacy-scenario",
  ]) {
    const record = await recordFixture(1, { id });
    const history = {
      revision: 1,
      scenario_id: id,
      versions: [record],
      execution_enabled: false,
    };
    const page = {
      revision: 1,
      total: 1,
      offset: 0,
      limit: 50,
      items: [record],
      execution_enabled: false,
    };
    fetcher.mockResolvedValueOnce(reply(history));
    if (id === "legacy-scenario")
      await expect(api.history(id)).rejects.toThrow();
    else expect(await api.history(id)).toEqual(history);
    fetcher.mockResolvedValueOnce(reply(page));
    if (id === "legacy-scenario") await expect(api.read()).rejects.toThrow();
    else expect(await api.read()).toEqual(page);
  }
  expect(fetcher).toHaveBeenCalledTimes(4);
});
