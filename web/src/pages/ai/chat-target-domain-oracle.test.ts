// Genuine unchanged domain TargetInput/Target oracle, NOT a B chat producer capture.
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, it, vi, afterEach } from "vitest";
import { toolClient } from "./chat-tool-client";
const addresses = [
  "192.0.2.1",
  "01.2.3.4",
  "123",
  "123.",
  "Example.COM.",
  "::",
  "::1",
  "2001:db8::1",
  "::ffff:192.0.2.1",
  "::ffff:01.2.3.4",
  "fe80::1%eth0",
  "1:2:3:4:5:6:7:8",
  "1:2:3:4:5:6:7",
  "1::2::3",
  "https://host",
  "[::1]",
  " host ",
  "bad\u0000host",
  "bad\u200dhost",
  "a".repeat(63) + ".test",
  "a".repeat(64) + ".test",
  "-bad.test",
  "a".repeat(63) +
    "." +
    "b".repeat(63) +
    "." +
    "c".repeat(63) +
    "." +
    "d".repeat(61) +
    ".",
];
const inputs = [
  ...addresses.map((address) => ({
    name: " Literal 🌍 ",
    address,
    kind: "DUT",
  })),
  ...["🌍".repeat(120), "🌍".repeat(121), "\u001c", "\u200b", " ", "123"].map(
    (name) => ({ name, address: "Example.COM.", kind: "SINK" }),
  ),
];
const timestamps = [
  "2026-10-18T10:00:00+09:00",
  "2026-W42-7T10:00:00+09:00",
  "20261018T100000+0900",
  "2026-10-18🌍10:00:00.123456+09:00",
  "2026-10-18T01:00:00.1234567Z",
];
const allInputs = [
  ...inputs,
  ...timestamps.map((created_at) => ({
    name: "dated",
    address: "host.test",
    kind: "DUT",
    created_at,
  })),
];
const rows = JSON.parse(
  execFileSync(
    resolve("../.venv/bin/python"),
    [
      "-c",
      `
import json,sys
from pathlib import Path
from aiddos.api.models import TargetInput,Target
import aiddos.api.models as m
assert Path(m.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
rows=[]
for v in json.load(sys.stdin):
 try:
  created_at=v.pop('created_at','2026-10-18T01:00:00Z')
  i=TargetInput.model_validate(v)
  t=Target(id='old-target',created_at=created_at,status='draft',**i.model_dump())
  rows.append({'accepted':True,'target':t.model_dump(mode='json')})
 except ValueError:
  rows.append({'accepted':False})
print(json.dumps(rows,ensure_ascii=False))
`,
      resolve("../src"),
    ],
    {
      input: JSON.stringify(allInputs),
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: resolve("../src") + ":" + resolve(".."),
        PYTHONDONTWRITEBYTECODE: "1",
      },
    },
  ),
) as { accepted: boolean; target?: unknown }[];
afterEach(() => vi.unstubAllGlobals());
it.each(allInputs.map((input, index) => ({ input, index })))(
  "literal domain producer → actual Response boundary $index",
  async ({ input, index }) => {
    const row = rows[index];
    const target = row.accepted
      ? row.target
      : {
          id: "old-target",
          ...input,
          status: "draft",
          created_at: "2026-10-18T01:00:00Z",
        };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              schema_version: 1,
              draft_revision: 0,
              targets: [target],
            }),
            { headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    if (row.accepted)
      expect((await toolClient.targets()).targets).toEqual([target]);
    else await expect(toolClient.targets()).rejects.toThrow();
  },
);
