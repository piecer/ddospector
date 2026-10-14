import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import {
  bounded,
  evidenceAPI,
  hashBytes,
  prepareFiles,
  loadSample,
} from "./client";
const bytes = (name: string) =>
  new Uint8Array(readFileSync(`../tests/fixtures/evidence/${name}`));
beforeAll(() =>
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  }),
);
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("refuses malformed direct upload objects before fetch and never executes accessors", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  const good = {
    request_id: "4db4f744-286a-4fa1-b1ef-d6be167a1836",
    run_id: "65d2c686-b87a-4369-9c19-492a974ae7a6",
    ingress: { name: "x", base64: "AA==" },
    egress: { name: "y", base64: "AA==" },
  };
  for (const bad of [
    { ...good, extra: 1 },
    { ...good, ingress: { name: "x", base64: "AB==" } },
    { ...good, ingress: { name: "x", base64: btoa("x".repeat(65537)) } },
  ])
    await expect(evidenceAPI.post(bad)).rejects.toThrow();
  let called = 0;
  Object.defineProperty(good, "ingress", {
    get() {
      called++;
      return { name: "x", base64: "AA==" };
    },
  });
  await expect(evidenceAPI.post(good)).rejects.toThrow();
  expect(called).toBe(0);
  expect(fetcher).not.toHaveBeenCalled();
});
function controlledResponse(
  headers: HeadersInit = {},
  enqueue?: (c: ReadableStreamDefaultController<Uint8Array>) => void,
) {
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ start: enqueue, cancel });
  const acquire = stream.getReader.bind(stream);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  vi.spyOn(stream, "getReader").mockImplementation(() => {
    reader = acquire();
    vi.spyOn(reader, "cancel");
    vi.spyOn(reader, "releaseLock");
    return reader;
  });
  const response = new Response(stream, { headers });
  let signal!: AbortSignal;
  const abort = vi.fn();
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (_url, init) => {
      signal = init!.signal!;
      signal.addEventListener("abort", abort);
      return response;
    });
  return {
    stream,
    response,
    cancel,
    abort,
    fetcher,
    reader: () => reader,
    signal: () => signal,
  };
}

it.each(["encoded", "redirected", "missing-body", "reader-error"] as const)(
  "retires acquired response on %s admission failure without masking the original error",
  async (kind) => {
    vi.useFakeTimers();
    const cancel = vi.fn(() => new Promise<void>(() => {}));
    const stream = new ReadableStream<Uint8Array>({ cancel });
    const response = new Response(
      kind === "missing-body" ? null : stream,
      kind === "encoded" ? { headers: { "Content-Encoding": "gzip" } } : {},
    );
    if (kind === "redirected")
      Object.defineProperty(response, "redirected", { value: true });
    const primary = new Error("reader acquisition failed");
    if (kind === "reader-error")
      vi.spyOn(stream, "getReader").mockImplementation(() => {
        throw primary;
      });
    let signal!: AbortSignal;
    const abort = vi.fn();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
      signal = init!.signal!;
      signal.addEventListener("abort", abort);
      return response;
    });
    const result = bounded("/api/v1/evidence");
    await expect(result).rejects.toThrow(
      kind === "reader-error" ? primary : "EVIDENCE_CLIENT_INVALID",
    );
    expect(signal.aborted).toBe(true);
    expect(abort).toHaveBeenCalledTimes(1);
    expect(cancel).toHaveBeenCalledTimes(kind === "missing-body" ? 0 : 1);
    expect(stream.locked).toBe(false);
    await vi.advanceTimersByTimeAsync(20000);
    expect(abort).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  },
);

it.each(["length", "bytes", "frames"] as const)(
  "retires exactly once after the %s ceiling refuses a real stream",
  async (fault) => {
    vi.useFakeTimers();
    const r = controlledResponse(
      fault === "length" ? { "Content-Length": "65537" } : {},
      (c) => {
        if (fault === "bytes") c.enqueue(new Uint8Array(65537));
        if (fault === "frames")
          for (let i = 0; i < 4097; i++) c.enqueue(new Uint8Array(0));
      },
    );
    await expect(bounded("/api/v1/evidence")).rejects.toThrow(
      "EVIDENCE_CLIENT_INVALID",
    );
    expect(r.cancel).toHaveBeenCalledTimes(1);
    expect(r.reader()?.cancel).toHaveBeenCalledTimes(1);
    expect(r.reader()?.releaseLock).toHaveBeenCalledTimes(1);
    expect(r.abort).toHaveBeenCalledTimes(1);
    expect(r.stream.locked).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  },
);

it.each(["deadline", "caller"] as const)(
  "retires a stalled actual reader once on %s cancellation",
  async (fault) => {
    vi.useFakeTimers();
    const r = controlledResponse();
    const caller = new AbortController();
    const outcome = expect(
      bounded("/api/v1/evidence", { signal: caller.signal }),
    ).rejects.toMatchObject({ code: "EVIDENCE_CLIENT_TIMEOUT" });
    await vi.advanceTimersByTimeAsync(0);
    expect(r.stream.locked).toBe(true);
    if (fault === "caller") caller.abort();
    else await vi.advanceTimersByTimeAsync(10000);
    await outcome;
    await vi.advanceTimersByTimeAsync(20000);
    expect(r.cancel).toHaveBeenCalledTimes(1);
    expect(r.reader()?.cancel).toHaveBeenCalledTimes(1);
    expect(r.reader()?.releaseLock).toHaveBeenCalledTimes(1);
    expect(r.abort).toHaveBeenCalledTimes(1);
    expect(r.stream.locked).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("retires a late fetched response after deadline with no late consumer publication", async () => {
  vi.useFakeTimers();
  const r = controlledResponse();
  let release!: (v: Response) => void;
  r.fetcher.mockImplementation((_url, init) => {
    init!.signal!.addEventListener("abort", r.abort);
    return new Promise<Response>((resolve) => {
      release = resolve;
    });
  });
  const consume = vi.fn();
  const outcome = expect(
    bounded("/api/v1/evidence", {}, 65536, consume),
  ).rejects.toMatchObject({ code: "EVIDENCE_CLIENT_TIMEOUT" });
  await vi.advanceTimersByTimeAsync(10000);
  await outcome;
  release(r.response);
  await vi.advanceTimersByTimeAsync(0);
  expect(r.cancel).toHaveBeenCalledTimes(1);
  expect(r.abort).toHaveBeenCalledTimes(1);
  expect(r.stream.locked).toBe(false);
  expect(consume).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("releases the real reader while async validation stalls and refuses late success", async () => {
  vi.useFakeTimers();
  const r = controlledResponse({}, (c) => {
    c.enqueue(new Uint8Array([1]));
    c.close();
  });
  let release!: (value: string) => void;
  const consume = vi.fn(
    () =>
      new Promise<string>((resolve) => {
        release = resolve;
      }),
  );
  const operation = bounded("/api/v1/evidence", {}, 65536, consume);
  const outcome = expect(operation).rejects.toMatchObject({
    code: "EVIDENCE_CLIENT_TIMEOUT",
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(consume).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(10000);
  await outcome;
  expect(r.stream.locked).toBe(false);
  expect(r.reader()?.cancel).toHaveBeenCalledTimes(1);
  expect(r.reader()?.releaseLock).toHaveBeenCalledTimes(1);
  release("late");
  await vi.advanceTimersByTimeAsync(0);
  expect(r.abort).toHaveBeenCalledTimes(1);
  expect(r.reader()?.cancel).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["throw", "reject"] as const)(
  "does not mask header validation or create unhandled rejection when cancel will %s",
  async (fault) => {
    vi.useFakeTimers();
    const r = controlledResponse({ "Content-Encoding": "gzip" });
    r.cancel.mockImplementation(() => {
      if (fault === "throw") throw new Error("secondary cleanup");
      return Promise.reject(new Error("secondary cleanup"));
    });
    await expect(bounded("/api/v1/evidence")).rejects.toThrow(
      "EVIDENCE_CLIENT_INVALID",
    );
    await vi.advanceTimersByTimeAsync(20000);
    expect(r.cancel).toHaveBeenCalledTimes(1);
    expect(r.abort).toHaveBeenCalledTimes(1);
    expect(r.stream.locked).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("keeps successful bytes, reader release, and caller listener retirement without cancellation", async () => {
  vi.useFakeTimers();
  const r = controlledResponse({}, (c) => {
    c.enqueue(new Uint8Array([1, 2, 3]));
    c.close();
  });
  const caller = new AbortController();
  const result = await bounded("/api/v1/evidence", { signal: caller.signal });
  expect(result).toEqual({ bytes: new Uint8Array([1, 2, 3]), status: 200 });
  caller.abort();
  await vi.advanceTimersByTimeAsync(20000);
  expect(r.cancel).not.toHaveBeenCalled();
  expect(r.reader()?.cancel).not.toHaveBeenCalled();
  expect(r.reader()?.releaseLock).toHaveBeenCalledTimes(1);
  expect(r.signal().aborted).toBe(false);
  expect(r.abort).not.toHaveBeenCalled();
  expect(r.stream.locked).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});

it("streams exact/+1 response budget before decoding and cancels", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(new Uint8Array(65536)))
    .mockResolvedValueOnce(new Response(new Uint8Array(65537)));
  expect((await bounded("/api/v1/evidence", {}, 65536)).bytes.length).toBe(
    65536,
  );
  await expect(bounded("/api/v1/evidence", {}, 65536)).rejects.toThrow();
});
it("enforces a deadline even if acquisition never resolves", async () => {
  vi.useFakeTimers();
  vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
  const p = bounded("/api/v1/evidence", {}, 65536);
  const result = expect(p).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(10000);
  await result;
});
it("recognizes the exact producer 404 envelope without inventing a final absence proof", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(bytes("not-found.body"), { status: 404 }),
  );
  await expect(
    evidenceAPI.byRequest("4db4f744-286a-4fa1-b1ef-d6be167a1836"),
  ).rejects.toMatchObject({ code: "EVIDENCE_NOT_FOUND" });
});
it("reads actual producer detail and checks raw digest before download", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(bytes("complete-detail.body")),
  );
  const d = await evidenceAPI.get("3861d306-9823-4e38-a08d-bb3bc296d4bf");
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(new Uint8Array(d.evidence.ingress.size_bytes)),
  );
  await expect(evidenceAPI.raw(d.evidence, "ingress")).rejects.toThrow();
});
it("rejects both invalid file descriptors before reading either; exact bounds preserve names", async () => {
  const read = vi.fn().mockResolvedValue(new Uint8Array(65536).buffer);
  const f = { name: " x ", size: 65536, arrayBuffer: read } as unknown as File;
  await expect(
    prepareFiles(f, { ...f, size: 65537 } as File),
  ).rejects.toThrow();
  expect(read).not.toHaveBeenCalled();
  const p = await prepareFiles(f, f);
  expect(p.ingress.descriptor.name).toBe(" x ");
  expect(p.ingress.descriptor.size_bytes).toBe(65536);
  expect(read).toHaveBeenCalledTimes(2);
});
it("loads six exact local assets, verifies manifest and never posts or treats expectations as results", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(
      async (url) => new Response(readFileSync("public" + String(url))),
    );
  for (const id of ["complete", "violation", "unknown"] as const) {
    const pair = await loadSample(id);
    expect(pair.ingress.size).toBeGreaterThan(0);
    expect(
      await hashBytes(new Uint8Array(await pair.ingress.arrayBuffer())),
    ).toMatch(/^[a-f0-9]{64}$/);
  }
  expect(
    fetcher.mock.calls.every(
      ([url, init]) =>
        String(url).startsWith("/evidence-samples-v1/") && !init?.method,
    ),
  ).toBe(true);
});
