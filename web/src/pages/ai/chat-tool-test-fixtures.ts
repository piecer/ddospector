// Synthetic closed-protocol witnesses, NOT backend integration evidence.
import { createHash } from "node:crypto";
import { canonical } from "../scenarios/json";
import { sid, tid, rid, session } from "./chat-test-fixtures";
export const hash = (v: unknown) =>
  createHash("sha256").update(canonical(v)).digest("hex");
export const textHash = (v: string) => hash(v);
export const cid = "44444444-4444-4444-8444-444444444444";
export const gid = "55555555-5555-4555-8555-555555555555";
export const drid = "66666666-6666-4666-8666-666666666666";
export const now = "2026-10-18T01:00:00Z";
export const expiry = "2099-10-18T01:02:00Z";
export const agent = {
  resource_id: "agent-profile",
  name: "Before",
  skill_ids: ["skill-one"],
};
export const after = { ...agent, name: " After 한글 😀 ", skill_ids: [] };
export const args = {
  expected_draft_revision: 2,
  name: after.name,
  skill_ids: after.skill_ids,
};
const proposalBody = {
  call_id: cid,
  grant_id: gid,
  expected_draft_revision: 2,
  before: agent,
  after,
  expires_at: expiry,
};
export const proposal = {
  digest: hash(proposalBody),
  expected_draft_revision: 2,
  before: agent,
  after,
  expires_at: expiry,
};
export const decision = {
  schema_version: 1,
  request_id: drid,
  call_id: cid,
  proposal_digest: proposal.digest,
  decision: "approve",
  accepted_at: now,
};
export const call = {
  id: cid,
  index: 0,
  provider_call_id: "native-1",
  tool: "agent_profile_update",
  arguments: args,
  args_digest: hash(args),
  grant_id: gid,
  actor: "operator_authorized_model",
  status: "awaiting_approval",
  error_code: null,
  proposal,
  decision: null,
  result: null,
  started_at: now,
  finished_at: null,
};
export const transcript = {
  schema_version: 1,
  turn_id: tid,
  revision: 1,
  calls: [call],
};
export const grant = {
  schema_version: 1,
  id: gid,
  request_id: drid,
  session_id: sid,
  turn_request_id: rid,
  expected_sequence: 0,
  text_sha256: textHash("hello"),
  settings_revision: session.settings_revision,
  profile_id: session.profile_id,
  created_at: now,
  expires_at: "2026-10-18T01:05:00Z",
  status: "pending",
  read_scope: ["agent_profile", "skills", "skill"],
  proposal_fields: ["name", "skill_ids"],
};
export const result = {
  kind: "agent_profile_updated",
  before_revision: 2,
  after_revision: 3,
  agent_profile: after,
  audit: {
    id: "audit-1",
    action: "agent_profile.updated",
    entity_id: "agent-profile",
    created_at: now,
    origin: "local_operator",
  },
};
export const savedCall = {
  ...call,
  status: "succeeded",
  decision,
  result,
  finished_at: now,
};
export const fence = {
  schema_version: 1,
  generation: 0,
  fenced: false,
  call_ids: [],
  current_draft_revision: 2,
};
export const toolRuntime = {
  schema_version: 1,
  mode: "operator_approved_settings",
  supported: true,
  reason: null,
  tools: ["configuration_read", "agent_profile_update"],
  max_calls: 3,
  max_writes: 1,
  requires_write_approval: true,
};
