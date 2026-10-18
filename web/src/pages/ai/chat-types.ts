export const chatCodes = [
  "CHAT_INVALID_REQUEST",
  "CHAT_NOT_CONFIGURED",
  "CHAT_UNSUPPORTED_PROFILE",
  "CHAT_UNSUPPORTED_OPTIONS",
  "CHAT_BINDING_CHANGED",
  "CHAT_IDEMPOTENCY_CONFLICT",
  "CHAT_SEQUENCE_CONFLICT",
  "CHAT_RETENTION_FULL",
  "CHAT_CONTEXT_LIMIT",
  "CHAT_CURSOR_INVALID",
  "CHAT_NOT_FOUND",
  "CHAT_BUSY",
  "CHAT_BODY_TOO_LARGE",
  "CHAT_STORAGE_ERROR",
  "CHAT_COMMIT_UNCERTAIN",
  "CHAT_SHUTTING_DOWN",
  "CHAT_PROVIDER_ERROR",
  "CHAT_PROVIDER_PROTOCOL",
  "CHAT_OUTPUT_LIMIT",
  "CHAT_TIMEOUT",
  "CHAT_EMPTY_RESPONSE",
  "CHAT_INTERRUPTED",
  "CHAT_CANCELLED",
  "CHAT_TOOL_GRANT_CONFLICT",
  "CHAT_TOOL_GRANT_INVALID",
  "CHAT_TOOL_APPROVAL_CONFLICT",
  "CHAT_TOOL_CONFLICT",
  "CHAT_TOOL_WRITE_FENCED",
  "CHAT_TOOL_DENIED",
  "CHAT_TOOL_LIMIT",
  "CHAT_TOOL_PROTOCOL",
  "CHAT_TOOL_UNCERTAIN",
] as const;
export type ChatSession = {
  schema_version: 1;
  id: string;
  request_id: string;
  settings_revision: number;
  profile_id: string;
  model: string;
  endpoint: string;
  streaming: boolean;
  locale: "en" | "ko";
  created_at: string;
  sequence: number;
  active_turn_id: string | null;
};
export type ChatStatus =
  | "accepted"
  | "running"
  | "cancel_requested"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";
export type ChatTurn = {
  schema_version: 1;
  id: string;
  request_id: string;
  session_id: string;
  sequence: number;
  revision: number;
  status: ChatStatus;
  user_text: string;
  assistant_text: string;
  error_code: ChatCode | null;
  transport: "not_started" | "open" | "closed" | "unknown";
  provider_stop: "not_dispatched" | "unknown";
  created_at: string;
  finished_at: string | null;
};
export type ChatHistory = {
  schema_version: 1;
  session: ChatSession;
  turns: ChatTurn[];
  next_before_sequence: number | null;
};
export type ChatCode = (typeof chatCodes)[number];
export type ChatProfile = {
  id: string;
  name: string;
  model: string;
  format: "openai";
  endpoint: string;
  streaming: boolean;
};
export type ChatRuntime = {
  schema_version: 1;
  mode: "chat_only";
  supported: boolean;
  reason: ChatCode | null;
  settings_revision: number;
  profile: ChatProfile | null;
  limits: {
    input_bytes: 8192;
    output_bytes: 65536;
    sessions: 32;
    session_turns: 64;
    history_bytes: 8388608;
    turn_seconds: 120;
  };
  history: "persistent";
  configuration_tools: false;
  live_execution: false;
  mcp_execution: false;
};
