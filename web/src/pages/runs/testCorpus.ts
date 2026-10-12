import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { expect } from "vitest";
const corpusRoot = resolve(
  import.meta.dirname,
  "../../../../tests/fixtures/runs/h1",
);
export const rows = JSON.parse(
  readFileSync(resolve(corpusRoot, "selected-index.json"), "utf8"),
) as {
  body: string;
  sha256: string;
  method: string;
  path: string;
  status: number;
  state: string | null;
  provenance: string;
}[];
export function body(row: (typeof rows)[number]) {
  const bytes = readFileSync(resolve(corpusRoot, row.body));
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(row.sha256);
  return bytes;
}
