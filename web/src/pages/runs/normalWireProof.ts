import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import type { Context } from "./client";

export type NormalWireRow = {
  label: string;
  raw: string;
  sha256: string;
  context: Context;
  expected: "ACCEPT" | "REJECT";
  provenance: "RECORDED_ASGI_HTTP" | "SYNTHETIC_CONSUMER_NEGATIVE";
};
export type NormalWireFixture = {
  schema_version: number;
  scope: string;
  producer_source_sha256: Record<string, string>;
  origin: unknown;
  proof: unknown;
  cases: NormalWireRow[];
};

const object = (value: unknown): Record<string, unknown> => {
  assert(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as Record<string, unknown>;
};
const array = (value: unknown): unknown[] => {
  assert(Array.isArray(value));
  return value;
};
const keys = (value: object, expected: string[]) =>
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort());
const workerExits: Record<string, number> = {
  selected: 0, repeat: 69, "previous-attempt": 69, "unresolved-lease": 69,
};

function validateProof(value: NormalWireFixture, sources: Record<string, string>) {
  const origin = object(value.origin);
  keys(origin, ["transport", "legacy_sha256", "probe"]);
  assert.equal(origin.transport, "IN_PROCESS_ASGI_HTTP");
  assert.equal(origin.legacy_sha256,
    "e3ee5b76d6a180d3a6d61462174c695989c444adc2f4bdb9c11a94d0aca47922");
  assert.equal(origin.probe, "tests/runs/phase1_probe.py");
  const proof = object(value.proof);
  keys(proof, ["probe_exit", "probe_process", "report", "workers", "worker_starts",
    "origins", "native", "pg", "artifacts"]);
  assert.equal(proof.probe_exit, 0);
  const report = object(proof.report), terminal = JSON.parse(value.cases[10].raw);
  const artifacts = object(proof.artifacts);
  keys(artifacts, ["captured-wire.json", "result.json"]);
  for (const [name, parsed] of [["captured-wire.json", value.cases.slice(0, 12)],
    ["result.json", report]] as const) {
    const artifact = object(artifacts[name]);
    keys(artifact, ["raw", "sha256"]);
    assert(typeof artifact.raw === "string");
    assert.equal(createHash("sha256").update(Buffer.from(artifact.raw, "utf8")).digest("hex"),
      artifact.sha256);
    assert.deepEqual(JSON.parse(artifact.raw), parsed);
  }
  assert.equal(report.kind, "REAL_PRIVATE_PG_ASGI_HTTP_SEPARATE_ONESHOT_WORKER");
  assert.equal(report.state, "SUCCEEDED");
  assert.equal(report.attempt, 1);
  assert.equal(report.run_id, terminal.run.id);
  assert.deepEqual(report.detail, terminal);
  for (const key of ["other_run_untouched", "repeat_refused", "stored_result_matches_http"])
    assert.equal(report[key], true);
  assert.equal(report.previous_attempt_refused, "VALID_SQL_SEEDED_REQUEUED_FIXTURE");
  assert.equal(report.unresolved_lease_refused, "REAL_CLAIM_WITHOUT_COMPUTATION");
  assert.deepEqual(report.source, Object.fromEntries(Object.entries(sources)
    .filter(([path]) => path.startsWith("src/") && path.endsWith(".py"))));
  const workers = object(proof.workers), origins = object(proof.origins);
  const starts = object(proof.worker_starts), process = object(proof.probe_process);
  keys(workers, Object.keys(workerExits));
  keys(starts, Object.keys(workerExits));
  keys(origins, ["probe", ...Object.keys(workerExits)]);
  const native = object(proof.native), identities = array(native.identities);
  keys(native, ["clean", "remaining", "identities", "origins", "signals",
    "reaped_descendants", "remaining_direct_children", "errors", "pidfds_closed"]);
  assert.equal(native.clean, true);
  assert.deepEqual(native.remaining, []);
  for (const key of ["errors", "remaining_direct_children", "signals"])
    assert.deepEqual(native[key], []);
  assert.equal(native.pidfds_closed, true);
  const executions = object(native.origins);
  const root = object(origins.probe).root;
  assert(typeof root === "string");
  const probeIdentity = object(object(origins.probe).identity);
  assert.equal(process.actual_exit, proof.probe_exit);
  assert.equal(process.forced, false);
  for (const key of ["log_pipes_closed", "reaped", "absent", "stdout_closed", "stderr_closed"])
    assert.equal(process[key], true);
  for (const key of ["pid", "start_ticks", "boot_id"])
    assert.equal(process[key], probeIdentity[key]);
  assert.equal(process.cwd, root);
  const probeArgv = array(process.argv);
  assert.equal(probeArgv.length, 3);
  assert.equal(probeArgv[1], `${root}/tests/runs/phase1_probe.py`);
  const pids = new Set<unknown>();
  for (const [role, raw] of Object.entries(origins)) {
    const observation = object(raw), identity = object(observation.identity);
    assert.equal(observation.root, root);
    assert.equal(observation.pid, identity.pid);
    assert(identities.some(item => {
      const actual = object(item);
      return actual.pid === identity.pid && actual.start_ticks === identity.start_ticks &&
        actual.boot_id === identity.boot_id;
    }));
    pids.add(identity.pid);
    const execution = object(executions[String(identity.pid)]);
    assert.equal(execution.cwd, root);
    assert.deepEqual(execution.argv, role === "probe" ? probeArgv : object(starts[role]).argv);
    const modules = object(observation.modules);
    const required = role === "probe" ? ["aiddos.api.app", "scenario_producer"] :
      ["aiddos.runs.worker", "aiddos.runs.offline"];
    for (const name of required) assert(Object.hasOwn(modules, name));
    for (const [name, rawModule] of Object.entries(modules)) {
      const module = object(rawModule);
      assert.equal(typeof module.path, "string");
      assert(Object.hasOwn(sources, module.path as string));
      assert.equal(module.sha256, sources[module.path as string]);
      const stem = `src/${name.replaceAll(".", "/")}`;
      assert((name === "scenario_producer" ? ["tests/api/scenario_producer.py"] :
        [`${stem}.py`, `${stem}/__init__.py`]).includes(module.path as string));
    }
    if (role !== "probe") {
      const worker = object(workers[role]);
      assert.equal(worker.code, workerExits[role]);
      assert.equal(worker.absent, true);
      assert.equal(worker.timed_out, false);
      assert.deepEqual(worker.identity, identity);
      const start = object(starts[role]);
      keys(start, ["identity", "argv"]);
      assert.deepEqual(start.identity, identity);
      const argv = array(start.argv);
      assert.equal(argv.length, 5);
      assert.deepEqual(argv.slice(0, 4), [probeArgv[0], "-m", "ddospector.runs.worker", "--run-id"]);
      assert(typeof argv[4] === "string" &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(argv[4]));
      assert.equal(argv[4] === report.run_id, role === "selected" || role === "repeat");
    }
  }
  assert.equal(pids.size, 5);
  const pg = object(proof.pg), journal = array(pg.journal).map(object);
  assert.equal(pg.state, "CLEAN");
  assert.equal(journal[0].backend_kind, "docker");
  const registrations = journal.filter(e => e.event === "registered");
  assert.equal(registrations.length, 1);
  const registered = registrations[0], clean = journal.at(-1)!;
  assert.equal(clean.event, "clean");
  assert.equal(clean.cid, registered.cid);
  assert.deepEqual(clean.volume, registered.volume);
  assert.equal(object(registered.metadata).NetworkMode, "none");
  assert.deepEqual(object(registered.metadata).PortBindings, {});
  assert(journal.some(e => e.event === "container_absent" && e.cid === clean.cid));
  const volumeReads = journal.filter(e => e.event === "volume_absence_readback");
  assert.equal(volumeReads.length, 1);
  assert.equal(volumeReads[0].code, 1);
  assert.equal(volumeReads[0].timed_out, false);
  assert.deepEqual(volumeReads[0].volume, clean.volume);
  assert(typeof volumeReads[0].stdout === "string" && volumeReads[0].stdout.trim() === "");
  assert(typeof volumeReads[0].stderr === "string");
  assert.equal(volumeReads[0].stderr.trim(),
    `Error response from daemon: get ${object(clean.volume).Name}: no such volume`);
}

export function validateNormalWire(
  value: NormalWireFixture,
  legacy: { cases: NormalWireRow[] },
  sources: Record<string, string>,
): NormalWireRow[] {
  keys(value, ["schema_version", "scope", "producer_source_sha256", "origin", "proof", "cases"]);
  assert.equal(value.schema_version, 2);
  assert.deepEqual(value.producer_source_sha256, sources, "Producer source inventory changed");
  assert.equal(value.cases.length, 51);
  assert.equal(value.cases.filter(r => r.provenance === "RECORDED_ASGI_HTTP").length, 12);
  assert.equal(new Set(value.cases.map(r => r.label)).size, 51);
  assert.deepEqual(value.cases.slice(0, 12).map(r => r.label), [
    "list-0", "create-1", "detail-2", "events-3", "cancel-4", "events-5",
    "request-6", "list-7", "detail-8", "events-9", "detail-10", "events-11",
  ]);
  assert.deepEqual(value.cases.slice(12),
    legacy.cases.filter(r => r.provenance === "SYNTHETIC_CONSUMER_NEGATIVE"));
  for (const row of value.cases) {
    keys(row, ["label", "raw", "sha256", "context", "expected", "provenance"]);
    assert.equal(createHash("sha256").update(Buffer.from(row.raw, "utf8")).digest("hex"), row.sha256);
  }
  for (const row of value.cases.slice(0, 12)) {
    assert.equal(row.expected, "ACCEPT");
    assert.equal(row.provenance, "RECORDED_ASGI_HTTP");
  }
  validateProof(value, sources);
  return value.cases;
}
