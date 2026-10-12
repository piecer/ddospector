import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { decodeResponse, type Context } from "./client";
import { RunError } from "./errors";
const directory = resolve(
  import.meta.dirname,
  "../../../../tests/fixtures/runs/parity",
);
const manifestBytes = readFileSync(resolve(directory, "manifest.json"));
const manifestSha256 = createHash("sha256").update(manifestBytes).digest("hex");
const cases = JSON.parse(manifestBytes.toString("utf8")) as {
  file: string;
  sha256: string;
  context: Context;
  expected: string;
  label: string;
}[];
it("same frozen actual H1 and labeled mutation bytes through shipped Node consumer", async () => {
  const results: { index: number; file: string; sha256: string; verdict: string }[] = [];
  let complete = false;
  try {
    expect(manifestSha256).toBe("acc596572800a936e7c319a3adcbe1cd6547f8968ca58c05757eb57cb69227c7");
    expect(cases).toHaveLength(5259);
    for (const entry of cases) {
      const bytes = readFileSync(resolve(directory, entry.file));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(entry.sha256);
      let verdict = "ACCEPT";
      try {
        await decodeResponse(bytes, entry.context);
      } catch (e) {
        verdict = e instanceof RunError ? e.code : "REJECT";
      }
      results.push({ index: results.length, file: entry.file,
        sha256: createHash("sha256").update(bytes).digest("hex"), verdict });
      expect(verdict, entry.file + " " + entry.label).toBe(entry.expected);
    }
    complete = true;
  } finally {
    if (process.env.I3_NODE_EVIDENCE) {
      writeFileSync(process.env.I3_NODE_EVIDENCE, JSON.stringify({
        schema_version: 1,
        execution_binding: process.env.I3_RUN_BINDING,
        cwd: process.cwd(),
        node: process.version,
        module: import.meta.filename,
        module_sha256: createHash("sha256").update(readFileSync(import.meta.filename)).digest("hex"),
        decoder_sha256: createHash("sha256").update(readFileSync(resolve(import.meta.dirname, "client.ts"))).digest("hex"),
        manifest_sha256: manifestSha256,
        count: cases.length,
        complete,
        results,
      }, null, 2) + "\n", { flag: "wx" });
    }
  }
});
