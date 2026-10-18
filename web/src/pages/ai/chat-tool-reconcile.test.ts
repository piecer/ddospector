import { expect, it } from "vitest";
import * as wire from "./chat-tool-wire";
import { call, cid, drid, fence } from "./chat-tool-test-fixtures";
const api = wire as unknown as {
  parseFence(v: unknown): typeof fence;
  reconcileFence(a: unknown, b: unknown): unknown;
  parseReconcile(v: unknown): unknown;
  reconcileTranscript(a: unknown, b: unknown): unknown;
};
it("fence A / clear A / fence B rejects stale clear A and contradictory equal generations", () => {
  const a = { ...fence, generation: 1, fenced: true, call_ids: [cid] };
  const clearA = { ...fence, generation: 2 };
  const b = { ...a, generation: 3 };
  expect(api.reconcileFence(api.parseFence(a), api.parseFence(clearA))).toEqual(
    clearA,
  );
  expect(api.reconcileFence(clearA, b)).toEqual(b);
  expect(() => api.reconcileFence(b, clearA)).toThrow();
  expect(() =>
    api.reconcileFence(b, { ...b, fenced: false, call_ids: [] }),
  ).toThrow();
  expect(api.reconcileFence(b, { ...b, current_draft_revision: 3 })).toEqual({
    ...b,
    current_draft_revision: 3,
  });
  expect(() => api.parseFence({ ...a, call_ids: [] })).toThrow();
  expect(() => api.parseFence({ ...fence, generation: true })).toThrow();
  expect(
    api.parseReconcile({
      schema_version: 1,
      request_id: drid,
      acknowledged_call_ids: [cid],
      generation: 2,
      write_fenced: false,
      prior_outcomes: "remain_uncertain",
    }),
  ).toBeTruthy();
});
it("transcript monotonicity retains immutable terminal calls and exact identity/proposals/decisions", () => {
  const a = { schema_version: 1, turn_id: drid, revision: 1, calls: [call] };
  const b = {
    ...a,
    revision: 2,
    calls: [
      {
        ...call,
        status: "cancelled",
        finished_at: call.started_at,
        error_code: "CHAT_CANCELLED",
      },
    ],
  };
  expect(api.reconcileTranscript(a, b)).toEqual(b);
  for (const next of [
    a,
    { ...b, revision: 3, calls: [call] },
    { ...b, revision: 3, calls: [] },
    { ...b, turn_id: cid },
    { ...b, calls: [{ ...b.calls[0], args_digest: "a".repeat(64) }] },
  ])
    expect(() => api.reconcileTranscript(b, next)).toThrow();
});
