import type { WorkspaceSnapshot } from "../lib/contracts";
export function workspaceFixture(): WorkspaceSnapshot {
  return {
    meta: {
      version: "0.1.0-ui",
      mode: "OFFLINE",
      live_enabled: false,
      live_limit: 1,
      storage: "local_drafts",
      deployment: "loopback_development",
    },
    targets: [],
    instruments: [],
    mcp_servers: [],
    profiles: [],
    skills: [],
    campaigns: [],
    runs: [],
    findings: [],
    evidence: [],
    approvals: [],
    audit: [],
    agent_profile: {
      name: "Validation agent",
      skill_ids: [],
      mcp_server_ids: [],
      autonomy: "REVIEW_ONLY",
      execution_enabled: false,
    },
    capabilities: {
      draft_editing: true,
      context_preview: true,
      live_execution: false,
      mcp_connect: false,
      llm_inference: false,
    },
  };
}
