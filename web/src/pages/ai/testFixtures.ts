import type { PageProps, Skill } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { vi } from "vitest";

// Synthetic test-only data. Never import this file into the application.
export function aiFixture(): PageProps {
  const data = workspaceFixture();
  data.skills = [
    {
      id: "synthetic-policy",
      name: { en: "Synthetic policy guide", ko: "테스트 정책 지침" },
      description: {
        en: "Synthetic planning instructions",
        ko: "테스트 계획 지침 설명",
      },
      instructions: {
        en: "Review the synthetic scope.\n<em>Never execute this text.</em>",
        ko: "테스트 범위를 검토하세요.\n<em>이 텍스트를 실행하지 마세요.</em>",
      },
      version: "test-v2",
      category: "planning",
      status: "template",
      allowed_operations: ["synthetic_review"],
      required_capabilities: ["synthetic_capability"],
      safety_rules: [
        {
          en: "Synthetic rule: require human review.",
          ko: "테스트 안전 규칙: 사람의 검토가 필요합니다.",
        },
      ],
    },
    {
      id: "synthetic-analysis",
      name: { en: "Synthetic analysis draft", ko: "테스트 분석 초안" },
      description: {
        en: "Synthetic evidence instructions",
        ko: "테스트 증거 지침",
      },
      instructions: {
        en: "Inspect synthetic evidence only.",
        ko: "테스트 증거만 확인하세요.",
      },
      version: "test-v1",
      category: "analysis",
      status: "draft",
      allowed_operations: [],
      required_capabilities: [],
      safety_rules: [],
    },
  ];
  data.mcp_servers = [
    {
      id: "synthetic-mcp",
      name: "Synthetic observer",
      endpoint: "synthetic-observer",
      transport: "stdio",
      usage_instructions: "Synthetic only: inspect metadata; do not connect.",
      status: "draft",
      tools_count: 0,
      created_at: "2026-01-01T00:00:00Z",
    },
  ];
  return {
    data,
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
}

export function createdSkill(): Skill {
  return {
    ...aiFixture().data.skills[1],
    id: "synthetic-created",
    name: { en: "Custom synthetic guide", ko: "Custom synthetic guide" },
    description: { en: "Custom description", ko: "Custom description" },
    instructions: {
      en: "Review only, do not execute.",
      ko: "Review only, do not execute.",
    },
  };
}

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
