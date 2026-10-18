// Synthetic unit-test data only; never imported by product code.
export const sid = "11111111-1111-4111-8111-111111111111";
export const tid = "22222222-2222-4222-8222-222222222222";
export const rid = "33333333-3333-4333-8333-333333333333";
export const session = {
  schema_version: 1,
  id: sid,
  request_id: rid,
  settings_revision: 0,
  profile_id: "local-model_1",
  model: "test:model",
  endpoint: "http://localhost:11434/v1/chat/completions",
  streaming: true,
  locale: "en",
  created_at: "2026-10-18T01:00:00Z",
  sequence: 1,
  active_turn_id: tid,
};
export const turn = {
  schema_version: 1,
  id: tid,
  request_id: rid,
  session_id: sid,
  sequence: 1,
  revision: 1,
  status: "accepted",
  user_text: "hello",
  assistant_text: "",
  error_code: null,
  transport: "not_started",
  provider_stop: "not_dispatched",
  created_at: "2026-10-18T01:00:00Z",
  finished_at: null,
};
export const runtimeFixture = {
  schema_version: 1,
  mode: "chat_only",
  supported: true,
  reason: null,
  settings_revision: 0,
  profile: {
    id: "local-model_1",
    name: "Local",
    model: "test:model",
    format: "openai",
    endpoint: session.endpoint,
    streaming: true,
  },
  limits: {
    input_bytes: 8192,
    output_bytes: 65536,
    sessions: 32,
    session_turns: 64,
    history_bytes: 8388608,
    turn_seconds: 120,
  },
  history: "persistent",
  configuration_tools: false,
  live_execution: false,
  mcp_execution: false,
};
export const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
