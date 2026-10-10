const invalid = (): never => {
  throw new Error("Invalid scenario JSON.");
};
/** Lexical admission before JSON.parse: duplicate decoded keys and integer tokens. */
export function parseJSON(source: string): unknown {
  let i = 0;
  const ws = () => {
    while (i < source.length && /[ \r\n\t]/.test(source[i])) i++;
  };
  const string = (): string => {
    const start = i++;
    while (i < source.length) {
      if (source[i] === '"') {
        i++;
        return JSON.parse(source.slice(start, i)) as string;
      }
      if (source[i] === "\\") i++;
      i++;
    }
    return invalid();
  };
  const value = (depth: number): void => {
    ws();
    const c = source[i];
    if (c === "{" || c === "[") {
      if (depth >= 32) invalid();
      const object = c === "{",
        end = object ? "}" : "]";
      const keys = new Set<string>();
      i++;
      ws();
      if (source[i] === end) {
        i++;
        return;
      }
      while (i < source.length) {
        if (object) {
          ws();
          if (source[i] !== '"') invalid();
          const key = string();
          if (keys.has(key)) invalid();
          keys.add(key);
          ws();
          if (source[i++] !== ":") invalid();
        }
        value(depth + 1);
        ws();
        if (source[i] === end) {
          i++;
          return;
        }
        if (source[i++] !== ",") invalid();
      }
      invalid();
    } else if (c === '"') string();
    else if (c === "-" || (c >= "0" && c <= "9")) {
      const token = /^-?(?:0|[1-9][0-9]*)/.exec(source.slice(i))?.[0];
      if (!token || !Number.isSafeInteger(Number(token))) invalid();
      i += token!.length;
      if (/[.eE0-9]/.test(source[i] ?? "")) invalid();
    } else {
      const token = /^(?:true|false|null)/.exec(source.slice(i))?.[0];
      if (!token) invalid();
      i += token!.length;
    }
  };
  value(0);
  ws();
  if (i !== source.length) invalid();
  return JSON.parse(source) as unknown;
}
/** Only admitted closed S01 data: ASCII keys, integer numbers, literal Unicode. */
export function canonical(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string")
    return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value))
    return String(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (typeof value === "object" && value !== null)
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map(
          (key) =>
            JSON.stringify(key) +
            ":" +
            canonical((value as Record<string, unknown>)[key]),
        )
        .join(",") +
      "}"
    );
  return invalid();
}
export const utf8Length = (text: string): number =>
  new TextEncoder().encode(text).byteLength;
export async function digest(value: unknown): Promise<string> {
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonical(value)),
  );
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
