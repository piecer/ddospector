import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Context } from "./client";

export const normalWireRoot = resolve(import.meta.dirname, "../../../..");
const bytes = readFileSync(resolve(normalWireRoot, "tests/fixtures/runs/normal-wire.json"));
assert.equal(createHash("sha256").update(bytes).digest("hex"),
  "fea7985c0351fd9368b3a109f736341f61dabc2c3d2b092a1d5d4aa7d7b91e51");
type Row = {
  label: string;
  raw: string;
  sha256: string;
  context: Context;
  expected: "ACCEPT" | "REJECT";
  provenance: "RECORDED_ASGI_HTTP" | "SYNTHETIC_CONSUMER_NEGATIVE";
};
const fixture = JSON.parse(bytes.toString("utf8")) as {
  schema_version: number;
  producer_source_sha256: Record<string, string>;
  cases: Row[];
};
assert.equal(fixture.schema_version, 1);
for (const [path, hash] of Object.entries(fixture.producer_source_sha256)) {
  assert(!path.split("/").includes("..") &&
    (path.startsWith("src/") || ["pyproject.toml", "uv.lock"].includes(path)));
  assert.equal(createHash("sha256").update(readFileSync(resolve(normalWireRoot, path))).digest("hex"),
    hash, `Producer source changed: ${path}; do not silently regenerate this recorded corpus.`);
}
assert.equal(fixture.cases.length, 51);
assert.equal(fixture.cases.filter(r => r.provenance === "RECORDED_ASGI_HTTP").length, 12);
assert.equal(new Set(fixture.cases.map(r => r.label)).size, fixture.cases.length);
for (const row of fixture.cases) {
  assert.equal(createHash("sha256").update(Buffer.from(row.raw, "utf8")).digest("hex"), row.sha256);
}
export const normalWireCases = fixture.cases;
