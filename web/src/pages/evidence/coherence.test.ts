import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { File as NodeFile } from "node:buffer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EvidenceController } from "./controller";
import { evidenceAPI } from "./client";
import { decodeDetail, decodeList, parseDetail } from "./codec";
import { canonical } from "../scenarios/json";
import { parseDetail as parseRun } from "../runs/wire";
import { runAPI } from "../runs/transport";
import type { Collection, Detail, Summary } from "./types";

const bytes = (name: string) =>
  new Uint8Array(readFileSync("../tests/fixtures/evidence/" + name));
// Scheduling projections only: producer fixture bytes are never changed.
const list = (items: Summary[]): Collection =>
  decodeList(
    new TextEncoder().encode(
      canonical({ schema_version: 1, items, total: items.length }),
    ),
  );
const held = <T>() => {
  let release!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    release = r;
  });
  return { promise, release };
};
async function load() {
  const registered = await decodeDetail(bytes("complete-registered.body"));
  const analyzed = await decodeDetail(bytes("complete-detail.body"));
  const second = await decodeDetail(bytes("violation-registered.body"));
  const run = await parseRun(
    JSON.parse(new TextDecoder().decode(bytes("run-before.body"))),
  );
  vi.spyOn(runAPI, "get").mockResolvedValue(run);
  return { registered, analyzed, second, run };
}
function coherent(c: EvidenceController, d: Detail) {
  const s = c.snapshot();
  expect(s.collection?.items.find((x) => x.id === d.evidence.id)).toEqual(
    d.evidence,
  );
  expect(s.selected).toBe(d.evidence.id);
  expect(s.detail).toEqual(d);
  expect(s.detail?.report).toMatchObject({
    outcome: "SATISFIED",
    scenario_evaluation: "NOT_EVALUATED",
    defense_verdict: null,
  });
  expect(s.source?.result).toMatchObject({
    evaluation: "NOT_EVALUATED",
    defense_verdict: null,
  });
  expect(s.readError).toBeNull();
  expect(s.listError).toBeNull();
}
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

it("reconciles a held old list after terminal detail, including after viewing another record", async () => {
  const { registered, analyzed, second, run } = await load();
  const old = list([registered.evidence, second.evidence]);
  const pending = held<Collection>();
  const lists = vi
    .spyOn(evidenceAPI, "list")
    .mockResolvedValueOnce(old)
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue(old);
  vi.spyOn(evidenceAPI, "get")
    .mockResolvedValueOnce(analyzed)
    .mockResolvedValueOnce(second)
    .mockResolvedValueOnce(analyzed);
  const c = new EvidenceController();
  try {
    await c.refreshList();
    const request = c.refreshList();
    await c.select(analyzed.evidence.id);
    coherent(c, analyzed);
    pending.release(old);
    await request;
    coherent(c, analyzed);
    await c.select(second.evidence.id);
    await c.refreshList();
    expect(c.state.collection?.items).toEqual([
      analyzed.evidence,
      second.evidence,
    ]);
    expect(c.state.detail).toEqual(second);
    expect(c.state.source).toEqual(run);
    await c.select(analyzed.evidence.id);
    coherent(c, analyzed);
    expect(lists).toHaveBeenCalledTimes(3);
  } finally {
    c.dispose();
  }
});

it("retains a registration acknowledged while the older empty list is in flight, then polls coherently", async () => {
  const { registered, analyzed, run } = await load();
  const pending = held<Collection>();
  const lists = vi
    .spyOn(evidenceAPI, "list")
    .mockResolvedValueOnce(list([]))
    .mockReturnValueOnce(pending.promise);
  vi.spyOn(evidenceAPI, "post").mockResolvedValue(registered);
  vi.spyOn(evidenceAPI, "get").mockResolvedValue(analyzed);
  vi.spyOn(crypto, "randomUUID").mockReturnValue(
    registered.evidence
      .request_id as `${string}-${string}-${string}-${string}-${string}`,
  );
  const files = ["ingress", "egress"].map(
    (side) =>
      new NodeFile(
        [readFileSync(`public/evidence-samples-v1/complete-${side}.pcap`)],
        registered.evidence[side as "ingress" | "egress"].name,
      ) as unknown as File,
  );
  const c = new EvidenceController();
  try {
    await c.refreshList();
    const request = c.refreshList();
    vi.useFakeTimers();
    await c.submit(run.run.id, files[0], files[1]);
    expect(c.state.pending).toBeNull();
    expect(c.state.collection).toEqual(list([registered.evidence]));
    await vi.advanceTimersByTimeAsync(2000);
    pending.release(list([]));
    await request;
    coherent(c, analyzed);
    expect(c.state.collection?.total).toBe(1);
    expect(lists).toHaveBeenCalledTimes(2);
    expect(evidenceAPI.post).toHaveBeenCalledTimes(1);
  } finally {
    c.dispose();
  }
});

it("does not downgrade terminal list knowledge with an older registration acknowledgement", async () => {
  const { registered, analyzed, run } = await load();
  const pending = held<Detail>();
  vi.spyOn(evidenceAPI, "list").mockResolvedValue(list([analyzed.evidence]));
  vi.spyOn(evidenceAPI, "post").mockReturnValue(pending.promise);
  vi.spyOn(evidenceAPI, "get").mockResolvedValue(analyzed);
  vi.spyOn(crypto, "randomUUID").mockReturnValue(
    registered.evidence
      .request_id as `${string}-${string}-${string}-${string}-${string}`,
  );
  const files = ["ingress", "egress"].map(
    (side) =>
      new NodeFile(
        [readFileSync(`public/evidence-samples-v1/complete-${side}.pcap`)],
        registered.evidence[side as "ingress" | "egress"].name,
      ) as unknown as File,
  );
  const c = new EvidenceController();
  const contradictions: unknown[] = [];
  c.subscribe(() => {
    const s = c.snapshot();
    if (
      s.detail &&
      s.collection?.items.some(
        (row) =>
          row.id === s.detail!.evidence.id &&
          row.analysis_state !== s.detail!.evidence.analysis_state,
      )
    )
      contradictions.push(s);
  });
  try {
    const submission = c.submit(run.run.id, files[0], files[1]);
    await vi.waitFor(() => expect(evidenceAPI.post).toHaveBeenCalledTimes(1));
    await c.refreshList();
    vi.useFakeTimers();
    pending.release(registered);
    await submission;
    expect(contradictions).toEqual([]);
    expect(c.state.pending).toBeNull();
    expect(c.state.collection?.items).toEqual([analyzed.evidence]);
    expect(c.state.detail).toBeNull();
    await vi.advanceTimersByTimeAsync(2000);
    coherent(c, analyzed);
  } finally {
    c.dispose();
  }
});

it.each(["list", "detail"] as const)(
  "refuses same-ID conflicting immutable metadata on %s publication without laundering it",
  async (path) => {
    const { registered, analyzed } = await load();
    const lists = vi
      .spyOn(evidenceAPI, "list")
      .mockResolvedValue(list([registered.evidence]));
    const get = vi.spyOn(evidenceAPI, "get").mockResolvedValue(analyzed);
    const c = new EvidenceController();
    try {
      await c.refreshList();
      await c.select(analyzed.evidence.id);
      const changed = await parseDetail({
        ...analyzed,
        evidence: {
          ...analyzed.evidence,
          ingress: {
            ...analyzed.evidence.ingress,
            name: "conflicting name.pcap",
          },
        },
      });
      if (path === "list") {
        lists.mockResolvedValue(list([changed.evidence]));
        await c.refreshList();
        expect(c.state.listError).toBe("EVIDENCE_CLIENT_INVALID");
        expect(c.state.detail).toEqual(analyzed);
      } else {
        get.mockResolvedValue(changed);
        await c.refreshSelected();
        expect(c.state.readError).toBe("EVIDENCE_CLIENT_INVALID");
        expect(c.state.detail).toBeNull();
      }
      expect(c.state.collection?.items).toEqual([analyzed.evidence]);
      lists.mockResolvedValue(list([registered.evidence]));
      await c.refreshList();
      get.mockResolvedValue(analyzed);
      await c.refreshSelected();
      coherent(c, analyzed);
    } finally {
      c.dispose();
    }
  },
);

it("keeps all 16 immutable rows ordered, unobserved analysis unchanged, and refuses another identity at capacity", async () => {
  const { analyzed, registered } = await load();
  const full = list([
    registered.evidence,
    ...decodeList(bytes("full-list.body")).items.slice(1),
  ]);
  const lists = vi.spyOn(evidenceAPI, "list").mockResolvedValue(full);
  vi.spyOn(evidenceAPI, "get").mockResolvedValue(analyzed);
  const c = new EvidenceController();
  try {
    await c.refreshList();
    await c.select(analyzed.evidence.id);
    coherent(c, analyzed);
    expect(c.state.collection).toEqual({
      ...full,
      items: [analyzed.evidence, ...full.items.slice(1)],
    });
    lists.mockResolvedValue(
      list([
        {
          ...registered.evidence,
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          request_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        },
      ]),
    );
    await c.refreshList();
    expect(c.state.listError).toBe("EVIDENCE_CLIENT_INVALID");
    expect(c.state.collection?.total).toBe(16);
    lists.mockResolvedValue(full);
    await c.refreshList();
    coherent(c, analyzed);
    expect(c.state.collection?.items.slice(1)).toEqual(full.items.slice(1));
  } finally {
    c.dispose();
  }
});

it("does not publish an old selected REGISTERED detail after an ANALYZED list or fabricate its report", async () => {
  const { registered, analyzed } = await load();
  vi.useFakeTimers();
  const pending = held<Detail>();
  vi.spyOn(evidenceAPI, "get")
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValue(analyzed);
  vi.spyOn(evidenceAPI, "list").mockResolvedValue(list([analyzed.evidence]));
  const c = new EvidenceController();
  try {
    const selected = c.select(registered.evidence.id);
    await c.refreshList();
    pending.release(registered);
    await selected;
    expect(c.state.collection?.items).toEqual([analyzed.evidence]);
    expect(c.state.detail).toBeNull();
    expect(c.state.readError).toBeNull();
    await vi.advanceTimersByTimeAsync(2000);
    coherent(c, analyzed);
  } finally {
    c.dispose();
  }
});
