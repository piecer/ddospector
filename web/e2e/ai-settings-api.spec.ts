import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

const endpoint = "/api/v1/ai-settings";
const zeroRetry = () => ({ attempts: 0, interval_ms: 0 });

function profile() {
  const id = `llm-wire-${randomUUID()}`;
  return {
    id,
    name: `Wire model ${id}`,
    format: "openai",
    model: "operator/model-id:literal",
    base_url: "http://127.0.0.1:1234/v1",
    credential_env: "AIDDOS_LLM_TEST_KEY",
    rate_per_second: 0,
    rate_per_minute: 12,
    context_window_k: 200,
    streaming: true,
    max_tokens: 4096,
    max_tokens_field: "max_completion_tokens",
    thinking_type: "enabled",
    reasoning_effort: "high",
    retry: { connect: zeroRetry(), empty: zeroRetry(), stream: zeroRetry() },
  };
}

test("real AI configuration API persists profiles, bindings and CAS without execution", async ({
  request,
}) => {
  const initial = await request.get(endpoint);
  expect(initial.status()).toBe(200);
  const original = await initial.json();
  const created = profile();
  const input = {
    revision: original.revision,
    profiles: [...original.profiles, created],
    default_profile_id: original.default_profile_id,
    agent_profile_id: original.agent_profile_id,
  };
  const savedResponse = await request.put(endpoint, { data: input });
  expect(savedResponse.status()).toBe(200);
  const saved = await savedResponse.json();
  expect(saved.revision).toBe(original.revision + 1);
  expect(saved.profiles).toContainEqual(created);
  expect(saved.default_profile_id).toBe(original.default_profile_id);
  expect(saved.execution_enabled).toBe(false);
  expect(saved.connection_status).toBe("not_tested");
  expect(await (await request.get(endpoint)).json()).toEqual(saved);

  const boundResponse = await request.put(endpoint, {
    data: {
      ...input,
      revision: saved.revision,
      default_profile_id: created.id,
      agent_profile_id: created.id,
    },
  });
  expect(boundResponse.status()).toBe(200);
  const bound = await boundResponse.json();
  const stale = await request.put(endpoint, { data: input });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).code).toBe("AI_SETTINGS_CONFLICT");
  expect(await (await request.get(endpoint)).json()).toEqual(bound);

  const contradictory = await request.put(endpoint, {
    data: {
      revision: bound.revision,
      profiles: [
        ...original.profiles,
        { ...created, format: "openai-responses" },
      ],
      default_profile_id: created.id,
      agent_profile_id: created.id,
    },
  });
  expect(contradictory.status()).toBe(422);
  expect(await (await request.get(endpoint)).json()).toEqual(bound);

  const editedResponse = await request.put(endpoint, {
    data: {
      revision: bound.revision,
      profiles: [
        ...original.profiles,
        { ...created, format: "openai-responses", max_tokens_field: "" },
      ],
      default_profile_id: created.id,
      agent_profile_id: created.id,
    },
  });
  expect(editedResponse.status()).toBe(200);
  const edited = await editedResponse.json();
  const dangling = await request.put(endpoint, {
    data: {
      revision: edited.revision,
      profiles: original.profiles,
      default_profile_id: created.id,
      agent_profile_id: created.id,
    },
  });
  expect(dangling.status()).toBe(422);
  expect(await (await request.get(endpoint)).json()).toEqual(edited);

  const removedResponse = await request.put(endpoint, {
    data: { ...input, revision: edited.revision, profiles: original.profiles },
  });
  expect(removedResponse.status()).toBe(200);
  const removed = await removedResponse.json();
  expect(removed.profiles).toEqual(original.profiles);
  expect(removed.default_profile_id).toBe(original.default_profile_id);
  expect(removed.agent_profile_id).toBe(original.agent_profile_id);
  const workspace = await (await request.get("/api/v1/workspace")).json();
  expect(workspace.audit.at(-1).action).toBe("ai_settings.updated");
  expect(workspace.capabilities.llm_inference).toBe(false);
  expect(workspace.capabilities.mcp_connect).toBe(false);
  expect(workspace.capabilities.live_execution).toBe(false);
});

test("real AI configuration rejects raw-key fields and denies discovery and inference", async ({
  request,
}) => {
  const initial = await request.get(endpoint);
  expect(initial.status()).toBe(200);
  const original = await initial.json();
  const invalid = await request.put(endpoint, {
    data: {
      revision: original.revision,
      profiles: [{ ...profile(), api_key: "example-invalid-key" }],
      default_profile_id: null,
      agent_profile_id: null,
    },
  });
  expect(invalid.status()).toBe(422);
  expect(await invalid.text()).not.toContain("example-invalid-key");
  for (const action of ["test", "models"]) {
    const response = await request.post(`${endpoint}/${action}`, {
      data: { profile_id: "missing" },
    });
    expect(response.status()).toBe(409);
    expect((await response.json()).code).toBe("AI_CONNECTION_NOT_AVAILABLE");
  }
  expect(await (await request.get(endpoint)).json()).toEqual(original);
});
