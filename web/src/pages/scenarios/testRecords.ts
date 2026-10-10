import { execFileSync } from "node:child_process";
import { definitionFixture } from "./testFixtures";
import { digest } from "./json";
import type { ScenarioVersion } from "./types";
// TEST-ONLY records, using the real pinned catalog but NOT the pending S01 producer.
export async function recordFixture(
  version = 1,
  override: Record<string, unknown> = {},
): Promise<ScenarioVersion> {
  const profiles = JSON.parse(
    execFileSync(
      "../.venv/bin/python",
      [
        "-c",
        "import json; from aiddos.api.catalog import PROFILES_V1; print(json.dumps(PROFILES_V1, ensure_ascii=False))",
      ],
      { encoding: "utf8" },
    ),
  );
  const v = {
    id: "11111111-1111-4111-8111-111111111111",
    version,
    created_at: "2026-10-09T00:00:00+00:00",
    status: "definition",
    execution_enabled: false,
    definition: definitionFixture(),
    target_snapshot: {
      id: "dut-test",
      name: "DUT",
      address: "lab.test",
      kind: "DUT",
      status: "draft",
      created_at: "2026-10-09T00:00:00+00:00",
    },
    sink_snapshot: {
      id: "sink-test",
      name: "Sink",
      address: "::1",
      kind: "SINK",
      status: "draft",
      created_at: "2026-10-09T00:00:00+00:00",
    },
    profile_snapshot: profiles[0],
    catalog_version: "1.0.0",
    ...override,
  };
  return { ...v, digest: await digest(v) } as ScenarioVersion;
}
