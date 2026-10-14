import { canonical, utf8Length } from "../scenarios/json";
import { exact, sha256 } from "../scenarios/validation";
import { uuid } from "../runs/wire";
import { runAPI } from "../runs/transport";
import type { Summary as RunSummary, Detail as RunDetail } from "../runs/types";
import { check, descriptor, bindRun, bindSubmission, wire } from "./codec";
import { evidenceAPI, prepareFiles, admitFile } from "./client";
import { EvidenceError } from "./errors";
import type { Binding, Collection, Detail, Summary } from "./types";
const receiptKey = "ddospector.evidence.pending.v1";
function readPending(): Binding | null {
  const text = sessionStorage.getItem(receiptKey);
  if (text === null) return null;
  check(text.length <= 4096);
  const v = wire(new TextEncoder().encode(text), 4096);
  check(
    exact(v, [
      "request_id",
      "run_id",
      "run_snapshot_digest",
      "ingress",
      "egress",
    ]) &&
      uuid(v.request_id) &&
      uuid(v.run_id) &&
      sha256(v.run_snapshot_digest),
  );
  descriptor(v.ingress);
  descriptor(v.egress);
  return v as Binding;
}
function savePending(value: Binding | null) {
  if (value === null) {
    sessionStorage.removeItem(receiptKey);
    check(sessionStorage.getItem(receiptKey) === null);
  } else {
    const text = canonical(value);
    check(utf8Length(text) <= 4096);
    sessionStorage.setItem(receiptKey, text);
    check(sessionStorage.getItem(receiptKey) === text);
  }
}
export type State = {
  collection: Collection | null;
  listError: string | null;
  runs: RunSummary[] | null;
  runError: string | null;
  selected: string | null;
  detail: Detail | null;
  source: RunDetail | null;
  readError: string | null;
  pending: Binding | null;
  storageError: boolean;
  busy: boolean;
  waiting: boolean;
  pollStopped: boolean;
  actionError: string | null;
  registered: boolean;
};
function code(e: unknown) {
  return e instanceof EvidenceError ? e.code : "EVIDENCE_CLIENT_INVALID";
}
export class EvidenceController {
  state: State = {
    collection: null,
    listError: null,
    runs: null,
    runError: null,
    selected: null,
    detail: null,
    source: null,
    readError: null,
    pending: null,
    storageError: false,
    busy: false,
    waiting: false,
    pollStopped: false,
    actionError: null,
    registered: false,
  };
  private listeners = new Set<() => void>();
  private alive = true;
  private selectedAbort: AbortController | null = null;
  private listAbort: AbortController | null = null;
  private runsAbort: AbortController | null = null;
  private actionAbort: AbortController | null = null;
  private generation = 0;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private pollStart = 0;
  private pollDeadline: ReturnType<typeof setTimeout> | null = null;
  // Immutable, append-only repository: retain at most its existing 16 identities.
  // Never retain reports for unselected records or infer their outcomes.
  private summaries = new Map<string, Summary>();
  private reconcile(incoming: Summary[]) {
    const next = new Map(this.summaries);
    for (const s of incoming) {
      const old = next.get(s.id);
      if (old) {
        check(
          canonical({ ...old, analysis_state: s.analysis_state }) ===
            canonical(s),
        );
      }
      next.set(s.id, old?.analysis_state === "ANALYZED" ? old : s);
      check(next.size <= 16);
    }
    const items = [...next.values()].sort((a, b) => a.ordinal - b.ordinal);
    check(new Set(items.map((s) => s.ordinal)).size === items.length);
    check(new Set(items.map((s) => s.request_id)).size === items.length);
    return {
      next,
      collection: { schema_version: 1 as const, items, total: items.length },
    };
  }
  constructor() {
    try {
      this.state.pending = readPending();
    } catch {
      this.state.storageError = true;
    }
    document.addEventListener("visibilitychange", this.visibility);
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  snapshot = () => this.state;
  private update(p: Partial<State>) {
    if (!this.alive) return;
    this.state = { ...this.state, ...p };
    this.listeners.forEach((f) => f());
  }
  private visibility = () => {
    if (document.hidden) this.stopPolling();
  };
  async refreshList() {
    if (!this.alive || this.listAbort) return;
    const a = new AbortController();
    this.listAbort = a;
    try {
      const collection = await evidenceAPI.list(a.signal);
      if (!a.signal.aborted) {
        const merged = this.reconcile(collection.items);
        this.summaries = merged.next;
        // A list can know report presence but cannot supply a validated report.
        const obsolete =
          this.state.detail?.report === null &&
          merged.next.get(this.state.detail.evidence.id)?.analysis_state ===
            "ANALYZED";
        this.update({
          collection: merged.collection,
          listError: null,
          ...(obsolete ? { detail: null, source: null } : {}),
        });
      }
    } catch (e) {
      if (!a.signal.aborted) this.update({ listError: code(e) });
    } finally {
      if (this.listAbort === a) this.listAbort = null;
    }
  }
  async refreshRuns() {
    if (!this.alive || this.runsAbort) return;
    const a = new AbortController();
    this.runsAbort = a;
    try {
      const runs: RunSummary[] = [];
      let after = 0,
        through: number | undefined;
      for (let page = 0; page < 7; page++) {
        const p = await runAPI.list(after, 20, through, a.signal);
        a.signal.throwIfAborted();
        through = p.through;
        runs.push(...p.items);
        check(runs.length <= 128);
        if (p.next_after === null) {
          check(runs.length === p.total);
          this.update({
            runs: runs.filter((r) => r.state === "SUCCEEDED"),
            runError: null,
          });
          return;
        }
        after = p.next_after;
      }
      throw new Error("invalid pagination");
    } catch (e) {
      if (!a.signal.aborted) this.update({ runError: code(e) });
    } finally {
      if (this.runsAbort === a) this.runsAbort = null;
    }
  }
  stopPolling() {
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    if (this.pollDeadline !== null) clearTimeout(this.pollDeadline);
    this.pollTimer = null;
    this.pollDeadline = null;
    this.selectedAbort?.abort();
    this.selectedAbort = null;
    ++this.generation;
    this.update({ waiting: false, pollStopped: true });
  }
  async select(id: string) {
    if (!this.alive) return;
    this.stopPolling();
    this.pollStart = performance.now();
    const gen = this.generation;
    this.update({
      selected: id,
      detail: null,
      source: null,
      readError: null,
      pollStopped: false,
    });
    await this.readSelected(id, gen);
  }
  async refreshSelected() {
    if (this.state.selected) await this.select(this.state.selected);
  }
  private schedule(id: string, gen: number) {
    if (document.hidden || performance.now() - this.pollStart >= 60000) {
      this.update({ waiting: false, pollStopped: true });
      return;
    }
    this.update({ waiting: true });
    if (this.pollDeadline === null)
      this.pollDeadline = setTimeout(
        () => this.stopPolling(),
        Math.max(0, 60000 - (performance.now() - this.pollStart)),
      );
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      void this.readSelected(id, gen);
    }, 2000);
  }
  private async readSelected(id: string, gen: number) {
    if (!this.alive || gen !== this.generation) return;
    const a = new AbortController();
    this.selectedAbort = a;
    try {
      const d = await evidenceAPI.get(id, a.signal);
      const run = await runAPI.get(d.evidence.run_id, a.signal);
      bindRun(d, run);
      if (!this.alive || a.signal.aborted || gen !== this.generation) return;
      const merged = this.reconcile([d.evidence]);
      this.summaries = merged.next;
      if (
        d.report === null &&
        merged.next.get(id)?.analysis_state === "ANALYZED"
      ) {
        // A read started before terminal publication; keep the bounded poll,
        // never fabricate a report or downgrade the known immutable summary.
        this.schedule(id, gen);
        return;
      }
      this.update({
        detail: d,
        source: run,
        readError: null,
        collection: this.state.collection ? merged.collection : null,
      });
      if (d.report === null) this.schedule(id, gen);
      else {
        if (this.pollDeadline !== null) clearTimeout(this.pollDeadline);
        this.pollDeadline = null;
        this.update({ waiting: false, pollStopped: false });
      }
    } catch (e) {
      if (this.alive && gen === this.generation && !a.signal.aborted) {
        if (this.pollDeadline !== null) clearTimeout(this.pollDeadline);
        this.pollDeadline = null;
        this.update({ readError: code(e), waiting: false, pollStopped: true });
      }
    } finally {
      if (this.selectedAbort === a) this.selectedAbort = null;
    }
  }
  async submit(runId: string, ingress: File, egress: File) {
    if (
      !this.alive ||
      this.state.busy ||
      this.state.pending ||
      this.state.storageError
    )
      return;
    const a = new AbortController();
    this.actionAbort = a;
    this.update({ busy: true, actionError: null, registered: false });
    try {
      // Admission happens before source lookup as well as before either file read.
      admitFile(ingress);
      admitFile(egress);
      const run = await runAPI.get(runId, a.signal);
      check(run.run.state === "SUCCEEDED" && run.run.id === runId);
      const pair = await prepareFiles(ingress, egress, a.signal);
      a.signal.throwIfAborted();
      if (!this.alive) return;
      const request_id = crypto.randomUUID();
      const pending: Binding = {
        request_id,
        run_id: runId,
        run_snapshot_digest: run.snapshot.digest,
        ingress: pair.ingress.descriptor,
        egress: pair.egress.descriptor,
      };
      try {
        savePending(pending);
      } catch {
        this.update({ storageError: true });
        throw new Error("storage");
      }
      this.update({ pending });
      const d = await evidenceAPI.post(
        {
          request_id,
          run_id: runId,
          ingress: pair.ingress.input,
          egress: pair.egress.input,
        },
        a.signal,
      );
      a.signal.throwIfAborted();
      bindSubmission(d, pending);
      bindRun(d, run);
      await this.accept(d, run, a);
    } catch (e) {
      if (!a.signal.aborted) this.update({ actionError: code(e) });
    } finally {
      if (this.actionAbort === a) this.actionAbort = null;
      this.update({ busy: false });
    }
  }
  async resolve() {
    const pending = this.state.pending;
    if (!this.alive || this.state.busy || !pending || this.state.storageError)
      return;
    const a = new AbortController();
    this.actionAbort = a;
    this.update({ busy: true, actionError: null });
    try {
      const d = await evidenceAPI.byRequest(pending.request_id, a.signal);
      bindSubmission(d, pending);
      const run = await runAPI.get(d.evidence.run_id, a.signal);
      bindRun(d, run);
      a.signal.throwIfAborted();
      await this.accept(d, run, a);
    } catch (e) {
      if (!a.signal.aborted) this.update({ actionError: code(e) });
    } finally {
      if (this.actionAbort === a) this.actionAbort = null;
      this.update({ busy: false });
    }
  }
  private async accept(d: Detail, run: RunDetail, a: AbortController) {
    if (!this.alive || a.signal.aborted) return;
    const merged = this.reconcile([d.evidence]);
    try {
      savePending(null);
    } catch {
      this.update({ storageError: true });
      throw new Error("storage");
    }
    this.stopPolling();
    this.pollStart = performance.now();
    this.summaries = merged.next;
    const obsolete =
      d.report === null &&
      merged.next.get(d.evidence.id)?.analysis_state === "ANALYZED";
    this.update({
      pending: null,
      registered: true,
      selected: d.evidence.id,
      detail: obsolete ? null : d,
      source: obsolete ? null : run,
      collection: this.state.collection ? merged.collection : null,
      readError: null,
      pollStopped: false,
    });
    if (d.report === null) this.schedule(d.evidence.id, this.generation);
    await this.refreshList();
  }
  dispose() {
    this.stopPolling();
    this.alive = false;
    this.actionAbort?.abort();
    this.listAbort?.abort();
    this.runsAbort?.abort();
    document.removeEventListener("visibilitychange", this.visibility);
    this.listeners.clear();
  }
}
