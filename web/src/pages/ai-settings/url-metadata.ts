import { idnaASCII } from "./idna";
import { URL_DELIMITERS } from "./text-data";
import { forbiddenText, inRanges, pythonSpace } from "./unicode-text";

function ipv4(host: string): boolean {
  const parts = host.split(".");
  return (
    parts.length === 4 &&
    parts.every(
      (part) => /^(?:0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255,
    )
  );
}
function ipv6(host: string): boolean {
  // Embedded IPv4 has exactly the strict dotted-decimal grammar of ipaddress.
  if (host.includes(".")) {
    const end = host.lastIndexOf(":");
    if (end < 0 || !ipv4(host.slice(end + 1))) return false;
    host = host.slice(0, end + 1) + "0:0";
  }
  const halves = host.split("::");
  if (halves.length > 2) return false;
  const groups = halves.flatMap((part) => (part ? part.split(":") : []));
  if (!groups.every((part) => /^[a-fA-F0-9]{1,4}$/.test(part))) return false;
  return halves.length === 2 ? groups.length < 8 : groups.length === 8;
}
function hostname(raw: string): boolean {
  const encoded = idnaASCII(raw);
  if (encoded === null) return false;
  if (ipv4(encoded)) return true;
  const host = encoded.endsWith(".") ? encoded.slice(0, -1) : encoded;
  // Numeric-only invalid addresses are NOT historical WHATWG IPv4 shorthand.
  return (
    host.length <= 253 &&
    !/^[0-9.]+$/.test(host) &&
    host
      .split(".")
      .every((label) =>
        /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label),
      )
  );
}
export function validBaseURL(value: string): boolean {
  if (!value) return true;
  const chars = Array.from(value);
  if (
    chars.length > 512 ||
    chars.some((c) => forbiddenText(c) || pythonSpace(c)) ||
    /[\\?#]/.test(value)
  )
    return false;
  // Metadata grammar mirrors AIBaseURL: urlsplit + syntactic IDNA/address.
  // Never pass it through WHATWG URL (which reinterprets DNS labels as IPv4),
  // and never return a normalized replacement for the operator's literal text.
  const authority = /^https?:\/\/([^/]+)/i.exec(value)?.[1];
  if (
    !authority ||
    /[@%]/.test(authority) ||
    Array.from(authority).some((c) =>
      inRanges(c.codePointAt(0)!, URL_DELIMITERS),
    )
  )
    return false;
  const parts = authority.startsWith("[")
    ? /^\[([^\]]+)\](?::([0-9]+))?$/.exec(authority)
    : /^([^:]+)(?::([0-9]+))?$/.exec(authority);
  if (
    !parts ||
    (parts[2] !== undefined &&
      !(Number(parts[2]) >= 1 && Number(parts[2]) <= 65535))
  )
    return false;
  return authority.startsWith("[") ? ipv6(parts[1]) : hostname(parts[1]);
}
