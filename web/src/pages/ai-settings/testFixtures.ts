import type { AIModelProfile, AISettingsSnapshot } from "./types";
export const empty = (): AISettingsSnapshot => ({
  revision: 0,
  profiles: [],
  default_profile_id: null,
  agent_profile_id: null,
  updated_at: null,
  execution_enabled: false,
  connection_status: "not_tested",
});
export const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
export function profile(
  overrides: Partial<AIModelProfile> = {},
): AIModelProfile {
  return {
    id: "llm-test",
    name: "Review model",
    format: "openai",
    model: "manual-model-id",
    base_url: "https://models.example.test/v1",
    credential_env: "REVIEW_API_KEY",
    rate_per_second: 0,
    rate_per_minute: 0,
    context_window_k: 0,
    streaming: true,
    max_tokens: 0,
    max_tokens_field: "",
    thinking_type: "",
    reasoning_effort: "",
    retry: {
      connect: { attempts: 0, interval_ms: 0 },
      empty: { attempts: 0, interval_ms: 0 },
      stream: { attempts: 0, interval_ms: 0 },
    },
    ...overrides,
  };
}
