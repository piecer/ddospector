// Synthetic test witnesses ONLY; not native publication or producer capture.
import {
  call,
  decision,
  expiry,
  cid,
  gid,
  hash,
  now,
  transcript,
  grant,
  toolRuntime,
} from "./chat-tool-test-fixtures";
import type { SkillInput, CompleteDraftSkill } from "../../lib/contracts";
import { skillSafety } from "./chat-skill-catalog";
export const skillInput: SkillInput = {
  name: " Literal 🌍 ",
  description: "description\n\t",
  instructions: "<script>not authority</script>\r\nEND",
  category: "planning",
};
export const skillArgs = { expected_draft_revision: 2, ...skillInput };
export const skillProposal = {
  operation: "skill_create",
  expected_draft_revision: 2,
  before: null,
  after: skillInput,
  expires_at: expiry,
};
// Synthetic component witness, not a claim of publication.
export const draft: CompleteDraftSkill = {
  id: "skill-test",
  name: { en: skillInput.name, ko: skillInput.name },
  description: { en: skillInput.description, ko: skillInput.description },
  instructions: { en: skillInput.instructions, ko: skillInput.instructions },
  category: skillInput.category,
  version: "1.0.0",
  status: "draft",
  allowed_operations: [],
  required_capabilities: [],
  safety_rules: skillSafety.map((r) => ({ ...r })),
};
export const saved = {
  ...call,
  tool: "skill_create",
  arguments: skillArgs,
  args_digest: hash(skillArgs),
  proposal: {
    ...skillProposal,
    digest: hash({ call_id: cid, grant_id: gid, ...skillProposal }),
  },
  status: "succeeded",
  finished_at: now,
  result: {
    kind: "skill_created",
    before_revision: 2,
    after_revision: 3,
    skill: draft,
    audit: {
      id: "audit-skill",
      action: "skill.created",
      entity_id: draft.id,
      origin: "local_operator",
      created_at: now,
    },
  },
};
export const skillSaved = {
  ...saved,
  decision: { ...decision, proposal_digest: saved.proposal.digest },
};

export const skillTranscript = { ...transcript, calls: [skillSaved] };
export const skillCall = {
  ...saved,
  status: "awaiting_approval",
  result: null,
  finished_at: null,
};
export const skillRuntime = {
  ...toolRuntime,
  schema_version: 3,
  tools: [...toolRuntime.tools, "target_create", "skill_create"],
};
export const skillGrant = (() => {
  const { proposal_fields, ...common } = grant;
  void proposal_fields;
  return {
    ...common,
    schema_version: 3,
    scope: "skill_create",
    read_scope: ["skills", "skill"],
    proposal_tools: ["skill_create"],
  };
})();
export const skillInspection = {
  schema_version: 1,
  draft_revision: 3,
  skill: draft,
};
