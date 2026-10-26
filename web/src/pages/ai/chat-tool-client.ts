import { readChatMetadata } from "./chat-metadata";
import { chatScenarioClient } from "./chat-scenario-client";
import {
  boundCall,
  boundGrant as boundScenarioGrant,
  parseV4,
} from "./chat-scenario-wire";
import type { ScenarioGrantCommitment } from "./chat-scenario-wire";
import type { GrantV4, ScenarioStateInspection } from "./chat-scenario-types";
import {
  parseSkillInventory,
  parseSkillInspection,
  SkillReadbackMismatch,
} from "./chat-skill-wire";
import {
  bindSubmission,
  chatClient,
  chatJSON,
  chatToolJSON,
  ChatRequestError,
} from "./chat-client";
import { api } from "../../lib/api";
import { canonical, digest } from "../scenarios/json";
import { uuid, validText } from "./chat-wire";
import {
  check,
  integer,
  identifier,
  object,
  parseDecision,
  parseGrant,
  parseToolRuntimeResponse,
  parseTranscript,
  parseFence,
  parseReconcile,
  parseAgent,
  parseTargetInspection,
  reconcileFence,
} from "./chat-tool-wire";
import type { ChatSession } from "./chat-types";
import type {
  LegacyRequestedAuthority,
  ToolAuthority,
  ToolDecision,
  ToolGrant,
  ToolFence,
} from "./chat-tool-types";
export type ScenarioCallContext = { grant: GrantV4; deadlineAt: string };
export type DecisionInput = Pick<
  ToolDecision,
  "request_id" | "proposal_digest" | "decision"
>;
async function boundGrant(
  value: unknown,
  session: ChatSession,
  request: string,
  turnRequest: string,
  text: string,
  requestedAuthority: LegacyRequestedAuthority,
) {
  const g = parseGrant(value);
  check(
    requestedAuthority === "agent_v1"
      ? g.schema_version === 1
      : requestedAuthority === "target_create_v2"
        ? g.schema_version === 2
        : requestedAuthority === "skill_create_v3" && g.schema_version === 3,
  );
  check(
    g.request_id === request &&
      g.session_id === session.id &&
      g.turn_request_id === turnRequest &&
      g.expected_sequence === session.sequence &&
      g.profile_id === session.profile_id &&
      g.settings_revision === session.settings_revision &&
      g.text_sha256 === (await digest(text)),
  );
  return g;
}
export function bindDecision(
  value: unknown,
  call: string,
  input: DecisionInput,
) {
  const d = parseDecision(value);
  check(
    d.call_id === call &&
      d.request_id === input.request_id &&
      d.proposal_digest === input.proposal_digest &&
      d.decision === input.decision,
  );
  return d;
}
/** Capture each P0 value synchronously, before any codec/digest await. */
async function captureCommitment(
  commitment: ScenarioGrantCommitment,
  session: ChatSession,
  request: string,
  turnRequest: string,
  text: string,
): Promise<ScenarioGrantCommitment> {
  object(
    commitment,
    "requestedAuthority request settings_revision profile_id resolved_inputs",
  );
  check(commitment.requestedAuthority === "scenario_write_v4");
  const { settings_revision, profile_id } = commitment;
  integer(settings_revision);
  check(
    typeof profile_id === "string" &&
      profile_id === session.profile_id &&
      settings_revision === session.settings_revision,
  );
  const { id, sequence } = session;
  const [capturedRequest, resolved_inputs] = await Promise.all([
    parseV4("GrantInputV4", commitment.request),
    parseV4("ProtectedInputs", commitment.resolved_inputs),
  ]);
  check(
    capturedRequest.session_id === id &&
      capturedRequest.expected_sequence === sequence &&
      capturedRequest.request_id === request &&
      capturedRequest.turn_request_id === turnRequest &&
      capturedRequest.text === text,
  );
  if (capturedRequest.intent.input_source.source === "operator")
    check(
      canonical(capturedRequest.intent.input_source.inputs) ===
        canonical(resolved_inputs),
    );
  return {
    requestedAuthority: "scenario_write_v4",
    request: capturedRequest,
    settings_revision,
    profile_id,
    resolved_inputs,
  };
}
async function recoverScenarioGrant(
  captured: ScenarioGrantCommitment,
): Promise<GrantV4> {
  return chatToolJSON(
    `/tool-grants/by-request/${captured.request.request_id}`,
    (value) => boundScenarioGrant(value, captured),
  );
}
async function createScenarioGrant(
  captured: ScenarioGrantCommitment,
): Promise<GrantV4> {
  let acknowledged = false;
  try {
    return await chatToolJSON(
      "/tool-grants",
      (value) => {
        acknowledged = true;
        return boundScenarioGrant(value, captured);
      },
      "POST",
      captured.request,
      undefined,
      [200, 201],
    );
  } catch (error) {
    if (error instanceof ChatRequestError && error.definite) throw error;
    const readback = await recoverScenarioGrant(captured);
    // A decoded contradictory ACK never becomes permission to send automatically.
    if (acknowledged) throw error;
    return readback;
  }
}
async function submitScenario(
  captured: ScenarioGrantCommitment,
  grant: GrantV4,
  admit: () => boolean,
) {
  const g = await boundScenarioGrant(grant, captured);
  check(g.status === "pending" && admit());
  const r = captured.request;
  try {
    return await chatToolJSON(
      `/sessions/${r.session_id}/tool-turns`,
      async (value) =>
        bindSubmission(
          value,
          r.session_id,
          r.turn_request_id,
          r.expected_sequence,
          r.text,
        ),
      "POST",
      {
        request_id: r.turn_request_id,
        expected_sequence: r.expected_sequence,
        text: r.text,
        grant_id: g.id,
      },
      undefined,
      [200, 202],
    );
  } catch (error) {
    if (error instanceof ChatRequestError && error.definite) throw error;
    return chatToolJSON(
      `/turns/by-request/${r.turn_request_id}`,
      async (value) =>
        bindSubmission(
          value,
          r.session_id,
          r.turn_request_id,
          r.expected_sequence,
          r.text,
        ),
    );
  }
}

async function inspectScenarioWith<T extends { revision: number }>(
  read: () => Promise<T>,
  signal?: AbortSignal,
) {
  const activeSignal = signal ?? new AbortController().signal;
  const before = await readChatMetadata(toolClient.fence, activeSignal);
  check(before.fenced && before.current_draft_revision !== null);
  const first = await readChatMetadata(toolClient.scenarioState, activeSignal);
  const snapshot = await read();
  const last = await readChatMetadata(toolClient.scenarioState, activeSignal);
  const after = await readChatMetadata(toolClient.fence, activeSignal);
  reconcileFence(before, after);
  check(
    canonical(first) === canonical(last) &&
      canonical(before) === canonical(after) &&
      snapshot.revision === first.scenario_revision,
  );
  return { fence: after, state: last, snapshot };
}

export const toolClient = {
  async skills(signal?: AbortSignal) {
    return parseSkillInventory(
      await chatJSON("/tools/skills", "GET", undefined, signal),
    );
  },
  async inspectSkills(signal?: AbortSignal) {
    const before = await toolClient.fence(signal);
    check(before.current_draft_revision !== null);
    const snapshot = await toolClient.skills(signal);
    const after = await toolClient.fence(signal);
    reconcileFence(before, after);
    check(
      before.generation === after.generation &&
        before.current_draft_revision === snapshot.draft_revision &&
        after.current_draft_revision === snapshot.draft_revision,
    );
    return { fence: after, skills: snapshot.skills };
  },
  async inspectSkill(id: string, fence: ToolFence, signal?: AbortSignal) {
    const snapshot = await toolClient.skill(id, signal);
    const after = await toolClient.fence(signal);
    reconcileFence(fence, after);
    check(
      fence.fenced &&
        fence.generation === after.generation &&
        fence.current_draft_revision === snapshot.draft_revision &&
        after.current_draft_revision === snapshot.draft_revision,
    );
    return snapshot.skill;
  },
  async skill(id: string, signal?: AbortSignal) {
    identifier(id);
    const result = parseSkillInspection(
      await chatJSON(
        `/tools/skills/${encodeURIComponent(id)}`,
        "GET",
        undefined,
        signal,
      ),
    );
    if (result.skill.id !== id)
      throw new SkillReadbackMismatch(
        "Selected Skill differs from requested ID.",
      );
    return result;
  },
  async targets(signal?: AbortSignal) {
    return parseTargetInspection(
      await chatJSON("/tools/targets", "GET", undefined, signal),
    );
  },
  async inspectTargets(signal?: AbortSignal) {
    const before = await toolClient.fence(signal);
    check(before.current_draft_revision !== null);
    const snapshot = await toolClient.targets(signal);
    const after = await toolClient.fence(signal);
    reconcileFence(before, after);
    check(
      before.generation === after.generation &&
        before.current_draft_revision === snapshot.draft_revision &&
        after.current_draft_revision === snapshot.draft_revision,
    );
    return { fence: after, targets: snapshot.targets };
  },
  async inspectCurrent(signal?: AbortSignal) {
    // Workspace v1 has no CAS token. Sandwich it between equal revision observations;
    // never invent a field/route or use audit-list length as the draft revision.
    const before = await toolClient.fence(signal);
    check(before.current_draft_revision !== null);
    const snapshot = await api.getWorkspace(signal);
    const p = object(
      snapshot.agent_profile,
      "name skill_ids mcp_server_ids autonomy execution_enabled",
    );
    check(p.autonomy === "REVIEW_ONLY" && p.execution_enabled === false);
    const agent = parseAgent({
      resource_id: "agent-profile",
      name: p.name,
      skill_ids: p.skill_ids,
    });
    const after = await toolClient.fence(signal);
    reconcileFence(before, after);
    check(
      before.generation === after.generation &&
        before.current_draft_revision === after.current_draft_revision,
    );
    return { fence: after, agent };
  },
  async reconcile(
    request: string,
    fence: ToolFence,
    scenario?: ScenarioStateInspection,
  ) {
    if (scenario !== undefined) {
      const f = parseFence(fence);
      const capturedFence = { ...f, call_ids: [...f.call_ids] };
      const state = await parseV4("ScenarioStateInspection", scenario);
      check(
        capturedFence.fenced && capturedFence.current_draft_revision !== null,
      );
      const input = await parseV4("ReconcileInputV4", {
        schema_version: 4,
        request_id: request,
        expected_generation: capturedFence.generation,
        expected_draft_revision: capturedFence.current_draft_revision,
        expected_scenario_revision: state.scenario_revision,
        acknowledge_uncertain: true,
      });
      return chatToolJSON(
        "/tools/reconcile",
        async (value) => {
          const receipt = await parseV4("ReconcileReceiptV4", value);
          check(
            receipt.request_id === request &&
              receipt.generation === capturedFence.generation + 1 &&
              receipt.observed_scenario_revision === state.scenario_revision &&
              canonical(receipt.acknowledged_call_ids) ===
                canonical(capturedFence.call_ids),
          );
          return receipt;
        },
        "POST",
        input,
        undefined,
        [200, 201],
      );
    }
    uuid(request);
    check(fence.fenced && fence.current_draft_revision !== null);
    const receipt = parseReconcile(
      await chatJSON(
        "/tools/reconcile",
        "POST",
        {
          request_id: request,
          expected_generation: fence.generation,
          expected_draft_revision: fence.current_draft_revision,
          acknowledge_uncertain: true,
        },
        undefined,
        [200, 201],
      ),
    );
    check(
      receipt.request_id === request &&
        receipt.generation === fence.generation + 1 &&
        canonical(receipt.acknowledged_call_ids) === canonical(fence.call_ids),
    );
    return receipt;
  },
  async fence(signal?: AbortSignal) {
    return chatToolJSON(
      "/tools/fence",
      async (value) => parseFence(value),
      "GET",
      undefined,
      signal,
    );
  },
  async runtime(signal?: AbortSignal) {
    return chatToolJSON(
      "/tools/runtime",
      parseToolRuntimeResponse,
      "GET",
      undefined,
      signal,
    );
  },
  async scenarioState(signal?: AbortSignal) {
    return chatToolJSON(
      "/tools/scenarios/state",
      (value) => parseV4("ScenarioStateInspection", value),
      "GET",
      undefined,
      signal,
    );
  },
  async inspectScenario(id: string, signal?: AbortSignal) {
    identifier(id);
    const { fence, state, snapshot } = await inspectScenarioWith(
      () => chatScenarioClient.history(id, signal),
      signal,
    );
    return { fence, state, history: snapshot };
  },
  async inspectScenarioPage(offset = 0, limit = 50, signal?: AbortSignal) {
    integer(offset, 0, 100);
    integer(limit, 1, 100);
    const { fence, state, snapshot } = await inspectScenarioWith(
      () => chatScenarioClient.read(offset, limit, signal),
      signal,
    );
    return { fence, state, page: snapshot };
  },
  async grant(
    session: ChatSession,
    request: string,
    turnRequest: string,
    text: string,
    requestedAuthority: ToolAuthority = "agent_v1",
  ) {
    if (typeof requestedAuthority === "object") {
      const captured = await captureCommitment(
        requestedAuthority,
        session,
        request,
        turnRequest,
        text,
      );
      return createScenarioGrant(captured);
    }
    check(
      ["agent_v1", "target_create_v2", "skill_create_v3"].includes(
        requestedAuthority,
      ),
    );
    uuid(session.id);
    uuid(request);
    uuid(turnRequest);
    integer(session.sequence, 0, 63);
    check(validText(text, 8192, true));
    let acknowledged: unknown;
    try {
      acknowledged = await chatJSON(
        "/tool-grants",
        "POST",
        {
          ...(requestedAuthority === "target_create_v2"
            ? { schema_version: 2, scope: "target_create" }
            : requestedAuthority === "skill_create_v3"
              ? { schema_version: 3, scope: "skill_create" }
              : {}),
          request_id: request,
          session_id: session.id,
          turn_request_id: turnRequest,
          expected_sequence: session.sequence,
          text,
        },
        undefined,
        [200, 201],
      );
    } catch (error) {
      if (error instanceof ChatRequestError && error.definite) throw error;
      return toolClient.recoverGrant(
        session,
        request,
        turnRequest,
        text,
        requestedAuthority,
      );
    }
    try {
      return await boundGrant(
        acknowledged,
        session,
        request,
        turnRequest,
        text,
        requestedAuthority,
      );
    } catch (mismatch) {
      // Preserve B1's one GET-only observation after an invalid ACK, but a
      // decoded contradictory ACK must never become an automatic tool send.
      await toolClient.recoverGrant(
        session,
        request,
        turnRequest,
        text,
        requestedAuthority,
      );
      throw mismatch;
    }
  },
  async recoverGrant(
    session: ChatSession,
    request: string,
    turnRequest: string,
    text: string,
    requestedAuthority: ToolAuthority = "agent_v1",
  ) {
    if (typeof requestedAuthority === "object") {
      const captured = await captureCommitment(
        requestedAuthority,
        session,
        request,
        turnRequest,
        text,
      );
      return recoverScenarioGrant(captured);
    }
    uuid(request);
    return boundGrant(
      await chatJSON(`/tool-grants/by-request/${request}`),
      session,
      request,
      turnRequest,
      text,
      requestedAuthority,
    );
  },
  async revoke(grant: ToolGrant) {
    if (grant.schema_version === 4) {
      const captured = await parseV4("GrantV4", grant);
      return chatToolJSON(
        `/tool-grants/${captured.id}/revoke`,
        async (value) => {
          const result = await parseV4("GrantV4", value);
          check(
            canonical({ ...result, status: captured.status }) ===
              canonical(captured),
          );
          check(result.status === "revoked" || result.status === "expired");
          return result;
        },
        "POST",
        {},
      );
    }
    uuid(grant.id);
    const result = parseGrant(
      await chatJSON(`/tool-grants/${grant.id}/revoke`, "POST", {}),
    );
    for (const key of Object.keys(grant) as (keyof ToolGrant)[])
      if (key !== "status")
        check(JSON.stringify(result[key]) === JSON.stringify(grant[key]));
    check(result.status === "revoked" || result.status === "expired");
    return result;
  },
  async submit(
    session: ChatSession,
    grant: ToolGrant,
    text: string,
    admit: () => boolean = () => true,
    requestedAuthority: ToolAuthority = "agent_v1",
  ) {
    if (typeof requestedAuthority === "object") {
      const [captured, capturedGrant] = await Promise.all([
        captureCommitment(
          requestedAuthority,
          session,
          grant.request_id,
          grant.turn_request_id,
          text,
        ),
        parseV4("GrantV4", grant),
      ]);
      return submitScenario(captured, capturedGrant, admit);
    }
    await boundGrant(
      grant,
      session,
      grant.request_id,
      grant.turn_request_id,
      text,
      requestedAuthority,
    );
    check(grant.status === "pending" && admit());
    try {
      return bindSubmission(
        await chatJSON(
          `/sessions/${session.id}/tool-turns`,
          "POST",
          {
            request_id: grant.turn_request_id,
            expected_sequence: session.sequence,
            text,
            grant_id: grant.id,
          },
          undefined,
          [200, 202],
        ),
        session.id,
        grant.turn_request_id,
        session.sequence,
        text,
      );
    } catch (error) {
      if (error instanceof ChatRequestError && error.definite) throw error;
      return bindSubmission(
        await chatClient.byRequest(grant.turn_request_id),
        session.id,
        grant.turn_request_id,
        session.sequence,
        text,
      );
    }
  },
  async tools(
    id: string,
    signal?: AbortSignal,
    authority?: ScenarioCallContext,
  ) {
    uuid(id);
    // No historical grant lookup/cache. Optional live authority is a separate check.
    const deadlineAt = authority?.deadlineAt;
    const grant =
      authority === undefined
        ? undefined
        : await parseV4("GrantV4", authority.grant);
    return chatToolJSON(
      `/turns/${id}/tools`,
      async (value) => {
        const result = await parseTranscript(value);
        check(result.turn_id === id);
        if (grant !== undefined) {
          check(result.schema_version === 4 && deadlineAt !== undefined);
          for (const call of result.calls)
            await boundCall(call, grant, deadlineAt);
        }
        return result;
      },
      "GET",
      undefined,
      signal,
    );
  },
  async decide(
    call: string,
    turn: string,
    input: DecisionInput,
    recover = true,
  ) {
    uuid(call);
    uuid(turn);
    uuid(input.request_id);
    const i = object(input, "request_id proposal_digest decision");
    check(
      typeof i.proposal_digest === "string" &&
        /^[a-f0-9]{64}$/.test(i.proposal_digest) &&
        ["approve", "deny"].includes(i.decision as string),
    );
    const captured = { ...input };
    try {
      return await chatToolJSON(
        `/tool-calls/${call}/decision`,
        async (value) => bindDecision(value, call, captured),
        "POST",
        captured,
        undefined,
        [200, 201],
      );
    } catch {
      if (!recover) throw new Error("Decision acknowledgement unknown.");
      // Even a conflict may reflect another decision; recover only OUR exact receipt.
      const transcript = await toolClient.tools(turn);
      return bindDecision(
        transcript.calls.find((c) => c.id === call)?.decision,
        call,
        captured,
      );
    }
  },
};
