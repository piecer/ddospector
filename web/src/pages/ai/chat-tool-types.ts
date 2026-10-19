import type { AuditEvent, Target, TargetInput } from "../../lib/contracts";
import type { ChatCode } from "./chat-types";
export type AgentConfig = {
  resource_id: "agent-profile";
  name: string;
  skill_ids: string[];
};
export type SkillSummary = {
  id: string;
  name: string;
  category: "planning" | "measurement" | "analysis";
  status: "template" | "draft";
  version: "1.0.0";
};
export type ReadArguments =
  | { kind: "agent_profile" }
  | { kind: "skills"; offset: number; limit: number }
  | { kind: "skill"; id: string };
export type WriteArguments = {
  expected_draft_revision: number;
  name: string;
  skill_ids: string[];
};
export type TargetCreateArguments = TargetInput & {
  expected_draft_revision: number;
};
export type TargetInspection = {
  schema_version: 1;
  draft_revision: number;
  targets: Target[];
};
export type ToolResult =
  | {
      kind: "targets";
      draft_revision: number;
      items: Target[];
      next_offset: number | null;
    }
  | { kind: "target"; draft_revision: number; target: Target }
  | {
      kind: "target_created";
      before_revision: number;
      after_revision: number;
      target: Target;
      audit: AuditEvent;
    }
  | {
      kind: "agent_profile";
      draft_revision: number;
      agent_profile: AgentConfig;
    }
  | {
      kind: "skills";
      draft_revision: number;
      items: SkillSummary[];
      next_offset: number | null;
    }
  | {
      kind: "skill";
      draft_revision: number;
      skill: SkillSummary & { description: string; instructions: string };
    }
  | {
      kind: "agent_profile_updated";
      before_revision: number;
      after_revision: number;
      agent_profile: AgentConfig;
      audit: AuditEvent;
    };
export type RequestedAuthority = "agent_v1" | "target_create_v2";
export type ToolRuntime = {
  mode: "operator_approved_settings";
  supported: boolean;
  reason: ChatCode | null;
  max_calls: 3;
  max_writes: 1;
  requires_write_approval: true;
} & (
  | { schema_version: 1; tools: ["configuration_read", "agent_profile_update"] }
  | {
      schema_version: 2;
      tools: ["configuration_read", "agent_profile_update", "target_create"];
    }
);
export type ToolGrant = {
  id: string;
  request_id: string;
  session_id: string;
  turn_request_id: string;
  expected_sequence: number;
  text_sha256: string;
  settings_revision: number;
  profile_id: string;
  created_at: string;
  expires_at: string;
  status: "pending" | "consumed" | "revoked" | "expired";
} & (
  | {
      schema_version: 1;
      read_scope: ["agent_profile", "skills", "skill"];
      proposal_fields: ["name", "skill_ids"];
    }
  | {
      schema_version: 2;
      scope: "target_create";
      read_scope: ["targets", "target"];
      proposal_tools: ["target_create"];
    }
);
export type ToolDecision = {
  schema_version: 1;
  request_id: string;
  call_id: string;
  proposal_digest: string;
  decision: "approve" | "deny";
  accepted_at: string;
};
export type ToolProposal =
  | {
      operation: "target_create";
      digest: string;
      expected_draft_revision: number;
      before: null;
      after: TargetInput;
      expires_at: string;
    }
  | {
      digest: string;
      expected_draft_revision: number;
      before: AgentConfig;
      after: AgentConfig;
      expires_at: string;
    };
export type ToolStatus =
  | "requested"
  | "awaiting_approval"
  | "executing"
  | "succeeded"
  | "denied"
  | "conflict"
  | "failed"
  | "uncertain"
  | "cancelled";
export type ToolCall = {
  id: string;
  index: number;
  provider_call_id: string;
  tool: "configuration_read" | "agent_profile_update" | "target_create";
  arguments:
    | ReadArguments
    | WriteArguments
    | TargetCreateArguments
    | { kind: "targets"; offset: number; limit: number }
    | { kind: "target"; id: string };
  args_digest: string;
  grant_id: string;
  actor: "operator_authorized_model";
  status: ToolStatus;
  error_code: ChatCode | null;
  proposal: ToolProposal | null;
  decision: ToolDecision | null;
  result: ToolResult | null;
  started_at: string;
  finished_at: string | null;
};
export type ToolTranscript = {
  schema_version: 1;
  turn_id: string;
  revision: number;
  calls: ToolCall[];
};
export type ToolFence = {
  schema_version: 1;
  generation: number;
  fenced: boolean;
  call_ids: string[];
  current_draft_revision: number | null;
};
export type ReconcileReceipt = {
  schema_version: 1;
  request_id: string;
  acknowledged_call_ids: string[];
  generation: number;
  write_fenced: false;
  prior_outcomes: "remain_uncertain";
};
