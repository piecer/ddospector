import {
  parseSkillInventory,
  parseSkillInspection,
  SkillReadbackMismatch,
} from "./chat-skill-wire";
import {
  bindSubmission,
  chatClient,
  chatJSON,
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
  parseToolRuntime,
  parseTranscript,
  parseFence,
  parseReconcile,
  parseAgent,
  parseTargetInspection,
  reconcileFence,
} from "./chat-tool-wire";
import type { ChatSession } from "./chat-types";
import type {
  RequestedAuthority,
  ToolDecision,
  ToolGrant,
  ToolFence,
} from "./chat-tool-types";
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
  requestedAuthority: RequestedAuthority,
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
  async reconcile(request: string, fence: ToolFence) {
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
    return parseFence(await chatJSON("/tools/fence", "GET", undefined, signal));
  },
  async runtime(signal?: AbortSignal) {
    return parseToolRuntime(
      await chatJSON("/tools/runtime", "GET", undefined, signal),
    );
  },
  async grant(
    session: ChatSession,
    request: string,
    turnRequest: string,
    text: string,
    requestedAuthority: RequestedAuthority = "agent_v1",
  ) {
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
    requestedAuthority: RequestedAuthority = "agent_v1",
  ) {
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
    requestedAuthority: RequestedAuthority = "agent_v1",
  ) {
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
  async tools(id: string, signal?: AbortSignal) {
    uuid(id);
    const result = await parseTranscript(
      await chatJSON(`/turns/${id}/tools`, "GET", undefined, signal),
    );
    check(result.turn_id === id);
    return result;
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
    try {
      return bindDecision(
        await chatJSON(
          `/tool-calls/${call}/decision`,
          "POST",
          input,
          undefined,
          [200, 201],
        ),
        call,
        input,
      );
    } catch {
      if (!recover) throw new Error("Decision acknowledgement unknown.");
      // Even a conflict may reflect another decision; recover only OUR exact receipt.
      const transcript = await toolClient.tools(turn);
      return bindDecision(
        transcript.calls.find((c) => c.id === call)?.decision,
        call,
        input,
      );
    }
  },
};
