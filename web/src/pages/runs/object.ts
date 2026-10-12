import { canonical, utf8Length } from "../scenarios/json";
/** Validate original descriptors before copying. Never execute accessors/toJSON. */
export function snapshot<T = unknown>(value: T, max: number): T {
  let units = 0,
    bytes = 0;
  const seen = new Set<object>();
  const fail = (): never => {
    throw new Error("Invalid run response.");
  };
  function charge(size: number): void {
    bytes += size;
    if (bytes > max) fail();
  }
  function visit(v: unknown, depth: number): void {
    if (++units > max || depth > 32) fail();
    if (v === null || typeof v === "boolean") {
      charge(JSON.stringify(v).length);
      return;
    }
    if (typeof v === "string") {
      if (v.length > max || /[\uD800-\uDFFF]/u.test(v)) fail();
      charge(utf8Length(JSON.stringify(v)));
      return;
    }
    if (typeof v === "number") {
      if (!Number.isSafeInteger(v) || Object.is(v, -0)) fail();
      charge(JSON.stringify(v).length);
      return;
    }
    if (typeof v !== "object" || !v) fail();
    const obj = v as object;
    if (seen.has(obj)) fail();
    seen.add(obj);
    const array = Array.isArray(obj),
      proto = Object.getPrototypeOf(obj);
    if (
      array
        ? proto !== Array.prototype
        : proto !== Object.prototype && proto !== null
    )
      fail();
    const keys = Reflect.ownKeys(obj);
    if (keys.length > max) fail();
    if (array && keys.length !== (obj as unknown[]).length + 1) fail();
    charge(2);
    let entries = 0;
    for (const k of keys) {
      if (typeof k !== "string") fail();
      const d = Object.getOwnPropertyDescriptor(obj, k)!;
      if (array && k === "length") continue;
      if (!d.enumerable || !Object.hasOwn(d, "value")) fail();
      if (
        array &&
        (!/^(0|[1-9][0-9]*)$/.test(k as string) ||
          Number(k) >= (obj as unknown[]).length)
      )
        fail();
      if (entries++) charge(1);
      if (!array) {
        visit(k, depth + 1);
        charge(1);
      }
      visit(d.value, depth + 1);
    }
    seen.delete(obj);
  }
  visit(value, 0);
  const text = canonical(value);
  if (utf8Length(text) > max) fail();
  return JSON.parse(text) as T;
}
export function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}
