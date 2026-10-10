import { validAddress } from "../lab/validation";
import { canonical, digest, utf8Length } from "./json";
import { scenarioProfiles } from "./catalog";
import {
  denseArray,
  exact,
  identifier,
  integer,
  scenarioText,
  sha256,
  validDefinition,
} from "./validation";
import type { ScenarioHistory, ScenarioPage, ScenarioVersion } from "./types";
export function invalid(): never {
  throw new Error("Invalid scenario response.");
}
export const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
import { timestamp } from "./timestamp";
function target(v: unknown, id: string, kind: string): boolean {
  return (
    exact(v, ["id", "name", "address", "kind", "status", "created_at"]) &&
    v.id === id &&
    identifier(v.id) &&
    scenarioText(v.name, 120) &&
    typeof v.address === "string" &&
    validAddress(v.address) &&
    v.kind === kind &&
    v.status === "draft" &&
    timestamp(v.created_at)
  );
}
function profile(v: unknown, id: "tcpreplay-policy" | "k6-http"): boolean {
  if (
    !exact(v, ["id", "name", "description", "engine", "layer", "status"]) ||
    !exact(v.name, ["en", "ko"]) ||
    !exact(v.description, ["en", "ko"])
  )
    return false;
  return canonical(v) === canonical(scenarioProfiles[id]);
}
export async function parseVersion(v: unknown): Promise<ScenarioVersion> {
  if (
    !exact(v, [
      "id",
      "version",
      "created_at",
      "status",
      "execution_enabled",
      "definition",
      "target_snapshot",
      "sink_snapshot",
      "profile_snapshot",
      "catalog_version",
      "digest",
    ]) ||
    !uuid(v.id) ||
    !integer(v.version, 1, 10) ||
    !timestamp(v.created_at) ||
    v.status !== "definition" ||
    v.execution_enabled !== false ||
    v.catalog_version !== "1.0.0" ||
    !sha256(v.digest) ||
    !validDefinition(v.definition)
  )
    return invalid();
  if (
    !target(v.target_snapshot, v.definition.target_id, "DUT") ||
    !target(v.sink_snapshot, v.definition.sink_id, "SINK") ||
    !profile(v.profile_snapshot, v.definition.profile_id)
  )
    return invalid();
  if (utf8Length(canonical(v)) > 8192) return invalid();
  const { digest: expected, ...content } = v;
  if ((await digest(content)) !== expected) return invalid();
  return v as ScenarioVersion;
}
export async function parsePage(
  v: unknown,
  offset: number,
  limit: number,
): Promise<ScenarioPage> {
  if (
    !exact(v, [
      "revision",
      "total",
      "offset",
      "limit",
      "items",
      "execution_enabled",
    ]) ||
    !integer(v.revision, 0, 1000) ||
    !integer(v.total, 0, 100) ||
    v.offset !== offset ||
    v.limit !== limit ||
    !integer(v.offset, 0, 100) ||
    !integer(v.limit, 1, 100) ||
    v.execution_enabled !== false ||
    !denseArray(v.items, 0, 100) ||
    v.items.length !== Math.max(0, Math.min(limit, v.total - offset)) ||
    v.revision < v.total ||
    v.revision > v.total * 10
  )
    return invalid();
  const items = await Promise.all(v.items.map(parseVersion));
  if (new Set(items.map((item) => item.id)).size !== items.length)
    return invalid();
  const count = items.reduce((n, item) => n + item.version, 0),
    outside = v.total - items.length;
  if (v.revision < count + outside || v.revision > count + outside * 10)
    return invalid();
  return v as ScenarioPage;
}
export async function parseHistory(
  v: unknown,
  id: string,
): Promise<ScenarioHistory> {
  if (
    !exact(v, ["revision", "scenario_id", "versions", "execution_enabled"]) ||
    !integer(v.revision, 1, 1000) ||
    v.scenario_id !== id ||
    !identifier(id) ||
    v.execution_enabled !== false ||
    !denseArray(v.versions, 1, 10) ||
    v.revision < v.versions.length
  )
    return invalid();
  const records = await Promise.all(v.versions.map(parseVersion));
  if (
    !records.every(
      (record, index) => record.id === id && record.version === index + 1,
    )
  )
    return invalid();
  return v as ScenarioHistory;
}
