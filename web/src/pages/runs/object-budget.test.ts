import { afterEach, expect, it, vi } from "vitest";
import * as json from "../scenarios/json";
import { snapshot } from "./object";
afterEach(() => vi.restoreAllMocks());
it("rejects a summed direct-object byte excess before allocating its canonical copy", () => {
  const canonical = vi.spyOn(json, "canonical");
  const value = { a: "x".repeat(900), b: "y".repeat(900) };
  expect(() => snapshot(value, 1024)).toThrow();
  expect(canonical).not.toHaveBeenCalled();
});
it("retains exact UTF8/escape/array byte boundary without charging array index property names", () => {
  const value = { a: ["한", "\n", '"', "🧪", 0, null, true] };
  const size = new TextEncoder().encode(json.canonical(value)).length;
  expect(snapshot(value, size)).toEqual(value);
  expect(() => snapshot(value, size - 1)).toThrow();
});
