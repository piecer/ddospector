import type { Target, TargetInput } from "../../lib/contracts";
import { timestamp as domainTimestamp } from "../scenarios/timestamp";
import { check, identifier, object, text } from "./chat-tool-wire";
// Literal syntax only; do not use URL/WHATWG IP normalization or form trimming.
function ipv4(value: string) {
  const parts = value.split(".");
  return (
    parts.length === 4 &&
    parts.every((p) => /^(0|[1-9][0-9]{0,2})$/.test(p) && Number(p) <= 255)
  );
}
function ipv6(value: string) {
  if (!value.includes(":")) return false;
  let address = value;
  if (address.includes(".")) {
    const pos = address.lastIndexOf(":");
    if (!ipv4(address.slice(pos + 1))) return false;
    address = address.slice(0, pos + 1) + "0:0";
  }
  const halves = address.split("::");
  if (halves.length > 2) return false;
  const parts = halves.flatMap((h) => (h === "" ? [] : h.split(":")));
  return (
    parts.every((p) => /^[0-9a-fA-F]{1,4}$/.test(p)) &&
    (halves.length === 2 ? parts.length < 8 : parts.length === 8)
  );
}
export function parseAddress(value: unknown): string {
  text(value, 255);
  check(typeof value === "string" && !value.includes("%"));
  if (ipv4(value) || ipv6(value)) return value;
  const hostname = value.endsWith(".") ? value.slice(0, -1) : value;
  check(
    hostname.length <= 253 &&
      !/^[0-9.]+$/.test(hostname) &&
      hostname
        .split(".")
        .every((p) =>
          /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(p),
        ),
  );
  return value;
}
export function parseTargetInput(value: unknown): TargetInput {
  const t = object(value, "name address kind");
  text(t.name, 120);
  parseAddress(t.address);
  check(t.kind === "DUT" || t.kind === "SINK");
  return value as TargetInput;
}
export function parseTarget(value: unknown): Target {
  const t = object(value, "id name address kind status created_at");
  identifier(t.id);
  check(domainTimestamp(t.created_at));
  check(t.status === "draft");
  parseTargetInput({ name: t.name, address: t.address, kind: t.kind });
  return value as Target;
}
