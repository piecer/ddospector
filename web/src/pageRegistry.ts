import type { ComponentType } from "react";
import type { PageProps } from "./lib/contracts";
import type { RouteId } from "./lib/navigation";
import { OverviewPage } from "./pages/OverviewPage";
import {
  CampaignsPage,
  RunsPage,
  FindingsPage,
  EvidencePage,
  ApprovalsPage,
  AuditPage,
} from "./pages/operations";
import {
  TargetsPage,
  InstrumentsPage,
  McpServersPage,
  ProfilesPage,
  SettingsPage,
} from "./pages/lab";
import { AgentPage, SkillsPage } from "./pages/ai";
export const pages: Record<RouteId, ComponentType<PageProps>> = {
  overview: OverviewPage,
  campaigns: CampaignsPage,
  runs: RunsPage,
  findings: FindingsPage,
  evidence: EvidencePage,
  targets: TargetsPage,
  instruments: InstrumentsPage,
  "mcp-servers": McpServersPage,
  profiles: ProfilesPage,
  agent: AgentPage,
  skills: SkillsPage,
  approvals: ApprovalsPage,
  audit: AuditPage,
  settings: SettingsPage,
};
