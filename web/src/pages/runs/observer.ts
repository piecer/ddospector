import type { Detail, Summary, Receipt } from "./types";
import type { ReceiptStore } from "./storage";
import { parseDetail, requireValue, uuid } from "./wire";
import { bindList, compareDetail } from "./checkpoint";
import { terminal } from "./grammar";
export function matchesReceipt(
  receipt: Receipt | null,
  id: string,
  requestId?: string,
): boolean {
  return (
    !!receipt &&
    (receipt.checkpoint?.run.id === id ||
      receipt.request.request_id === requestId)
  );
}
export class RunObserver {
  readonly token = Symbol("run-view");
  readonly started = performance.now();
  detail: Detail | null = null;
  stale = false;
  active = true;
  reading = false;
  cancelling = false;
  error: string | null = null;
  timer: ReturnType<typeof setTimeout> | null = null;
  constructor(
    public readonly id: string,
    public readonly summary: Summary | null = null,
  ) {
    requireValue(uuid(id));
    if (summary) requireValue(summary.id === id);
  }
  get canCancel() {
    return (
      this.active &&
      !!this.detail &&
      !this.stale &&
      !terminal(this.detail.run.state) &&
      !this.cancelling
    );
  }
  validate(value: Detail): void {
    requireValue(this.active && value.run.id === this.id);
    if (this.summary) bindList(this.summary, value.run);
    if (this.detail) compareDetail(this.detail, value);
  }
  publish(value: Detail): void {
    this.validate(value);
    this.detail = value;
    this.stale = false;
    this.error = null;
  }
  async accept(
    value: Detail,
    store: ReceiptStore,
    captured: Receipt | null = null,
  ) {
    const detail = await parseDetail(value);
    requireValue(
      !matchesReceipt(captured, detail.run.id, detail.run.request_id) &&
        !matchesReceipt(store.receipt, detail.run.id, detail.run.request_id),
    );
    this.publish(detail);
  }
  stop() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }
  close() {
    this.stop();
    this.active = false;
    this.detail = null;
  }
}
