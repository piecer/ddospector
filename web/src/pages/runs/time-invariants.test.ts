import { expect, it } from "vitest";
import { receiptFixture } from "./testFixtures";
import { parseSummary } from "./wire";
const later = (t: string, seconds: number) =>
  new Date(Date.parse(t) + seconds * 1000).toISOString().replace(/Z$/, "000Z");
it.each(["first-claim", "cancel-intent", "queued-cancel"])(
  "rejects inconsistent %s event timestamp rather than accepting an impossible summary",
  async (mode) => {
    const { d } = await receiptFixture(),
      created = d.run.created_at,
      t1 = later(created, 1),
      t2 = later(created, 2);
    const run = {
      ...d.run,
      state:
        mode === "first-claim"
          ? "RUNNING"
          : mode === "cancel-intent"
            ? "CANCEL_REQUESTED"
            : "CANCELLED",
      attempt: mode === "queued-cancel" ? 0 : 1,
      generation: mode === "queued-cancel" ? 0 : 1,
      event_count: mode === "cancel-intent" ? 3 : 2,
      started_at: mode === "queued-cancel" ? null : t1,
      updated_at: t2,
      cancel_requested_at: mode === "first-claim" ? null : t1,
      finished_at: mode === "queued-cancel" ? t2 : null,
    };
    expect(() => parseSummary(run)).toThrow();
  },
);
