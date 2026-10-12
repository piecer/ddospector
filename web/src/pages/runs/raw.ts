import { parseJSON } from "../scenarios/json";
export function rawJSON(bytes: Uint8Array, max: number): unknown {
  if (bytes.byteLength > max) throw new Error("Invalid run response.");
  const value = parseJSON(
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes),
  );
  function check(v: unknown): void {
    if (
      Object.is(v, -0) ||
      (typeof v === "string" && /[\uD800-\uDFFF]/u.test(v))
    )
      throw new Error("Invalid run response.");
    if (v && typeof v === "object") {
      Object.keys(v).forEach(check);
      Object.values(v).forEach(check);
    }
  }
  check(value);
  return value;
}
