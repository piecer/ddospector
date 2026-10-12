import type { Receipt, Request, Detail } from "./types";
import type { ScenarioVersion } from "../scenarios/types";
import { parseVersion } from "../scenarios/wire";
import { canonical, digest, utf8Length } from "../scenarios/json";
import { RECEIPT_KEY, parseReceipt, parseRequest } from "./receipt";
import { bindRequest, checkpoint, compareCheckpoint } from "./checkpoint";
import { parseDetail, requireValue } from "./wire";
import { snapshot, freeze } from "./object";
export type StoragePort = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type RecoveryNotice =
  | "RECOVERY_MEMORY_ONLY"
  | "RECOVERY_CHECKPOINT_UNSAVED"
  | "RECOVERY_STORAGE_UNKNOWN"
  | "RECOVERY_STORAGE_INVALID"
  | "RECOVERY_IDENTITY_CONFLICT"
  | "RECOVERY_CLEAR_UNCONFIRMED";
export class ReceiptStore {
  receipt: Receipt | null = null;
  original: ScenarioVersion | null = null;
  epoch = 0;
  notice: RecoveryNotice | null = null;
  resolved = false;
  initialized = false;
  private init: Promise<void> | null = null;
  private savedText: string | null = null;
  private persisted = false;
  private reserving = false;
  constructor(public readonly storage: StoragePort) {}
  get blocked() {
    return [
      "RECOVERY_STORAGE_UNKNOWN",
      "RECOVERY_STORAGE_INVALID",
      "RECOVERY_IDENTITY_CONFLICT",
    ].includes(this.notice ?? "");
  }
  get canSubmit() {
    return this.initialized && !this.receipt && !this.notice && !this.reserving;
  }
  private read(): { text: string | null } | null {
    try {
      return { text: this.storage.getItem(RECEIPT_KEY) };
    } catch {
      this.notice = "RECOVERY_STORAGE_UNKNOWN";
      return null;
    }
  }
  private async inspect(): Promise<{
    text: string | null;
    receipt: Receipt | null;
  } | null> {
    const read = this.read();
    if (!read) return null;
    let stored: Receipt | null = null;
    if (read.text !== null) {
      try {
        stored = await parseReceipt(read.text);
      } catch {
        this.notice = "RECOVERY_STORAGE_INVALID";
        return null;
      }
    }
    const again = this.read();
    if (!again) return null;
    if (again.text !== read.text) {
      this.notice = "RECOVERY_IDENTITY_CONFLICT";
      return null;
    }
    if (this.receipt && stored) {
      try {
        requireValue(
          canonical(stored.request) === canonical(this.receipt.request) &&
            stored.request_digest === this.receipt.request_digest,
        );
        if (stored.checkpoint) {
          requireValue(this.receipt.checkpoint);
          compareCheckpoint(stored.checkpoint, this.receipt.checkpoint);
        }
      } catch {
        this.notice = "RECOVERY_IDENTITY_CONFLICT";
        return null;
      }
    }
    return { text: read.text, receipt: stored };
  }
  initialize(): Promise<void> {
    return (this.init ??= (async () => {
      const value = await this.inspect();
      if (value) {
        this.receipt = value.receipt;
        this.savedText = value.text;
        this.persisted = value.text !== null;
        if (value.receipt) this.epoch++;
      }
      this.initialized = true;
    })());
  }
  private async write(
    candidate: Receipt,
    preimage: string | null,
    initial = false,
  ): Promise<boolean> {
    const text = canonical(candidate);
    requireValue(utf8Length(text) <= 2048);
    const before = this.read();
    if (!before) return false;
    if (before.text !== preimage) {
      await this.inspect();
      if (!this.blocked) this.notice = "RECOVERY_IDENTITY_CONFLICT";
      return false;
    }
    // No await between preimage check and mutation. Storage is not a cross-tab CAS.
    try {
      this.storage.setItem(RECEIPT_KEY, text);
    } catch {
      /* classify actual readback */
    }
    const after = this.read();
    if (!after) return false;
    if (after.text === text) {
      this.savedText = text;
      this.persisted = true;
      this.notice = null;
      return true;
    }
    if (after.text === preimage || after.text === null) {
      this.savedText = after.text;
      this.persisted = after.text !== null;
      this.notice =
        initial && after.text === null
          ? "RECOVERY_MEMORY_ONLY"
          : "RECOVERY_CHECKPOINT_UNSAVED";
      return initial && after.text === null;
    }
    await this.inspect();
    if (!this.blocked) this.notice = "RECOVERY_IDENTITY_CONFLICT";
    return false;
  }
  async reserve(input: Request, selected: ScenarioVersion): Promise<boolean> {
    requireValue(this.canSubmit);
    this.reserving = true;
    try {
      const empty = await this.inspect();
      if (!empty || empty.receipt) {
        if (empty) this.notice = "RECOVERY_IDENTITY_CONFLICT";
        return false;
      }
      const request = parseRequest(input),
        original = await parseVersion(snapshot(selected, 8192));
      requireValue(
        original.id === request.scenario_id &&
          original.version === request.scenario_version &&
          original.digest === request.scenario_digest,
      );
      const r: Receipt = freeze({
        schema_version: 1,
        request,
        request_digest: await digest(request),
        checkpoint: null,
      });
      this.receipt = r;
      this.original = freeze(original);
      this.epoch++;
      this.resolved = false;
      return await this.write(r, null, true);
    } finally {
      this.reserving = false;
    }
  }
  async validate(input: Detail): Promise<Detail> {
    const epoch = this.epoch,
      r = this.receipt;
    requireValue(r);
    const detail = await parseDetail(input);
    requireValue(this.epoch === epoch && this.receipt === r);
    bindRequest(r.request, detail);
    if (this.original)
      requireValue(
        canonical(this.original) === canonical(detail.snapshot.scenario),
      );
    if (r.checkpoint) compareCheckpoint(r.checkpoint, checkpoint(detail));
    return detail;
  }
  async accept(input: Detail, resolve: boolean): Promise<void> {
    const epoch = this.epoch,
      detail = await this.validate(input);
    requireValue(this.receipt && this.epoch === epoch);
    this.receipt = freeze({ ...this.receipt, checkpoint: checkpoint(detail) });
    if (
      !this.blocked &&
      this.persisted &&
      this.notice !== "RECOVERY_CHECKPOINT_UNSAVED"
    )
      await this.write(this.receipt, this.savedText);
    if (resolve) {
      this.resolved = true;
      await this.clear();
    }
  }
  private retire() {
    this.receipt = null;
    this.original = null;
    this.savedText = null;
    this.persisted = false;
    this.notice = null;
    this.resolved = false;
    this.epoch++;
  }
  private async clear(): Promise<void> {
    if (this.blocked) return;
    const epoch = this.epoch,
      checked = await this.inspect();
    if (!checked || epoch !== this.epoch) return;
    const before = this.read();
    if (!before) return;
    if (before.text !== checked.text) {
      this.notice = "RECOVERY_IDENTITY_CONFLICT";
      return;
    }
    if (before.text === null) {
      this.retire();
      return;
    }
    try {
      this.storage.removeItem(RECEIPT_KEY);
    } catch {
      /* removal may have taken effect */
    }
    const after = this.read();
    if (!after) return;
    if (after.text === null) {
      this.retire();
      return;
    }
    if (after.text === checked.text) {
      this.notice = "RECOVERY_CLEAR_UNCONFIRMED";
      return;
    }
    await this.inspect();
    if (!this.blocked) this.notice = "RECOVERY_IDENTITY_CONFLICT";
  }
  async recheck(): Promise<void> {
    const checked = await this.inspect();
    if (!checked) return;
    if (!this.receipt) {
      this.receipt = checked.receipt;
      this.savedText = checked.text;
      this.persisted = checked.text !== null;
      this.notice = null;
      if (checked.receipt) this.epoch++;
      return;
    }
    this.notice = null;
    // Explicit recheck can save the strongest checkpoint, never discard it.
    await this.write(this.receipt, checked.text);
  }
}
