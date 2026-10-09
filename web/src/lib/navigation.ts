export type RouteId =
  | "overview"
  | "campaigns"
  | "runs"
  | "findings"
  | "evidence"
  | "targets"
  | "instruments"
  | "mcp-servers"
  | "profiles"
  | "agent"
  | "skills"
  | "approvals"
  | "audit"
  | "settings";
export type NavItem = {
  id: RouteId;
  group: "workspace" | "lab" | "ai" | "system";
  label: { en: string; ko: string };
  icon: string;
};
export const navigation: NavItem[] = [
  {
    id: "overview",
    group: "workspace",
    label: { en: "Overview", ko: "워크스페이스" },
    icon: "LayoutDashboard",
  },
  {
    id: "campaigns",
    group: "workspace",
    label: { en: "Campaigns", ko: "시험 캠페인" },
    icon: "Layers3",
  },
  {
    id: "runs",
    group: "workspace",
    label: { en: "Runs", ko: "실행 이력" },
    icon: "Activity",
  },
  {
    id: "findings",
    group: "workspace",
    label: { en: "Findings", ko: "검증 결과" },
    icon: "ScanSearch",
  },
  {
    id: "evidence",
    group: "workspace",
    label: { en: "Evidence", ko: "증거 보관함" },
    icon: "FolderArchive",
  },
  {
    id: "targets",
    group: "lab",
    label: { en: "Targets", ko: "시험 대상" },
    icon: "Crosshair",
  },
  {
    id: "instruments",
    group: "lab",
    label: { en: "Instruments", ko: "계측기" },
    icon: "RadioTower",
  },
  {
    id: "mcp-servers",
    group: "lab",
    label: { en: "MCP servers", ko: "MCP 서버" },
    icon: "Network",
  },
  {
    id: "profiles",
    group: "lab",
    label: { en: "Traffic profiles", ko: "트래픽 프로파일" },
    icon: "SlidersHorizontal",
  },
  {
    id: "agent",
    group: "ai",
    label: { en: "Agent workspace", ko: "AI 에이전트" },
    icon: "Bot",
  },
  {
    id: "skills",
    group: "ai",
    label: { en: "Skill library", ko: "Skill 라이브러리" },
    icon: "BookOpen",
  },
  {
    id: "approvals",
    group: "ai",
    label: { en: "Approvals", ko: "실행 승인" },
    icon: "ShieldCheck",
  },
  {
    id: "audit",
    group: "system",
    label: { en: "Audit log", ko: "감사 로그" },
    icon: "History",
  },
  {
    id: "settings",
    group: "system",
    label: { en: "Settings", ko: "설정" },
    icon: "Settings2",
  },
];
export function routeFromPath(path: string): RouteId | null {
  if (path === "/") return "overview";
  return navigation.find((item) => path === "/" + item.id)?.id ?? null;
}
