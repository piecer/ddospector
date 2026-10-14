import { readFileSync } from "node:fs";
import { createHash, webcrypto } from "node:crypto";
import { spawnSync } from "node:child_process";
import { beforeAll, expect, it } from "vitest";
import { decodeDetail, decodeList, parseDetail, bindRun, wire } from "./codec";
import { canonical, digest } from "../scenarios/json";
import { parseDetail as parseRun } from "../runs/wire";
import { sampleCatalog, manifestSHA } from "./catalog";
const bytes = (n: string) =>
  new Uint8Array(readFileSync("../tests/fixtures/evidence/" + n));
const value = (n = "complete-detail.body") =>
  JSON.parse(new TextDecoder().decode(bytes(n)));
const encoded = (v: unknown) => new TextEncoder().encode(canonical(v));
beforeAll(() =>
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  }),
);
it("pins producer fixture and unchanged generator/catalog source bytes", () => {
  const origins = JSON.parse(
    readFileSync("../tests/fixtures/evidence/origins.json", "utf8"),
  ) as { file: string; sha256: string; bytes: number }[];
  for (const x of origins) {
    expect(createHash("sha256").update(bytes(x.file)).digest("hex")).toBe(
      x.sha256,
    );
    expect(bytes(x.file).length).toBe(x.bytes);
  }
  expect(
    createHash("sha256")
      .update(readFileSync("public/evidence-samples-v1/manifest.json"))
      .digest("hex"),
  ).toBe(manifestSHA);
  const code =
    'import hashlib,json; from aiddos.evidence.samples import SAMPLE_IDS,make_sample; print(json.dumps({s:{side:hashlib.sha256(getattr(make_sample(s),side)).hexdigest() for side in ("ingress","egress")} for s in SAMPLE_IDS}))';
  const p = spawnSync("../.venv/bin/python", ["-c", code], {
    cwd: process.cwd(),
    encoding: "utf8",
  });
  expect(p.status, p.stderr).toBe(0);
  const hashes = JSON.parse(p.stdout);
  for (const sample of sampleCatalog)
    for (const side of ["ingress", "egress"] as const) {
      const d = sample[side],
        raw = readFileSync("public/evidence-samples-v1/" + d.filename);
      expect(raw.length).toBe(d.size_bytes);
      expect(createHash("sha256").update(raw).digest("hex")).toBe(d.sha256);
      expect(hashes[sample.sample_id][side]).toBe(d.sha256);
    }
});
const mutations: [string, (d: ReturnType<typeof value>) => void][] = [
  ["unknown report field", (d) => (d.report.extra = 1)],
  ["missing report field", (d) => delete d.report.scope],
  ["report ID", (d) => (d.report.evidence_id = d.report.run_id)],
  ["foreign snapshot", (d) => (d.report.run_snapshot_digest = "0".repeat(64))],
  ["false scenario success", (d) => (d.report.scenario_evaluation = "PASS")],
  ["false defense success", (d) => (d.report.defense_verdict = "PASS")],
  ["bool count", (d) => (d.report.captures.ingress.packet_count = true)],
  [
    "invented missing count",
    (d) => (d.report.facts.unmatched_ingress_packets = 1),
  ],
  [
    "invented percentage",
    (d) => (d.report.facts.delivery_basis_points_floor = 9999),
  ],
  [
    "timestamp numeric type",
    (d) => (d.report.captures.ingress.first_timestamp_ns = 1),
  ],
  [
    "noncanonical timestamp string",
    (d) =>
      (d.report.captures.ingress.first_timestamp_ns = "01700000000000000000"),
  ],
  [
    "timestamp overflow",
    (d) =>
      (d.report.captures.ingress.last_timestamp_ns = "4294967296000000000"),
  ],
  ["invented wire bytes", (d) => d.report.captures.ingress.wire_bytes++],
  [
    "invented payload bytes",
    (d) => (d.report.captures.ingress.payload_bytes = 1000),
  ],
  [
    "invented parser error stats",
    (d) => (d.report.captures.ingress.parse_error = "PCAP_MALFORMED"),
  ],
  [
    "unknown parser error",
    (d) => (d.report.captures.egress.parse_error = "OTHER"),
  ],
  ["wrong sample", (d) => (d.report.sample_id = "violation")],
  ["false provenance", (d) => (d.report.provenance = "UNVERIFIED")],
  ["false coverage", (d) => (d.report.coverage = "UNKNOWN")],
  ["wrong issue", (d) => (d.report.issues = ["NO_INGRESS_RECORDS"])],
  ["missing requirement", (d) => (d.report.unassessed_requirements = [])],
  [
    "duplicate requirement",
    (d) => d.report.policy.evidence_requirements.push("ingress_pcap"),
  ],
  [
    "threshold out of range",
    (d) => (d.report.policy.minimum_delivery_pct = 101),
  ],
  ["policy mismatch", (d) => (d.report.policy.protocol = "HTTP")],
  ["state mismatch", (d) => (d.evidence.analysis_state = "REGISTERED")],
  ["false digest size", (d) => (d.evidence.ingress.size_bytes = 1)],
];
it.each(mutations)(
  "rejects declared mutated negative: %s even with recomputed self digest",
  async (_, mutate) => {
    const d = value();
    mutate(d);
    const { digest: _old, ...body } = d.report;
    void _old;
    d.report.digest = await digest(body);
    await expect(decodeDetail(encoded(d))).rejects.toThrow();
  },
);
it("uses dynamic threshold internals, not sample expectations (mutated policy consistency probe)", async () => {
  const d = value("violation-detail.body");
  d.report.policy.minimum_delivery_pct = 90;
  d.report.outcome = "SATISFIED";
  const { digest: _old, ...body } = d.report;
  void _old;
  d.report.digest = await digest(body);
  // This is a declared mutation, NOT a producer positive fixture or acceptance result.
  const consistent = await decodeDetail(encoded(d));
  expect(consistent.report?.outcome).toBe("SATISFIED");
  const run = await parseRun(value("run-before.body"));
  expect(() => bindRun(consistent, run)).toThrow();
});
it("rejects getter/hook/symbol/nonenumerable direct input without executing it", async () => {
  let called = 0;
  const d = value();
  Object.defineProperty(d.report, "extra", {
    get() {
      called++;
      return 1;
    },
    enumerable: true,
  });
  await expect(parseDetail(d)).rejects.toThrow();
  expect(called).toBe(0);
  const hidden = value();
  Object.defineProperty(hidden, "hidden", { value: 1 });
  await expect(parseDetail(hidden)).rejects.toThrow();
});
it("enforces 16/+1 cardinality, canonical lexical forms and exact/+1 raw envelope", () => {
  const list = value("full-list.body");
  list.items.push(list.items[0]);
  list.total = 17;
  expect(() => decodeList(encoded(list))).toThrow();
  for (const token of ["-0", "1.0", "1e0", "true"])
    expect(() =>
      decodeList(
        new TextEncoder().encode(
          '{"items":[],"schema_version":' + token + ',"total":0}',
        ),
      ),
    ).toThrow();
  expect(
    wire(new TextEncoder().encode('"' + "x".repeat(65534) + '"')),
  ).toBeTypeOf("string");
  expect(() =>
    wire(new TextEncoder().encode('"' + "x".repeat(65535) + '"')),
  ).toThrow();
});
