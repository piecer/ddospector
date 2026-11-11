import { expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { validateNormalWire, type NormalWireFixture } from "./normalWireProof";

const root = resolve(import.meta.dirname, "../../../..");
const current = JSON.parse(readFileSync(resolve(root,
  "tests/fixtures/runs/normal-wire-current.json"), "utf8")) as NormalWireFixture;
const legacy = JSON.parse(readFileSync(resolve(root,
  "tests/fixtures/runs/normal-wire.json"), "utf8")) as NormalWireFixture;

it("accepts the retained actual capture graph and preserves both input corpora", () => {
  const before = JSON.stringify([current, legacy]);
  expect(validateNormalWire(current, legacy, current.producer_source_sha256)).toEqual(current.cases);
  expect(JSON.stringify([current, legacy])).toBe(before);
});

const faults: [string, string[], unknown][] = [
  ["failed probe", ["proof", "probe_exit"], 1],
  ["SQL readback incomplete", ["proof", "report", "stored_result_matches_http"], false],
  ["foreign report", ["proof", "report", "run_id"], "foreign"],
  ["failed selected worker", ["proof", "workers", "selected", "code"], 69],
  ["succeeded refusal", ["proof", "workers", "repeat", "code"], 0],
  ["live worker", ["proof", "workers", "selected", "absent"], false],
  ["timed out worker", ["proof", "workers", "selected", "timed_out"], true],
  ["foreign pid", ["proof", "origins", "selected", "pid"], -1],
  ["foreign start", ["proof", "origins", "selected", "identity", "start_ticks"], "foreign"],
  ["foreign checkout", ["proof", "origins", "selected", "root"], "/foreign"],
  ["missing origin", ["proof", "origins", "probe"], null],
  ["unretired children", ["proof", "native", "clean"], false],
  ["unretired PostgreSQL", ["proof", "pg", "state"], "OWNED"],
  ["missing cleanup journal", ["proof", "pg", "journal"], []],
  ["synthetic origin", ["origin", "transport"], "SIMULATED"],
  ["missing proof", ["proof"], null],
];
it.each(faults)("refuses %s before treating corpus as current", (_, path, replacement) => {
  const changed = structuredClone(current);
  let parent = changed as unknown as Record<string, unknown>;
  for (const key of path.slice(0, -1)) parent = parent[key] as Record<string, unknown>;
  parent[path.at(-1)!] = replacement;
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});

it("refuses source inventory omissions rather than checking only supplied pins", () => {
  const changed = structuredClone(current);
  delete changed.producer_source_sha256["tests/api/scenario_producer.py"];
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});
it("refuses newly added runtime sources absent from the captured inventory", () => {
  expect(() => validateNormalWire(current, legacy, {
    ...current.producer_source_sha256, "src/aiddos/new-source.py": "0".repeat(64),
  })).toThrow();
});
it("refuses changed source bytes", () => {
  expect(() => validateNormalWire(current, legacy, {
    ...current.producer_source_sha256, "src/aiddos/api/app.py": "0".repeat(64),
  })).toThrow();
});
it("refuses reordered positive rows", () => {
  const changed = structuredClone(current);
  [changed.cases[0], changed.cases[1]] = [changed.cases[1], changed.cases[0]];
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});
it("preserves every historical negative row", () => {
  const changed = structuredClone(current);
  changed.cases[12].expected = "ACCEPT";
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});
it("rejects modified raw response bytes", () => {
  const changed = structuredClone(current);
  changed.cases[0].raw += " ";
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});

const object = (value: unknown) => value as Record<string, unknown>;
it.each(["missing native origins", "foreign run argv", "wrong module path", "native errors",
  "false volume absence", "missing raw hashes"])("rejects review reproduction: %s", fault => {
  validateNormalWire(current, legacy, current.producer_source_sha256);
  const changed = structuredClone(current), proof = object(changed.proof);
  const native = object(proof.native), origins = object(proof.origins);
  if (fault === "missing native origins") delete native.origins;
  else if (fault === "foreign run argv") {
    const selected = object(object(proof.workers).selected);
    const pid = String(object(selected.identity).pid);
    const argv = object(object(native.origins)[pid]).argv as string[];
    argv[argv.length - 1] = "foreign-run";
  } else if (fault === "wrong module path") {
    object(object(origins.selected).modules)["aiddos.runs.worker"] = {
      path: "tools/normal_wire.py", sha256: current.producer_source_sha256["tools/normal_wire.py"],
    };
  } else if (fault === "native errors") (native.errors as unknown[]).push("retirement unconfirmed");
  else if (fault === "false volume absence") {
    const entry = (object(proof.pg).journal as Record<string, unknown>[])
      .find(e => e.event === "volume_absence_readback")!;
    entry.stderr = "Cannot connect to the Docker daemon";
  } else delete proof.artifacts;
  expect(() => validateNormalWire(changed, legacy, current.producer_source_sha256)).toThrow();
});
