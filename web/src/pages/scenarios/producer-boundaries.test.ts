// Differential checks use the installed Python producer's existing validators.
// Synthetic candidates are test-only, not S01 API producer acceptance samples.
import { execFileSync } from "node:child_process";
import { expect, it } from "vitest";
import { scenarioText, validDefinition } from "./validation";
import { timestamp } from "./timestamp";
import { definitionFixture } from "./testFixtures";
import { scenarioProfiles } from "./catalog";
it("preserves Python Name/Goal codepoint and control classification at text boundaries", () => {
  const values = [
    "",
    " ",
    " \n\t ",
    " before ",
    "🧪".repeat(120),
    "🧪".repeat(121),
    "한".repeat(2000),
    "한".repeat(2001),
    "a\r\nb\t",
    "\ud800",
    "\udfff",
    "a\u2028b",
    "a\u2029b",
  ];
  for (const cp of [
    0, 9, 10, 13, 28, 32, 127, 133, 160, 173, 1536, 6158, 8203, 8239, 8288,
    12288, 65279, 0x1f9ea, 0x10ffff,
  ])
    values.push(
      String.fromCodePoint(cp),
      "a" + String.fromCodePoint(cp),
      String.fromCodePoint(cp) + "a",
    );
  const oracle = JSON.parse(
    execFileSync(
      "../.venv/bin/python",
      [
        "-c",
        "import json,sys; from pydantic import TypeAdapter; from aiddos.api.validation import Name,Goal\ndef valid(t,v):\n try: TypeAdapter(t).validate_python(v); return True\n except ValueError: return False\nprint(json.dumps([[valid(Name,v),valid(Goal,v)] for v in json.load(sys.stdin)]))",
      ],
      { input: JSON.stringify(values), encoding: "utf8" },
    ),
  ) as boolean[][];
  values.forEach((value, i) => {
    expect(scenarioText(value, 120), JSON.stringify(value)).toBe(oracle[i][0]);
    expect(scenarioText(value, 2000, true), JSON.stringify(value)).toBe(
      oracle[i][1],
    );
  });
});
it("matches the Python Timestamp adapter across calendar/week/clock/offset forms", () => {
  const stamps: string[] = [];
  for (const date of [
    "2026-10-09",
    "20261009",
    "2026-W41-5",
    "2026W415",
    "2026-W41",
    "2026W41",
    "2020-W53-7",
    "2026-W53-1",
    "0001-01-01",
    "9999-W52-7",
  ])
    for (const separator of ["T", " ", "🧪", "-"])
      for (const clock of [
        "12:34:56",
        "123456",
        "12:34",
        "12.5",
        "12:34:56,1234567",
        "24:00:00",
        "12:60:00",
      ])
        for (const zone of [
          "Z",
          "+00:00",
          "+00:60",
          "-23:59:59.99",
          "+24:00",
          "+01",
        ])
          stamps.push(date + separator + clock + zone);
  const oracle = JSON.parse(
    execFileSync(
      "../.venv/bin/python",
      [
        "-c",
        "import json,sys; from pydantic import TypeAdapter; from aiddos.api.models import Timestamp\na=TypeAdapter(Timestamp)\ndef valid(v):\n try:a.validate_python(v);return True\n except ValueError:return False\nprint(json.dumps([valid(v) for v in json.load(sys.stdin)]))",
      ],
      { input: JSON.stringify(stamps), encoding: "utf8" },
    ),
  ) as boolean[];
  stamps.forEach((stamp, i) => expect(timestamp(stamp), stamp).toBe(oracle[i]));
});
it("pins both complete catalog profiles to the real Python catalog", () => {
  const catalog = JSON.parse(
    execFileSync(
      "../.venv/bin/python",
      [
        "-c",
        "import json;from aiddos.api.catalog import PROFILES_V1;print(json.dumps(PROFILES_V1))",
      ],
      { encoding: "utf8" },
    ),
  ) as (typeof scenarioProfiles)[keyof typeof scenarioProfiles][];
  for (const profile of Object.values(scenarioProfiles))
    expect(profile).toEqual(catalog.find((p) => p.id === profile.id));
});
it("covers the action/delivery/detection/profile/protocol/evidence truth table", () => {
  const roles = [
    "ingress_pcap",
    "egress_pcap",
    "dut_events",
    "service_probe",
    "resource_metrics",
  ];
  for (const expected_action of ["ALLOW", "BLOCK", "ALERT"])
    for (const delivery_expectation of ["ALLOW", "BLOCK"])
      for (const detection_required of [false, true])
        for (const profile_id of ["tcpreplay-policy", "k6-http"])
          for (const protocol of ["TCP", "UDP", "DNS", "HTTP"])
            for (let mask = 0; mask < 32; mask++) {
              const evidence_requirements = roles.filter(
                (_, i) => mask & (1 << i),
              );
              const d = {
                ...definitionFixture(),
                expected_action,
                delivery_expectation,
                detection_required,
                profile_id,
                protocol,
                evidence_requirements,
                success_criteria: {
                  minimum_delivery_pct:
                    delivery_expectation === "BLOCK" ? 0 : 95,
                  maximum_delivery_pct:
                    delivery_expectation === "BLOCK" ? 5 : 100,
                  detection_deadline_ms: detection_required ? 500 : null,
                },
              };
              const expected =
                (profile_id === "k6-http"
                  ? protocol === "HTTP"
                  : protocol !== "HTTP") &&
                (expected_action === "ALERT"
                  ? detection_required
                  : expected_action === delivery_expectation) &&
                evidence_requirements.includes("service_probe") &&
                (profile_id !== "tcpreplay-policy" ||
                  (evidence_requirements.includes("ingress_pcap") &&
                    evidence_requirements.includes("egress_pcap"))) &&
                (!detection_required ||
                  evidence_requirements.includes("dut_events"));
              expect(validDefinition(d), JSON.stringify(d)).toBe(expected);
            }
});
