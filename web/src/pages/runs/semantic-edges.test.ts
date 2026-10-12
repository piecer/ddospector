import { expect, it } from "vitest";
import { receiptFixture } from "./testFixtures";
import { parseEvents } from "./pages";
import { decodeResponse } from "./client";
it("synthetic negative: claimed extra committed event after a terminal page prefix", async () => {
  const { d } = await receiptFixture();
  const page = {
    schema_version: 1,
    run_id: d.run.id,
    after: 0,
    limit: 2,
    total: 3,
    next_after: 2,
    items: [
      {
        seq: 1,
        at: d.run.created_at,
        type: "QUEUED",
        state: "QUEUED",
        attempt: 0,
        generation: 0,
        reason: null,
      },
      {
        seq: 2,
        at: d.run.created_at,
        type: "CANCELLED",
        state: "CANCELLED",
        attempt: 0,
        generation: 0,
        reason: "BEFORE_CLAIM",
      },
    ],
  };
  expect(() => parseEvents(page, d.run.id, 0, 2)).toThrow();
});
it("synthetic negative: timeout event before observed admission plus 300 seconds", async () => {
  const { d } = await receiptFixture();
  const page = {
    schema_version: 1,
    run_id: d.run.id,
    after: 0,
    limit: 16,
    total: 2,
    next_after: null,
    items: [
      {
        seq: 1,
        at: d.run.created_at,
        type: "QUEUED",
        state: "QUEUED",
        attempt: 0,
        generation: 0,
        reason: null,
      },
      {
        seq: 2,
        at: d.run.created_at,
        type: "TIMED_OUT",
        state: "TIMED_OUT",
        attempt: 0,
        generation: 0,
        reason: "DEADLINE_EXCEEDED",
      },
    ],
  };
  expect(() => parseEvents(page, d.run.id)).toThrow();
});
it("synthetic negative: new-create 202 cannot masquerade as a later requeued identity", async () => {
  const { d } = await receiptFixture();
  const detail = {
    ...d,
    run: {
      ...d.run,
      attempt: 1,
      generation: 2,
      event_count: 3,
      started_at: d.run.created_at,
    },
  };
  await expect(
    decodeResponse(new TextEncoder().encode(JSON.stringify(detail)), {
      kind: "create",
      method: "POST",
      status: 202,
    }),
  ).rejects.toThrow();
});
