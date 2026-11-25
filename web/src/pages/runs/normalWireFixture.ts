import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { validateNormalWire, type NormalWireFixture } from "./normalWireProof";

export const normalWireRoot = resolve(import.meta.dirname, "../../../..");
const historical = readFileSync(resolve(normalWireRoot, "tests/fixtures/runs/normal-wire.json"));
assert.equal(createHash("sha256").update(historical).digest("hex"),
  "e3ee5b76d6a180d3a6d61462174c695989c444adc2f4bdb9c11a94d0aca47922");
const p0a = readFileSync(resolve(normalWireRoot, "tests/fixtures/runs/normal-wire-p0a.json"));
assert.equal(createHash("sha256").update(p0a).digest("hex"),
  "04fa85bd80ea052efb35c1fea781fe8dac01095da36addbc95fc1bca947877d2");
const bytes = readFileSync(resolve(normalWireRoot, "tests/fixtures/runs/normal-wire-current.json"));
assert.equal(createHash("sha256").update(bytes).digest("hex"),
  "3b51502ae23d7a4df061f81a81c2c6fa7dc9fa81aeac9e16e708ff631443a631");
const paths = ["pyproject.toml", "uv.lock", "tests/api/scenario_producer.py",
  "tests/runs/phase1_probe.py", "tools/s02_harness.py", "tools/s02_web_probe.py",
  "tools/normal_wire.py", "tools/normal_wire_observer/sitecustomize.py"];
function enumerate(directory: string) {
  for (const entry of readdirSync(resolve(normalWireRoot, directory), { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) enumerate(path);
    else if (entry.isFile() && /\.(py|sql)$/.test(path)) paths.push(path);
  }
}
enumerate("src");
const sources = Object.fromEntries(paths.sort().map(path => [path,
  createHash("sha256").update(readFileSync(resolve(normalWireRoot, path))).digest("hex"),
]));
export const normalWireCases = validateNormalWire(JSON.parse(bytes.toString("utf8")) as
  NormalWireFixture, JSON.parse(historical.toString("utf8")), sources);
