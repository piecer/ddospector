import { expect, it } from "vitest";
import { canonical } from "../scenarios/json";
import { parseReceipt } from "./receipt";
import { receiptFixture } from "./testFixtures";
it("roundtrips canonical bounded saved original commitment independently of S01 availability", async () => {
  const { r } = await receiptFixture();
  const text = canonical(r);
  expect(new TextEncoder().encode(text).length).toBeLessThanOrEqual(2048);
  expect(await parseReceipt(text)).toEqual(r);
  await expect(parseReceipt(" " + text)).rejects.toThrow();
  await expect(
    parseReceipt(canonical({ ...r, request_digest: "a".repeat(64) })),
  ).rejects.toThrow();
});
