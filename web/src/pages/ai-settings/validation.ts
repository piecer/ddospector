import type { AIModelProfile } from "./types";
import { casefold } from "./casefold";
import { literalText as literal } from "./unicode-text";
import { validBaseURL } from "./url-metadata";
export { validBaseURL } from "./url-metadata";
export function integer(
  value: unknown,
  min: number,
  max: number,
): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= min &&
    value <= max
  );
}
export function profileIssue(
  profile: AIModelProfile,
  others: AIModelProfile[] = [],
): string | null {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(profile.id)) return "id";
  if (
    !literal(profile.name, 120) ||
    others.some(
      (p) => p.id !== profile.id && casefold(p.name) === casefold(profile.name),
    )
  )
    return "name";
  if (!literal(profile.model, 200)) return "model";
  if (!validBaseURL(profile.base_url)) return "base_url";
  if (
    profile.credential_env !== "" &&
    !/^[A-Z][A-Z0-9_]{0,63}$/.test(profile.credential_env)
  )
    return "credential_env";
  for (const key of [
    "rate_per_second",
    "rate_per_minute",
    "max_tokens",
  ] as const)
    if (!integer(profile[key], 0, 1_000_000)) return key;
  if (
    !integer(profile.context_window_k, 0, 1000) ||
    (profile.context_window_k !== 0 && profile.context_window_k < 32)
  )
    return "context_window_k";
  for (const layer of ["connect", "empty", "stream"] as const) {
    if (!integer(profile.retry[layer].attempts, -1, 20))
      return `retry.${layer}.attempts`;
    if (!integer(profile.retry[layer].interval_ms, 0, 3_600_000))
      return `retry.${layer}.interval_ms`;
  }
  return null;
}
