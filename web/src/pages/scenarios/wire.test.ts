import { execFileSync } from "node:child_process";
import { expect, it } from "vitest";
import { canonical, digest } from "./json";
import { parseVersion as parse, parsePage, parseHistory } from "./wire";
import { recordFixture } from "./testRecords";
it("accepts Python canonical bytes with embedded history independent of current targets", async () => {
  const record = await recordFixture();
  const serialized = execFileSync(
    "../.venv/bin/python",
    [
      "-c",
      'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False), end="")',
    ],
    { input: JSON.stringify(record), encoding: "utf8" },
  );
  expect(canonical(record)).toBe(serialized);
  expect(await parse(JSON.parse(serialized))).toEqual(record);
});
it("matches the existing Python timezone-aware timestamp grammar rather than guessing browser Date rules", async () => {
  for (const stamp of [
    "2026-10-09 12:34:56+00:00",
    "20261009T123456+00:00",
    "2026-W41-5T12:34:56+00:00",
    "2026-10-09🧪12:34:56+00:00",
    "2026-10-09T12:34:56,123456789+05:30:15.12",
    "2026-10-09T12:34:56+00:60",
    "2026-10-09T12:34:56+24:00",
    "2026-02-29T12:34:56+00:00",
    "2026-10-09T25:34:56+00:00",
  ]) {
    const allowed =
      execFileSync(
        "../.venv/bin/python",
        [
          "-c",
          'import sys; from pydantic import TypeAdapter; from aiddos.api.models import Timestamp\ntry: TypeAdapter(Timestamp).validate_python(sys.argv[1]); print("yes")\nexcept ValueError: print("no")',
          stamp,
        ],
        { encoding: "utf8" },
      ).trim() === "yes";
    const record = await recordFixture(1, { created_at: stamp });
    if (allowed) expect(await parse(record), stamp).toEqual(record);
    else await expect(parse(record), stamp).rejects.toThrow();
  }
});
it("rejects mismatched digests, snapshots, exact catalog, fields and record bytes", async () => {
  const good = await recordFixture();
  for (const patch of [
    { digest: "0".repeat(64) },
    { version: 11 },
    { status: "draft" },
    { execution_enabled: true },
    { extra: null },
    { id: "not-a-uuid" },
    { target_snapshot: { ...good.target_snapshot, id: "foreign" } },
    { sink_snapshot: { ...good.sink_snapshot, kind: "DUT" } },
    {
      target_snapshot: {
        ...good.target_snapshot,
        created_at: "2026-02-30T00:00:00Z",
      },
    },
    { profile_snapshot: { ...good.profile_snapshot, layer: "L7" } },
    { catalog_version: "2.0.0" },
  ]) {
    const v = { ...good, ...patch };
    if (!("digest" in patch)) {
      const { digest: ignored, ...rest } = v;
      void ignored;
      v.digest = await digest(rest);
    }
    await expect(parse(v), JSON.stringify(patch)).rejects.toThrow();
  }
  const large = await recordFixture(1, {
    definition: { ...good.definition, objective: "🧪".repeat(2000) },
  });
  await expect(parse(large)).rejects.toThrow();
});
it("validates exact page counts and chronological histories, allowing newer registry revisions", async () => {
  const one = await recordFixture(),
    two = await recordFixture(2);
  const history = {
    revision: 3,
    scenario_id: one.id,
    versions: [one, two],
    execution_enabled: false,
  };
  expect(await parseHistory(history, one.id)).toEqual(history);
  const page = {
    revision: 2,
    total: 1,
    offset: 0,
    limit: 50,
    items: [two],
    execution_enabled: false,
  };
  expect(await parsePage(page, 0, 50)).toEqual(page);
  for (const versions of [[], [two], [one, one], [two, one]])
    await expect(
      parseHistory({ ...history, versions }, one.id),
    ).rejects.toThrow();
  for (const patch of [
    { revision: 0 },
    { revision: 11 },
    { total: 2 },
    { limit: 49 },
    { extra: true },
    { items: [two, two] },
  ])
    await expect(parsePage({ ...page, ...patch }, 0, 50)).rejects.toThrow();
});
