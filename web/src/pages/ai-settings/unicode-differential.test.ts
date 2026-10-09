import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { casefold } from "./casefold";
import { idnaASCII } from "./idna";
import { forbiddenText, pythonSpace } from "./unicode-text";
import { validBaseURL } from "./validation";

const python = resolve(process.cwd(), "../.venv/bin/python");
const tools = resolve(process.cwd(), "src/pages/ai-settings/tools");
function oracle(mode: string) {
  return JSON.parse(
    execFileSync(python, [resolve(tools, "unicode_oracle.py"), mode], {
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
      timeout: 120000,
    }),
  );
}
it("has byte-fresh Unicode data generated only with project Python 3.12", () => {
  expect(
    execFileSync(python, [resolve(tools, "generate_unicode.py"), "--check"], {
      encoding: "utf8",
      timeout: 120000,
    }),
  ).toContain("checked idna-data.ts");
}, 120000);

it("matches every Unicode code point's real Python fold/text/IDNA semantics", () => {
  const expected = oracle("exhaustive");
  const fold = createHash("sha256");
  const text = createHash("sha256");
  const idna = createHash("sha256");
  let count = 0;
  for (let cp = 0; cp < 0x110000; cp++) {
    const c = String.fromCodePoint(cp);
    const folded = Array.from(casefold(c), (ch) =>
      ch.codePointAt(0)!.toString(16),
    ).join(".");
    fold.update(`${cp}:${folded}\n`);
    text.update(
      new Uint8Array([Number(forbiddenText(c)), Number(pythonSpace(c))]),
    );
    idna.update(`${cp}:${idnaASCII(c) ?? "<null>"}\n`);
    count++;
  }
  expect({
    count,
    fold: fold.digest("hex"),
    text: text.digest("hex"),
    idna: idna.digest("hex"),
  }).toEqual(expected);
}, 120000);

it("matches cross-character Nameprep and URL/IPv4/IPv6 authority differentials", () => {
  const expected = oracle("corpus") as {
    hosts: [string, string | null][];
    urls: [string, boolean][];
  };
  const mismatchedHosts = expected.hosts.filter(
    ([host, encoded]) => idnaASCII(host) !== encoded,
  );
  const mismatchedURLs = expected.urls.filter(
    ([url, accepted]) => validBaseURL(url) !== accepted,
  );
  expect(mismatchedHosts.slice(0, 20)).toEqual([]);
  expect(mismatchedURLs.slice(0, 20)).toEqual([]);
  console.info(
    `Differential corpus: ${expected.hosts.length} IDNA hosts, ${expected.urls.length} AIBaseURL values`,
  );
}, 120000);
