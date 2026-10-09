import type {
  WorkspaceSnapshot,
  Target,
  TargetInput,
  McpServer,
  McpServerInput,
  Skill,
  SkillInput,
  AgentProfile,
  AgentProfileInput,
  Campaign,
  CampaignInput,
  ContextPreview,
  Locale,
} from "./contracts";
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    signal,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The API returned an unreadable response.");
  }
  if (!response.ok) {
    const message =
      typeof payload === "object" &&
      payload !== null &&
      "message" in payload &&
      typeof payload.message === "string"
        ? payload.message.slice(0, 300)
        : "Request rejected (" + response.status + ").";
    throw new Error(message);
  }
  return payload as T;
}
async function getWorkspace(signal?: AbortSignal): Promise<WorkspaceSnapshot> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(
    () =>
      controller.abort(
        new DOMException("Workspace request timed out.", "TimeoutError"),
      ),
    10_000,
  );
  try {
    return await request<WorkspaceSnapshot>(
      "/workspace",
      "GET",
      undefined,
      controller.signal,
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
export const api = {
  getWorkspace,
  createTarget: (input: TargetInput) =>
    request<Target>("/targets", "POST", input),
  createMcpServer: (input: McpServerInput) =>
    request<McpServer>("/mcp-servers", "POST", input),
  createSkill: (input: SkillInput) => request<Skill>("/skills", "POST", input),
  saveAgentProfile: (input: AgentProfileInput) =>
    request<AgentProfile>("/agent-profile", "PUT", input),
  createCampaign: (input: CampaignInput) =>
    request<Campaign>("/campaigns", "POST", input),
  previewContext: (input: { goal: string; locale: Locale }) =>
    request<ContextPreview>("/agent/preview", "POST", input),
};
