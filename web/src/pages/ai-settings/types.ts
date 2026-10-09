export type AIProtocol = "anthropic" | "openai" | "openai-responses";
export type RetryRule = { attempts: number; interval_ms: number };
export type AIModelProfile = {
  id: string;
  name: string;
  format: AIProtocol;
  model: string;
  base_url: string;
  credential_env: string;
  rate_per_second: number;
  rate_per_minute: number;
  context_window_k: number;
  streaming: boolean;
  max_tokens: number;
  max_tokens_field: "" | "max_completion_tokens";
  thinking_type: "" | "disabled" | "enabled";
  reasoning_effort: "" | "low" | "medium" | "high" | "xhigh" | "max";
  retry: { connect: RetryRule; empty: RetryRule; stream: RetryRule };
};
export type AISettingsInput = {
  revision: number;
  profiles: AIModelProfile[];
  default_profile_id: string | null;
  agent_profile_id: string | null;
};
export type AISettingsSnapshot = AISettingsInput & {
  updated_at: string | null;
  execution_enabled: false;
  connection_status: "not_tested";
};
