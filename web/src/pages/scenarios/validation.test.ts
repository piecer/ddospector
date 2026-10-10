import { describe, expect, it } from "vitest";
import { definitionFixture } from "./testFixtures";
import { validDefinition as valid, scenarioText } from "./validation";
const text = (v: unknown, max = 120, multiline = false) =>
  scenarioText(v, max, multiline);
describe("S01 definition admission", () => {
  it("closes every structural object and enforces numeric and policy/evidence consistency", () => {
    const good = definitionFixture();
    for (const key of Object.keys(good)) {
      const missing: Record<string, unknown> = { ...good };
      delete missing[key];
      expect(valid(missing), key).toBe(false);
    }
    expect(valid({ ...good, extra: null })).toBe(false);
    for (const field of [
      "traffic_budget",
      "success_criteria",
      "stop_conditions",
    ] as const) {
      expect(valid({ ...good, [field]: { ...good[field], extra: 1 } })).toBe(
        false,
      );
      for (const key of Object.keys(good[field])) {
        const missing: Record<string, unknown> = { ...good[field] };
        delete missing[key];
        expect(valid({ ...good, [field]: missing }), key).toBe(false);
      }
    }
    for (const max_pps of [
      0,
      1e9 + 1,
      1.1,
      true,
      "1",
      NaN,
      Infinity,
      Number.MAX_SAFE_INTEGER + 1,
    ]) {
      expect(
        valid({ ...good, traffic_budget: { ...good.traffic_budget, max_pps } }),
      ).toBe(false);
    }
    for (const patch of [
      { target_id: "INVALID" },
      { sink_id: good.target_id },
      { protocol: "HTTP" },
      { ip_version: "4" },
      { expected_action: "BLOCK" },
      { expected_action: "ALERT" },
      { detection_required: 1 },
      { detection_required: true },
      { evidence_requirements: ["service_probe"] },
      {
        evidence_requirements: [...good.evidence_requirements, "service_probe"],
      },
      { evidence_requirements: [...good.evidence_requirements, null] },
      { stop_conditions: { ...good.stop_conditions, max_cpu_pct: 80 } },
      {
        pcap_asset: {
          label: "asset",
          sha256: "a".repeat(64) + "\n",
          size_bytes: 1,
        },
      },
      { target_id: "a".repeat(64) + "\n" },
      { pcap_asset: { label: "asset", sha256: "A".repeat(64), size_bytes: 1 } },
      {
        success_criteria: {
          ...good.success_criteria,
          minimum_delivery_pct: 101,
        },
      },
    ])
      expect(valid({ ...good, ...patch }), JSON.stringify(patch)).toBe(false);
    const alert = {
      ...good,
      expected_action: "ALERT",
      detection_required: true,
      success_criteria: { ...good.success_criteria, detection_deadline_ms: 1 },
      evidence_requirements: [
        ...good.evidence_requirements,
        "dut_events",
        "resource_metrics",
      ],
      stop_conditions: {
        ...good.stop_conditions,
        max_cpu_pct: 100,
        max_memory_pct: 1,
        max_sessions: 1000000,
      },
      pcap_asset: {
        label: " declared ",
        sha256: "a".repeat(64),
        size_bytes: 67108864,
      },
    };
    expect(valid(alert)).toBe(true);
    expect(
      valid({
        ...good,
        profile_id: "k6-http",
        protocol: "HTTP",
        evidence_requirements: ["service_probe"],
      }),
    ).toBe(true);
    expect(valid({ ...alert, profile_id: "k6-http", protocol: "HTTP" })).toBe(
      false,
    );
    expect(
      valid({
        ...good,
        expected_action: "BLOCK",
        delivery_expectation: "BLOCK",
        success_criteria: {
          ...good.success_criteria,
          minimum_delivery_pct: 0,
          maximum_delivery_pct: 5,
        },
      }),
    ).toBe(true);
  });
  it("rejects array holes, extra keys, accessors and hostile prototypes without invoking them", () => {
    const good = definitionFixture();
    let reads = 0;
    for (const change of [
      (roles: string[]) => {
        roles.length = 4;
      },
      (roles: string[]) => {
        Object.defineProperty(roles, "extra", { value: true });
      },
      (roles: string[]) => {
        Object.defineProperty(roles, "0", {
          get() {
            reads++;
            return "ingress_pcap";
          },
        });
      },
    ]) {
      const roles = [...good.evidence_requirements];
      change(roles);
      expect(valid({ ...good, evidence_requirements: roles })).toBe(false);
    }
    const getter = { ...good };
    Object.defineProperty(getter, "name", {
      get() {
        reads++;
        return good.name;
      },
    });
    expect(valid(getter)).toBe(false);
    const hidden = { ...good };
    Object.defineProperty(hidden, "extra", { value: null });
    expect(valid(hidden)).toBe(false);
    expect(valid(Object.assign(Object.create({ marker: true }), good))).toBe(
      false,
    );
    expect(reads).toBe(0);
  });
  it("accepts exact literal whitespace and codepoint limits, not AI trimming rules", () => {
    expect(valid(definitionFixture())).toBe(true);
    expect(text(" 🧪 ".repeat(40))).toBe(true);
    expect(text("🧪".repeat(120))).toBe(true);
    expect(text("🧪".repeat(121))).toBe(false);
    expect(text(" a\n\r\tb ", 2000, true)).toBe(true);
    for (const value of [
      "\u200b",
      " \u0085 ",
      "\ud800",
      "\nword",
      " ",
      "\u001c",
    ])
      expect(text(value)).toBe(false);
  });
});
