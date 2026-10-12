import { describe, expect, it } from "vitest";
import { rawJSON } from "./raw";
const bytes = (s: string) => new TextEncoder().encode(s);
describe("S02 lexical admission (synthetic negatives)", () => {
  it.each(["\ufeff{}", '{"x":"\\ud800"}', '{"\\udfff":0}'])(
    "rejects BOM/lone surrogate %s",
    (value) => {
      expect(() => rawJSON(bytes(value), 1024)).toThrow();
    },
  );
  it.each([
    '{"x":1,"\\u0078":2}',
    '{"x":1.0}',
    '{"x":1e0}',
    '{"x":9007199254740992}',
    '{"x":NaN}',
    "[".repeat(33) + "0" + "]".repeat(33),
  ])("rejects strict token %s", (value) => {
    expect(() => rawJSON(bytes(value), 1024)).toThrow();
  });
  it("honors exact UTF8 limit and rejects invalid UTF8", () => {
    const input = bytes('{"한":"글"}');
    expect(rawJSON(input, input.length)).toEqual({ 한: "글" });
    expect(() => rawJSON(input, input.length - 1)).toThrow();
    expect(() => rawJSON(new Uint8Array([0xff]), 1024)).toThrow();
    expect(rawJSON(bytes('{"text":"-0"}'), 1024)).toEqual({ text: "-0" });
  });
  it("rejects negative-zero before lossy integer decoding", () => {
    expect(() => rawJSON(bytes('{"count":-0}'), 1024)).toThrow();
  });
});
