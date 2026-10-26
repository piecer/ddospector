import { describe, expect, it } from "vitest";
import type { Target } from "../../lib/contracts";
import type { ScenarioInputValues } from "./scenario-grant-inputs";
import { definitionFromDraft, draftFromDefinition } from "../scenarios/draft";
import { definitionFixture } from "../scenarios/testFixtures";
import { recordFixture } from "../scenarios/testRecords";

const targets: Target[] = [
  {
    id: "dut-test",
    name: " DUT ",
    address: "lab.test",
    kind: "DUT",
    status: "draft",
    created_at: "2026-10-09T00:00:00+00:00",
  },
  {
    id: "sink-test",
    name: " Sink ",
    address: "::1",
    kind: "SINK",
    status: "draft",
    created_at: "2026-10-09T00:00:00+00:00",
  },
];
function filled() {
  const draft = inputs.newScenarioInputDraft();
  Object.assign(draft.values, {
    target_id: "dut-test",
    sink_id: "sink-test",
    dut_version: " firmware 🧪 ",
    policy_version: " policy ",
    max_pps: "1",
    max_bps: "1",
    max_packets: "1",
    max_bytes: "1",
    max_connections: "1",
    duration_seconds: "1",
    max_legitimate_loss_pct: "0",
    max_service_latency_ms: "1",
  });
  return draft;
}
const numericCases: [keyof ScenarioInputValues, number, number, boolean][] = [
  ["max_pps", 1, 1000000000, false],
  ["max_bps", 1, 1000000000000, false],
  ["max_packets", 1, 1000000000000, false],
  ["max_bytes", 1, 1000000000000, false],
  ["max_connections", 1, 1000000, false],
  ["duration_seconds", 1, 3600, false],
  ["max_legitimate_loss_pct", 0, 100, false],
  ["max_service_latency_ms", 1, 60000, false],
  ["max_cpu_pct", 1, 100, true],
  ["max_memory_pct", 1, 100, true],
  ["max_sessions", 1, 1000000, true],
];

// Discovery assertion makes the initial RED a missing-feature assertion, not an
// unresolved-import error. Once present, every test exercises the real module.
const modules = import.meta.glob("./scenario-grant-inputs.ts", { eager: true });
const inputs = modules[
  "./scenario-grant-inputs.ts"
] as typeof import("./scenario-grant-inputs");

describe("operator scenario inputs", () => {
  it("builds only protected inputs, preserving zero, nulls and literal declared versions", () => {
    const draft = filled();
    const result = inputs.buildScenarioInputResult(draft, targets);
    expect(result).toEqual({
      valid: true,
      input_source: {
        source: "operator",
        inputs: {
          target_id: "dut-test",
          sink_id: "sink-test",
          dut_version: " firmware 🧪 ",
          policy_version: " policy ",
          pcap_asset: null,
          traffic_budget: {
            max_pps: 1,
            max_bps: 1,
            max_packets: 1,
            max_bytes: 1,
            max_connections: 1,
            duration_seconds: 1,
          },
          stop_conditions: {
            max_legitimate_loss_pct: 0,
            max_service_latency_ms: 1,
            max_cpu_pct: null,
            max_memory_pct: null,
            max_sessions: null,
            management_loss: true,
          },
        },
      },
      resolved_inputs: expect.any(Object),
    });
    if (!result.valid || result.input_source.source !== "operator")
      throw Error("expected operator input");
    expect(result.resolved_inputs).toEqual(result.input_source.inputs);
    result.resolved_inputs.traffic_budget.max_pps = 999;
    expect(result.input_source.inputs.traffic_budget.max_pps).toBe(1);
    expect(draft.values.max_pps).toBe("1");
  });
  it.each(numericCases)(
    "validates canonical ASCII integer bounds for %s",
    (key, min, max, nullable) => {
      for (const raw of [String(min), String(max), ...(nullable ? [""] : [])]) {
        const draft = filled();
        draft.values[key] = raw;
        expect(
          inputs.buildScenarioInputResult(draft, targets).valid,
          `${key}=${JSON.stringify(raw)}`,
        ).toBe(true);
      }
      for (const raw of [
        String(min - 1),
        String(max + 1),
        "9007199254740992",
        "1.0",
        "1e0",
        "+1",
        "01",
        "-0",
        " 1",
        "1 ",
        "1\n",
        "1\t",
        "１",
        "١",
        "true",
        ...(nullable ? [] : [""]),
      ]) {
        const draft = filled();
        draft.values[key] = raw;
        expect(
          inputs.buildScenarioInputResult(draft, targets),
          `${key}=${JSON.stringify(raw)}`,
        ).toEqual({ valid: false, errors: [key] });
      }
    },
  );
  it.each(["target_id", "sink_id", "dut_version", "policy_version"] as const)(
    "reports missing or invalid %s without guessing",
    (key) => {
      for (const value of ["", " ", "x\n", "x\u0000"]) {
        const draft = filled();
        draft.values[key] = value;
        expect(inputs.buildScenarioInputResult(draft, targets)).toEqual({
          valid: false,
          errors: [key],
        });
      }
    },
  );
  it("requires current registered DUT and SINK kinds", () => {
    expect(inputs.buildScenarioInputResult(filled(), [])).toEqual({
      valid: false,
      errors: ["target_id", "sink_id"],
    });
    expect(
      inputs.buildScenarioInputResult(
        filled(),
        targets.map((t) => ({ ...t, kind: t.kind === "DUT" ? "SINK" : "DUT" })),
      ),
    ).toEqual({ valid: false, errors: ["target_id", "sink_id"] });
    const draft = filled();
    draft.values.sink_id = draft.values.target_id;
    expect(inputs.buildScenarioInputResult(draft, targets).valid).toBe(false);
  });
  it("rejects identical target/sink IDs even if supplied registry data duplicates an ID", () => {
    const draft = filled();
    draft.values.sink_id = draft.values.target_id;
    const duplicated = [targets[0], { ...targets[1], id: targets[0].id }];
    expect(inputs.buildScenarioInputResult(draft, duplicated)).toEqual({
      valid: false,
      errors: ["sink_id"],
    });
  });
  it("captures optional PCAP metadata only, with literal name and strict digest/size", () => {
    const draft = filled();
    draft.asset = true;
    Object.assign(draft.values, {
      asset_label: " <b>capture 🧪</b> ",
      asset_sha256: "a".repeat(64),
      asset_size_bytes: "67108864",
    });
    const result = inputs.buildScenarioInputResult(draft, targets);
    expect(result.valid && result.resolved_inputs.pcap_asset).toEqual({
      label: " <b>capture 🧪</b> ",
      sha256: "a".repeat(64),
      size_bytes: 67108864,
    });
    for (const [key, values] of [
      ["asset_label", ["", " ", "x\n", "x".repeat(121)]],
      [
        "asset_sha256",
        ["", "A".repeat(64), "a".repeat(63), "a".repeat(64) + "\n"],
      ],
      [
        "asset_size_bytes",
        [
          "",
          "0",
          "67108865",
          "9007199254740992",
          "1.0",
          "1e0",
          "01",
          " 1",
          "1\n",
        ],
      ],
    ] as const) {
      for (const value of values) {
        const invalid = structuredClone(draft);
        invalid.values[key] = value;
        expect(inputs.buildScenarioInputResult(invalid, targets)).toEqual({
          valid: false,
          errors: [key],
        });
      }
    }
    draft.values.asset_size_bytes = "1";
    expect(inputs.buildScenarioInputResult(draft, targets).valid).toBe(true);
    draft.asset = false;
    expect(inputs.buildScenarioInputResult(draft, targets)).toMatchObject({
      valid: true,
      resolved_inputs: { pcap_asset: null },
    });
  });
  it.each(["dut_version", "policy_version"] as const)(
    "counts Unicode codepoints without trimming %s",
    (key) => {
      const draft = filled();
      draft.values[key] = "🧪".repeat(120);
      expect(inputs.buildScenarioInputResult(draft, targets).valid).toBe(true);
      draft.values[key] += "🧪";
      expect(inputs.buildScenarioInputResult(draft, targets)).toEqual({
        valid: false,
        errors: [key],
      });
    },
  );
  it("captures an exact old immutable version and copies to a disjoint operator source", async () => {
    expect(
      inputs.scenarioInputDraftFromVersion,
      "explicit immutable-version capture",
    ).toBeTypeOf("function");
    expect(
      inputs.copyScenarioInputsToOperator,
      "explicit copy-to-edit",
    ).toBeTypeOf("function");
    const definition = definitionFixture();
    const record = await recordFixture(2, {
      id: "legacy-scenario",
      definition: {
        ...definition,
        pcap_asset: {
          label: " <script>literal</script> ",
          sha256: "b".repeat(64),
          size_bytes: 12,
        },
        stop_conditions: {
          ...definition.stop_conditions,
          max_legitimate_loss_pct: 0,
        },
      },
    });
    const before = structuredClone(record);
    const draft = inputs.scenarioInputDraftFromVersion(record);
    expect(record).toEqual(before);
    expect(draft.source).toBe("scenario_version");
    expect(draft.selection?.reference).toEqual({
      id: record.id,
      version: 2,
      digest: record.digest,
    });
    expect(Object.keys(draft.selection!.inputs).sort()).toEqual(
      [
        "target_id",
        "sink_id",
        "dut_version",
        "policy_version",
        "pcap_asset",
        "traffic_budget",
        "stop_conditions",
      ].sort(),
    );
    const result = inputs.buildScenarioInputResult(draft, targets);
    expect(result).toEqual({
      valid: true,
      input_source: {
        source: "scenario_version",
        reference: { id: record.id, version: 2, digest: record.digest },
      },
      resolved_inputs: draft.selection!.inputs,
    });
    record.definition.traffic_budget.max_pps = 999;
    record.definition.pcap_asset!.label = "changed";
    record.id = "changed";
    expect(draft.selection!.inputs.traffic_budget.max_pps).toBe(100);
    expect(draft.selection!.inputs.pcap_asset?.label).toBe(
      " <script>literal</script> ",
    );
    expect(draft.selection!.reference.id).toBe("legacy-scenario");
    if (!result.valid || result.input_source.source !== "scenario_version")
      throw Error("expected version source");
    result.input_source.reference.id = "changed-emission";
    result.resolved_inputs.traffic_budget.max_pps = 998;
    expect(draft.selection!.reference.id).toBe("legacy-scenario");
    expect(draft.selection!.inputs.traffic_budget.max_pps).toBe(100);
    const copied = inputs.copyScenarioInputsToOperator(draft)!;
    expect(copied.source).toBe("operator");
    expect(copied.values).toMatchObject({
      max_pps: "100",
      max_legitimate_loss_pct: "0",
      max_cpu_pct: "",
      asset_label: " <script>literal</script> ",
      asset_size_bytes: "12",
    });
    expect(inputs.buildScenarioInputResult(copied, targets)).toMatchObject({
      valid: true,
      input_source: { source: "operator" },
      resolved_inputs: draft.selection!.inputs,
    });
    expect(copied).not.toHaveProperty("selection");
    copied.values.max_pps = "3";
    expect(draft.selection!.inputs.traffic_budget.max_pps).toBe(100);
    expect(inputs.buildScenarioInputResult(draft, [])).toEqual({
      valid: false,
      errors: ["target_id", "sink_id"],
    });
    const empty = { source: "scenario_version" as const, selection: null };
    expect(inputs.buildScenarioInputResult(empty, targets)).toEqual({
      valid: false,
      errors: ["source"],
    });
    expect(inputs.copyScenarioInputsToOperator(empty)).toBeNull();
  });
  it("retains existing manual definition parsing", () => {
    const definition = {
      ...definitionFixture(),
      evidence_requirements: [
        "ingress_pcap",
        "egress_pcap",
        "service_probe",
      ] as const,
    };
    const manual = draftFromDefinition({
      ...definition,
      evidence_requirements: [...definition.evidence_requirements],
    });
    expect(definitionFromDraft(manual)).toEqual(definition);
    manual.values.max_pps = "1e2";
    expect(definitionFromDraft(manual)).toBeNull();
  });
  it("starts empty and incomplete with no numeric or identity defaults", () => {
    expect(
      inputs?.newScenarioInputDraft,
      "empty operator draft factory",
    ).toBeTypeOf("function");
    const draft = inputs.newScenarioInputDraft();
    expect(draft.source).toBe("operator");
    expect(draft.asset).toBe(false);
    expect(Object.values(draft.values).every((value) => value === "")).toBe(
      true,
    );
    expect(inputs.buildScenarioInputResult(draft, [])).toMatchObject({
      valid: false,
    });
    const other = inputs.newScenarioInputDraft();
    draft.values.max_pps = "123";
    expect(other.values.max_pps).toBe("");
  });
});
