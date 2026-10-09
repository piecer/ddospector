import type {
  AIModelProfile,
  AISettingsInput,
  AISettingsSnapshot,
} from "./types";
import { integer, profileIssue } from "./validation";
import { casefold } from "./casefold";
function exact(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.hasOwn(value, key))
  );
}
const inputKeys = [
  "revision",
  "profiles",
  "default_profile_id",
  "agent_profile_id",
];
const profileKeys = [
  "id",
  "name",
  "format",
  "model",
  "base_url",
  "credential_env",
  "rate_per_second",
  "rate_per_minute",
  "context_window_k",
  "streaming",
  "max_tokens",
  "max_tokens_field",
  "thinking_type",
  "reasoning_effort",
  "retry",
];
function validProfile(value: unknown): value is AIModelProfile {
  if (!exact(value, profileKeys)) return false;
  for (const key of ["id", "name", "model", "base_url", "credential_env"])
    if (typeof value[key] !== "string") return false;
  if (
    !["anthropic", "openai", "openai-responses"].includes(
      value.format as string,
    ) ||
    typeof value.streaming !== "boolean"
  )
    return false;
  if (
    !["", "max_completion_tokens"].includes(value.max_tokens_field as string) ||
    (value.max_tokens_field !== "" && value.format !== "openai")
  )
    return false;
  if (
    !["", "disabled", "enabled"].includes(value.thinking_type as string) ||
    !["", "low", "medium", "high", "xhigh", "max"].includes(
      value.reasoning_effort as string,
    )
  )
    return false;
  if (!exact(value.retry, ["connect", "empty", "stream"])) return false;
  for (const rule of Object.values(value.retry))
    if (
      !exact(rule, ["attempts", "interval_ms"]) ||
      !integer(rule.attempts, -1, 20) ||
      !integer(rule.interval_ms, 0, 3_600_000)
    )
      return false;
  return profileIssue(value as AIModelProfile) === null;
}
function settings(
  value: Record<string, unknown>,
  maxRevision: number,
): boolean {
  if (
    !integer(value.revision, 0, maxRevision) ||
    !Array.isArray(value.profiles) ||
    value.profiles.length > 20 ||
    !value.profiles.every(validProfile)
  )
    return false;
  const ids = new Set(value.profiles.map((p) => p.id));
  const names = new Set(value.profiles.map((p) => casefold(p.name)));
  if (
    ids.size !== value.profiles.length ||
    names.size !== value.profiles.length
  )
    return false;
  return [value.default_profile_id, value.agent_profile_id].every(
    (id) => id === null || (typeof id === "string" && ids.has(id)),
  );
}
export function assertSettingsInput(
  value: unknown,
): asserts value is AISettingsInput {
  if (!exact(value, inputKeys) || !settings(value, Number.MAX_SAFE_INTEGER - 1))
    throw new Error("Invalid AI settings replacement.");
}
export function parseSettingsSnapshot(value: unknown): AISettingsSnapshot {
  if (
    !exact(value, [
      ...inputKeys,
      "updated_at",
      "execution_enabled",
      "connection_status",
    ]) ||
    !settings(value, Number.MAX_SAFE_INTEGER) ||
    value.execution_enabled !== false ||
    value.connection_status !== "not_tested"
  )
    throw new Error("Invalid AI settings response.");
  if (
    value.updated_at !== null &&
    (typeof value.updated_at !== "string" ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
        value.updated_at,
      ) ||
      !Number.isFinite(Date.parse(value.updated_at)))
  )
    throw new Error("Invalid AI settings timestamp.");
  return value as AISettingsSnapshot;
}
