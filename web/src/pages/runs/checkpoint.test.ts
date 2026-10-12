import { expect, it } from "vitest";
import { rows, body } from "./testCorpus";
import { rawJSON } from "./raw";
import { parseDetail } from "./wire";
import { checkpoint, compareCheckpoint } from "./checkpoint";
it("holds terminal identity and exact equal-count checkpoint", async () => {
  const d = await parseDetail(
    rawJSON(body(rows.find((r) => r.state === "SUCCEEDED")!), 32768),
  );
  const old = checkpoint(d);
  expect(() => compareCheckpoint(old, old)).not.toThrow();
  for (const key of ["ordinal", "event_count", "generation"] as const) {
    const next = structuredClone(old);
    next.run[key]++;
    expect(() => compareCheckpoint(old, next)).toThrow();
  }
  const changed = structuredClone(old);
  changed.result_digest = "a".repeat(64);
  expect(() => compareCheckpoint(old, changed)).toThrow();
});
