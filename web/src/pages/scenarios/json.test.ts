import { expect, it } from "vitest";
import { parseJSON as parse, canonical, digest } from "./json";
it("rejects duplicate decoded keys, noninteger tokens and excessive nesting before materialization", () => {
  for (const raw of [
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"a":{"x":1,"x":1}}',
    '{"n":1.0}',
    '{"n":1e0}',
    '{"n":1E+0}',
    '{"n":9007199254740992}',
    "[".repeat(33) + "0" + "]".repeat(33),
  ]) {
    expect(() => parse(raw), raw).toThrow();
  }
  expect(parse('{"a":[1,-1,0,true,null,"a\\t🧪"]}')).toEqual({
    a: [1, -1, 0, true, null, "a\t🧪"],
  });
  expect(parse("[".repeat(32) + "0" + "]".repeat(32))).toBeDefined();
});
it("matches Python ensure_ascii=False canonical UTF-8 serialization and SHA256", async () => {
  const value = { z: "<>&  ", a: [" 🧪 ", "\b\f\n\r\t", 1000000000000, null] };
  const expected =
    '{"a":[" 🧪 ","\\b\\f\\n\\r\\t",1000000000000,null],"z":"<>&  "}';
  expect(canonical(value)).toBe(expected);
  // Independent crypto implementation; the actual Python bytes are checked in wire.test.ts.
  const { createHash } = await import("node:crypto");
  expect(await digest(value)).toBe(
    createHash("sha256").update(expected, "utf8").digest("hex"),
  );
});
