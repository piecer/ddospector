import type { RouteId } from "./navigation";
export type Locale = "en" | "ko";
export type LocalizedText = { en: string; ko: string };
export type Target = {
  id: string;
  name: string;
  address: string;
  kind: "DUT" | "SINK";
  status: "draft";
  created_at: string;
};
export type Instrument = {
  id: string;
  name: string;
  role: string;
  status: string;
};
export type McpServer = {
  id: string;
  name: string;
  endpoint: string;
  transport: "streamable_http" | "stdio";
  usage_instructions: string;
  status: "draft";
  tools_count: 0;
  created_at: string;
};
export type TrafficProfile = {
  id: string;
  name: LocalizedText;
  description: LocalizedText;
  engine: "tcpreplay" | "tcpdump" | "k6";
  layer: string;
  status: "template";
};
export type Skill = {
  id: string;
  name: LocalizedText;
  description: LocalizedText;
  instructions: LocalizedText;
  version: string;
  category: "planning" | "measurement" | "analysis";
  status: "template" | "draft";
  allowed_operations: string[];
  required_capabilities: string[];
  safety_rules: LocalizedText[];
};
export type AgentProfile = {
  name: string;
  skill_ids: string[];
  mcp_server_ids: string[];
  autonomy: "REVIEW_ONLY";
  execution_enabled: false;
};
export type Campaign = {
  id: string;
  name: string;
  objective: string;
  target_id: string;
  profile_id: string;
  status: "draft";
  created_at: string;
};
export type AuditEvent = {
  id: string;
  action: string;
  entity_id: string;
  created_at: string;
  origin: "local_operator";
};
export type WorkspaceSnapshot = {
  meta: {
    version: string;
    mode: "OFFLINE";
    live_enabled: false;
    live_limit: 1;
    storage: "local_drafts";
    deployment: "loopback_development";
  };
  targets: Target[];
  instruments: Instrument[];
  mcp_servers: McpServer[];
  profiles: TrafficProfile[];
  skills: Skill[];
  agent_profile: AgentProfile;
  campaigns: Campaign[];
  runs: never[];
  findings: never[];
  evidence: never[];
  approvals: never[];
  audit: AuditEvent[];
  capabilities: {
    draft_editing: true;
    context_preview: true;
    live_execution: false;
    mcp_connect: false;
    llm_inference: false;
  };
};
export type CompleteDraftSkill = Skill & {
  version: "1.0.0";
  status: "draft";
  allowed_operations: [];
  required_capabilities: [];
};
export type SkillExpectation = {
  skill: CompleteDraftSkill;
  after_revision: number;
};
export type SkillSelection = { id: string; expectation?: SkillExpectation };
export type TargetExpectation = { target: Target; after_revision: number };
export type TargetSelection = { id: string; expectation?: TargetExpectation };
export type NavigationArgs =
  | [route: RouteId]
  | [route: "targets", selection: TargetSelection]
  | [route: "skills", selection: SkillSelection];
export type PageProps = {
  data: WorkspaceSnapshot;
  locale: Locale;
  navigate: (...args: NavigationArgs) => void;
  targetSelection?: TargetSelection;
  skillSelection?: SkillSelection;
  refresh: () => Promise<void>;
};
export type TargetInput = Pick<Target, "name" | "address" | "kind">;
export type McpServerInput = Pick<
  McpServer,
  "name" | "endpoint" | "transport" | "usage_instructions"
>;
export type SkillInput = {
  name: string;
  description: string;
  instructions: string;
  category: Skill["category"];
};
export type AgentProfileInput = Pick<
  AgentProfile,
  "name" | "skill_ids" | "mcp_server_ids"
>;
export type CampaignInput = Pick<
  Campaign,
  "name" | "objective" | "target_id" | "profile_id"
>;
export type ContextPreview = {
  origin: "deterministic_context_preview";
  execution_enabled: false;
  prompt: string;
  skill_ids: string[];
  mcp_server_ids: string[];
};
