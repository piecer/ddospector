import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { File as NodeFile } from "node:buffer";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { EvidenceController } from "./controller";
import { EvidenceError } from "./errors";
import { evidenceAPI } from "./client";
import { runAPI } from "../runs/transport";
import { decodeDetail, decodeList } from "./codec";
import { parseDetail } from "../runs/wire";
const bytes = (name: string) =>
  new Uint8Array(readFileSync("../tests/fixtures/evidence/" + name));
const load = async () => ({
  registered: await decodeDetail(bytes("complete-registered.body")),
  analyzed: await decodeDetail(bytes("complete-detail.body")),
  run: await parseDetail(
    JSON.parse(new TextDecoder().decode(bytes("run-before.body"))),
  ),
});
const files = () =>
  ["ingress", "egress"].map(
    (side) =>
      new NodeFile(
        [readFileSync(`public/evidence-samples-v1/complete-${side}.pcap`)],
        ` original ${side}.pcap`,
      ) as unknown as File,
  );
beforeEach(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("keeps unknown POST identity through locale-style resubscription; doubleclick never posts twice; 404 resolves read-only", async () => {
  const { run, registered } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  vi.spyOn(crypto, "randomUUID").mockReturnValue(
    registered.evidence
      .request_id as `${string}-${string}-${string}-${string}-${string}`,
  );
  const post = vi
    .spyOn(evidenceAPI, "post")
    .mockRejectedValue(new Error("lost"));
  const c = new EvidenceController();
  const [i, e] = files();
  await Promise.all([c.submit(run.run.id, i, e), c.submit(run.run.id, i, e)]);
  expect(post).toHaveBeenCalledTimes(1);
  expect(c.state.pending?.request_id).toBe(registered.evidence.request_id);
  const lookup = vi
    .spyOn(evidenceAPI, "byRequest")
    .mockRejectedValue(new EvidenceError("EVIDENCE_NOT_FOUND"));
  await c.resolve();
  expect(c.state.actionError).toBe("EVIDENCE_NOT_FOUND");
  expect(c.state.pending).not.toBeNull();
  expect(
    sessionStorage.getItem("ddospector.evidence.pending.v1"),
  ).not.toContain("base64");
  expect(lookup).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledTimes(1);
  c.dispose();
  const next = new EvidenceController();
  expect(next.state.pending?.request_id).toBe(registered.evidence.request_id);
  next.dispose();
});
it("automatically observes terminal publication on the same selected route without manual refresh", async () => {
  const { run, registered, analyzed } = await load();
  vi.useFakeTimers();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  const get = vi
    .spyOn(evidenceAPI, "get")
    .mockResolvedValueOnce(registered)
    .mockResolvedValueOnce(analyzed);
  vi.spyOn(evidenceAPI, "list").mockResolvedValue({
    schema_version: 1,
    items: [registered.evidence],
    total: 1,
  });
  const c = new EvidenceController();
  try {
    await c.refreshList();
    await c.select(registered.evidence.id);
    expect(c.state.waiting).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    const state = c.snapshot();
    expect(state.detail?.report?.outcome).toBe("SATISFIED");
    expect(state.collection?.items).toEqual([analyzed.evidence]);
    expect(state.listError).toBeNull();
    expect(state.readError).toBeNull();
    expect(state.source).toEqual(run);
    expect(state.source?.result).toMatchObject({
      evaluation: "NOT_EVALUATED",
      defense_verdict: null,
    });
    expect(state.waiting).toBe(false);
    expect(get).toHaveBeenCalledTimes(2);
  } finally {
    c.dispose();
  }
});
it("ignores stale/out-of-order selected reads and stops on unmount", async () => {
  const { run, registered, analyzed } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  let finish!: (v: typeof registered) => void;
  vi.spyOn(evidenceAPI, "get")
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          finish = r;
        }),
    )
    .mockResolvedValueOnce(analyzed);
  const c = new EvidenceController();
  const first = c.select(registered.evidence.id);
  await c.select(analyzed.evidence.id);
  finish(registered);
  await first;
  expect(c.state.detail?.report).not.toBeNull();
  c.dispose();
  expect(c.state.waiting).toBe(false);
});
it("shows all 16 actual repository entries, never masks unavailable as empty", async () => {
  vi.spyOn(evidenceAPI, "list").mockResolvedValue(
    decodeList(bytes("full-list.body")),
  );
  vi.spyOn(runAPI, "list").mockRejectedValue(new Error("unavailable"));
  const c = new EvidenceController();
  await c.refreshList();
  expect(c.state.collection?.total).toBe(16);
  vi.mocked(evidenceAPI.list).mockRejectedValue(new Error("bad"));
  await c.refreshList();
  expect(c.state.listError).not.toBeNull();
  expect(c.state.collection?.total).toBe(16);
  c.dispose();
});
it("refuses an internally valid foreign acknowledgement without clearing the captured pending identity", async () => {
  const { run, analyzed } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  vi.spyOn(evidenceAPI, "post").mockResolvedValue(analyzed);
  const c = new EvidenceController();
  const [i, e] = files();
  await c.submit(run.run.id, i, e);
  expect(c.state.pending).not.toBeNull();
  expect(c.state.registered).toBe(false);
  expect(c.state.actionError).not.toBeNull();
  c.dispose();
});
it("binds acknowledged original names and digests, not just request and Run IDs", async () => {
  const { run, registered } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  vi.spyOn(crypto, "randomUUID").mockReturnValue(
    registered.evidence
      .request_id as `${string}-${string}-${string}-${string}-${string}`,
  );
  vi.spyOn(evidenceAPI, "post").mockResolvedValue(registered);
  const c = new EvidenceController();
  const [i, e] = files();
  const changed = new NodeFile(
    [await i.arrayBuffer()],
    "different.pcap",
  ) as unknown as File;
  await c.submit(run.run.id, changed, e);
  expect(c.state.pending).not.toBeNull();
  expect(c.state.registered).toBe(false);
  expect(c.state.actionError).not.toBeNull();
  c.dispose();
});
it("bounds polling elapsed time, does not overlap slow GETs, stops when hidden and retains visible read errors", async () => {
  const { run, registered } = await load();
  vi.useFakeTimers();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  const get = vi.spyOn(evidenceAPI, "get").mockResolvedValue(registered);
  const c = new EvidenceController();
  await c.select(registered.evidence.id);
  let finish!: (v: typeof registered) => void;
  get.mockImplementationOnce(
    () =>
      new Promise((r) => {
        finish = r;
      }),
  );
  await vi.advanceTimersByTimeAsync(10000);
  expect(get).toHaveBeenCalledTimes(2);
  finish(registered);
  await vi.advanceTimersByTimeAsync(0);
  Object.defineProperty(document, "hidden", {
    value: true,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(60000);
  expect(get).toHaveBeenCalledTimes(2);
  expect(c.state.waiting).toBe(false);
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  get.mockResolvedValue(registered);
  await c.refreshSelected();
  await vi.advanceTimersByTimeAsync(60000);
  const count = get.mock.calls.length;
  await vi.advanceTimersByTimeAsync(60000);
  expect(get).toHaveBeenCalledTimes(count);
  expect(c.state.pollStopped).toBe(true);
  get.mockRejectedValue(new Error("corrupt"));
  await c.refreshSelected();
  expect(c.state.readError).not.toBeNull();
  expect(c.state.waiting).toBe(false);
  c.dispose();
});
it("fails closed when pending receipt cannot be persisted, without POST", async () => {
  const { run } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const post = vi.spyOn(evidenceAPI, "post");
  const c = new EvidenceController();
  const [i, e] = files();
  await c.submit(run.run.id, i, e);
  expect(post).not.toHaveBeenCalled();
  expect(c.state.storageError).toBe(true);
  c.dispose();
});
it("controller unmount retires the actual bounded selected-response reader", async () => {
  const { registered } = await load();
  vi.useFakeTimers();
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ cancel });
  let signal!: AbortSignal;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    signal = init!.signal!;
    return new Response(stream);
  });
  const c = new EvidenceController();
  try {
    const request = c.select(registered.evidence.id);
    await vi.advanceTimersByTimeAsync(0);
    expect(stream.locked).toBe(true);
    c.dispose();
    await request;
    await vi.advanceTimersByTimeAsync(20000);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(signal.aborted).toBe(true);
    expect(stream.locked).toBe(false);
    expect(c.state.detail).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    c.dispose();
  }
});

it("never submits after an asynchronous file read completes following disposal", async () => {
  const { run } = await load();
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  const post = vi.spyOn(evidenceAPI, "post");
  let finish!: (v: ArrayBuffer) => void;
  const f = {
    name: "x",
    size: 1,
    arrayBuffer: () =>
      new Promise<ArrayBuffer>((r) => {
        finish = r;
      }),
  } as File;
  const c = new EvidenceController();
  const p = c.submit(run.run.id, f, f);
  await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
  c.dispose();
  finish(new ArrayBuffer(1));
  await p;
  expect(post).not.toHaveBeenCalled();
});
