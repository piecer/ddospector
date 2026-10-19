// Synthetic B witnesses ONLY: no current Python B producer exists in this seed.
import {
  call,
  decision,
  expiry,
  gid,
  cid,
  hash,
  now,
  transcript,
  toolRuntime,
} from "./chat-tool-test-fixtures";
export const target = {
  id: "target-legacy",
  name: " Literal 대상 🌍 ",
  address: "Example.COM.",
  kind: "DUT" as const,
  status: "draft" as const,
  created_at: now,
};
export const targetInput = {
  name: target.name,
  address: target.address,
  kind: target.kind,
};
export const targetArgs = { expected_draft_revision: 2, ...targetInput };
export const targetProposal = {
  operation: "target_create",
  digest: hash({
    call_id: cid,
    grant_id: gid,
    operation: "target_create",
    expected_draft_revision: 2,
    before: null,
    after: targetInput,
    expires_at: expiry,
  }),
  expected_draft_revision: 2,
  before: null,
  after: targetInput,
  expires_at: expiry,
};
export const targetResult = {
  kind: "target_created",
  before_revision: 2,
  after_revision: 3,
  target,
  audit: {
    id: "audit-1",
    action: "target.created",
    entity_id: target.id,
    origin: "local_operator",
    created_at: now,
  },
};
export const targetCall = {
  ...call,
  tool: "target_create",
  arguments: targetArgs,
  args_digest: hash(targetArgs),
  proposal: targetProposal,
};
export const targetSaved = {
  ...targetCall,
  status: "succeeded",
  decision: { ...decision, proposal_digest: targetProposal.digest },
  result: targetResult,
  finished_at: now,
};
export const targetTranscript = { ...transcript, calls: [targetSaved] };
export const targetRuntime = {
  ...toolRuntime,
  schema_version: 2,
  tools: [...toolRuntime.tools, "target_create"],
};
export const inspection = {
  schema_version: 1,
  draft_revision: 3,
  targets: [target],
};
