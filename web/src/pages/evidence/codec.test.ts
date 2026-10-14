import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";
import { decodeDetail, decodeList, bindRun, validName } from "./codec";
import { parseDetail } from "../runs/wire";
import { canonical, digest } from "../scenarios/json";
export const bytes = (name: string) =>
  new Uint8Array(readFileSync(`../tests/fixtures/evidence/${name}`));
const json = (name: string) =>
  JSON.parse(new TextDecoder().decode(bytes(name)));
beforeAll(() =>
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  }),
);
describe("actual producer Evidence bytes", () => {
  it.each(["complete", "violation", "unknown"])(
    "decodes and snapshot-binds %s without fabricated positive data",
    async (id) => {
      const d = await decodeDetail(bytes(`${id}-detail.body`));
      const run = await parseDetail(json("run-before.body"));
      bindRun(d, run);
      expect(d.report?.outcome).toBe(
        { complete: "SATISFIED", violation: "VIOLATED", unknown: "UNKNOWN" }[
          id
        ],
      );
      expect(d.report?.captures.ingress.first_timestamp_ns).toBe(
        "1700000000000000000",
      );
    },
  );
  it("admits all 16 actual summaries and registered-null states", async () => {
    expect(decodeList(bytes("full-list.body")).items).toHaveLength(16);
    expect(
      (await decodeDetail(bytes("complete-registered.body"))).report,
    ).toBeNull();
  });
  it("rejects lexical aliases, duplicates, extras and mutated self-consistent false outcomes", async () => {
    const source = new TextDecoder().decode(bytes("complete-detail.body"));
    for (const s of [
      source.replace('"ordinal":1', '"ordinal":1.0'),
      source.replace('"ordinal":1', '"ordinal":true'),
      source.replace('"ordinal":1', '"ordinal":1,"ordinal":1'),
      source + " ",
      source.replace('"ordinal":1', '"extra":1,"ordinal":1'),
    ])
      await expect(decodeDetail(new TextEncoder().encode(s))).rejects.toThrow();
    const d = json("complete-detail.body");
    d.report.outcome = "VIOLATED";
    const { digest: _discard, ...content } = d.report;
    void _discard;
    d.report.digest = await digest(content);
    await expect(
      decodeDetail(new TextEncoder().encode(canonical(d))),
    ).rejects.toThrow();
  });
  it("applies literal filename boundaries", () => {
    for (const s of [
      " ",
      "x".repeat(128),
      "😀".repeat(64),
      "<script>x</script>",
    ])
      expect(validName(s)).toBe(true);
    for (const s of [
      "",
      "x".repeat(129),
      "😀".repeat(65),
      "x\u0085",
      "x\u202e",
      "x\u2069",
      "x\ud800",
    ])
      expect(validName(s)).toBe(false);
  });
});
