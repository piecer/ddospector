import { ReceiptStore } from "./storage";
import type { ScenarioVersion } from "../scenarios/types";
import type { Detail, Receipt, Summary } from "./types";
import { runAPI } from "./transport";
import { RunError } from "./errors";
import { RunObserver, matchesReceipt } from "./observer";
import { terminal } from "./grammar";
import { bindList } from "./checkpoint";
import { canonical } from "../scenarios/json";
import { requireValue } from "./wire";
type Hold = { epoch: number; receipt: Receipt };
const code = (e: unknown) =>
  e instanceof RunError ? e.code : "RUN_CLIENT_INVALID";
export class RunsController {
  view: RunObserver | null = null;
  busy = false;
  error: string | null = null;
  createdId: string | null = null;
  private revision = 0;
  private listeners = new Set<() => void>();
  private tail: Promise<unknown> = Promise.resolve();
  private initialization: Promise<void> | null = null;
  constructor(public readonly store: ReceiptStore) {}
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.revision;
  private changed() {
    this.revision++;
    this.listeners.forEach((f) => f());
  }
  private hold(): Hold | null {
    return this.store.receipt
      ? { epoch: this.store.epoch, receipt: this.store.receipt }
      : null;
  }
  private owns(h: Hold) {
    return (
      !!this.store.receipt &&
      h.epoch === this.store.epoch &&
      canonical(h.receipt.request) === canonical(this.store.receipt.request) &&
      h.receipt.request_digest === this.store.receipt.request_digest
    );
  }
  private serial<T>(work: () => Promise<T>): Promise<T> {
    const p = this.tail.then(work);
    this.tail = p.catch(() => undefined);
    return p;
  }
  start(): Promise<void> {
    return (this.initialization ??= (async () => {
      await this.store.initialize();
      this.changed();
      if (this.store.receipt) await this.recover();
    })());
  }
  select(id: string, summary: Summary | null = null) {
    if (this.view?.id === id) {
      if (summary && this.view.detail) bindList(summary, this.view.detail.run);
      return this.view;
    }
    this.view?.close();
    this.view = new RunObserver(id, summary);
    this.changed();
    return this.view;
  }
  leave() {
    this.view?.close();
    this.view = null;
    this.changed();
  }
  private visible(v: RunObserver | null) {
    return v !== null && v.active && this.view === v;
  }
  private canPoll(v: RunObserver) {
    return (
      this.visible(v) &&
      !v.stale &&
      !!v.detail &&
      !terminal(v.detail.run.state) &&
      performance.now() - v.started < 300_000
    );
  }
  private schedule(v: RunObserver) {
    v.stop();
    if (!this.canPoll(v)) return;
    v.timer = setTimeout(() => {
      v.timer = null;
      void this.viewOperation(false, v);
    }, 1000);
  }
  private async receive(
    input: Detail,
    h: Hold,
    v: RunObserver | null,
    resolve: boolean,
  ) {
    if (!this.owns(h)) return;
    const detail = await this.store.validate(input);
    if (!this.owns(h)) return;
    if (this.visible(v) && v!.id === detail.run.id) {
      v!.validate(detail);
      v!.publish(detail);
    }
    this.error = null;
    await this.store.accept(detail, resolve);
    if (
      resolve &&
      (this.owns(h) || (!this.store.receipt && this.store.epoch === h.epoch + 1))
    ) this.createdId = detail.run.id;
    this.changed();
  }
  async submit(scenario: ScenarioVersion): Promise<void> {
    if (this.busy || !this.store.canSubmit) return;
    this.busy = true;
    this.error = null;
    this.createdId = null;
    this.changed();
    const v = this.view;
    await this.serial(async () => {
      let h: Hold | null = null;
      try {
        const request = {
          request_id: crypto.randomUUID(),
          mode: "OFFLINE" as const,
          scenario_id: scenario.id,
          scenario_version: scenario.version,
          scenario_digest: scenario.digest,
        };
        if (!(await this.store.reserve(request, scenario))) return;
        h = this.hold();
        requireValue(h);
        this.changed();
        const detail = await runAPI.create(request);
        if (!this.owns(h)) return;
        await this.receive(detail, h, v, false);
        if (!this.owns(h)) return;
        const read = await runAPI.get(detail.run.id);
        if (this.owns(h)) await this.receive(read, h, v, true);
      } catch (e) {
        if (!h || this.owns(h)) this.error = code(e);
      } finally {
        this.busy = false;
        this.changed();
        if (v) this.schedule(v);
      }
    });
  }
  async recover(): Promise<void> {
    const h = this.hold(),
      v = this.view;
    if (!h) return;
    return this.serial(async () => {
      if (!this.owns(h)) return;
      this.busy = true;
      this.changed();
      try {
        const id = this.store.receipt!.checkpoint?.run.id;
        const d = id
          ? await runAPI.get(id)
          : await runAPI.byRequest(h.receipt.request.request_id);
        if (this.owns(h)) await this.receive(d, h, v, true);
      } catch (e) {
        if (this.owns(h)) {
          this.error = code(e);
          if (
            this.visible(v) &&
            matchesReceipt(
              this.store.receipt,
              v!.id,
              v!.detail?.run.request_id ?? v!.summary?.request_id,
            )
          ) {
            v!.stale = true;
            v!.error = code(e);
            v!.stop();
          }
        }
      } finally {
        this.busy = false;
        this.changed();
        if (v) this.schedule(v);
      }
    });
  }
  async replay(): Promise<void> {
    const h = this.hold(),
      v = this.view;
    if (!h || this.store.blocked || this.busy) return;
    return this.serial(async () => {
      if (!this.owns(h) || this.store.blocked) return;
      if (
        this.visible(v) &&
        matchesReceipt(this.store.receipt, v!.id, v!.detail?.run.request_id ?? v!.summary?.request_id)
      ) v!.stop();
      this.busy = true;
      this.changed();
      try {
        const d = await runAPI.create(h.receipt.request);
        if (!this.owns(h)) return;
        await this.receive(d, h, v, false);
        if (!this.owns(h)) return;
        const get = await runAPI.get(d.run.id);
        if (this.owns(h)) await this.receive(get, h, v, true);
      } catch (e) {
        if (this.owns(h)) {
          this.error = code(e);
          if (
            this.visible(v) &&
            matchesReceipt(this.store.receipt, v!.id, v!.detail?.run.request_id ?? v!.summary?.request_id)
          ) {
            v!.stale = true;
            v!.error = code(e);
            v!.stop();
          }
        }
      } finally {
        this.busy = false;
        this.changed();
        if (v) this.schedule(v);
      }
    });
  }
  async recheck() {
    return this.serial(async () => {
      await this.store.recheck();
      this.changed();
    });
  }
  async read() {
    return this.viewOperation(false);
  }
  async cancel() {
    return this.viewOperation(true);
  }
  private async viewOperation(cancel: boolean, automatic: RunObserver | null = null): Promise<void> {
    const v = automatic ?? this.view;
    if (
      !v ||
      (automatic && !this.canPoll(v)) ||
      !v.active ||
      v.reading ||
      v.cancelling ||
      (cancel && !v.canCancel)
    )
      return;
    const h = this.hold(),
      captured = h?.receipt ?? null;
    const bound =
      h &&
      matchesReceipt(
        captured,
        v.id,
        v.detail?.run.request_id ?? v.summary?.request_id,
      )
        ? h
        : null;
    v.stop();
    if (cancel) v.cancelling = true;
    else v.reading = true;
    this.changed();
    const eligible = () => (bound ? this.owns(bound) : this.visible(v));
    const work = async () => {
      if (!eligible() || (automatic && !this.canPoll(v))) return;
      try {
        const detail = cancel
          ? await runAPI.cancel(v.id)
          : await runAPI.get(v.id);
        if (!eligible()) return;
        requireValue(detail.run.id === v.id);
        if (bound) await this.receive(detail, bound, v, !cancel);
        else {
          if (
            matchesReceipt(captured, detail.run.id, detail.run.request_id) ||
            matchesReceipt(
              this.store.receipt,
              detail.run.id,
              detail.run.request_id,
            )
          )
            throw new RunError("RECOVERY_READ_REQUIRED");
          await v.accept(detail, this.store, captured);
        }
      } catch (e) {
        if (eligible()) {
          if (bound) this.error = code(e);
          if (this.visible(v)) {
            v.stale = true;
            v.error = cancel ? "CANCELLATION_UNCONFIRMED" : code(e);
            v.stop();
          }
        }
      }
    };
    try {
      if (bound) await this.serial(work);
      else await work();
    } finally {
      v.reading = false;
      v.cancelling = false;
      this.changed();
      this.schedule(v);
    }
  }
}
let instance: RunsController | null = null;
/** One document lifetime, survives route unmount; no eager storage access. */
export function runsController(): RunsController {
  return (instance ??= new RunsController(
    new ReceiptStore({
      getItem: (k) => sessionStorage.getItem(k),
      setItem: (k, v) => sessionStorage.setItem(k, v),
      removeItem: (k) => sessionStorage.removeItem(k),
    }),
  ));
}
