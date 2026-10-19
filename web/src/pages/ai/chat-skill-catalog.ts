// Exact catalog.py v1 bytes; pure source DTO, not a producer capture.
// chat-skill-domain-oracle.test.ts binds these literals to the actual catalog.
export const skillSafety = [
  {
    en: "Guidance is not authority. LIVE, MCP connections and inference are disabled in UI-01.",
    ko: "지침은 실행 권한이 아닙니다. UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
  },
  {
    en: "Require operator scope approval and a future Safety Gate before any device operation; never place secrets in drafts or instructions.",
    ko: "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. 초안이나 지침에 비밀 정보를 넣지 마세요.",
  },
] as const;
export const skillTemplates = [
  {
    id: "policy-validation",
    name: {
      en: "Policy validation planning",
      ko: "정책 검증 계획",
    },
    description: {
      en: "Prepare a bounded, reviewable validation plan without generating traffic.",
      ko: "트래픽을 생성하지 않고 범위가 제한된 검토용 검증 계획을 준비합니다.",
    },
    instructions: {
      en: "Prerequisites: identify the authorized DUT and SINK, owner, isolated network, maintenance window, intended policy and rollback owner. Review the selected traffic template as a draft, not an executable asset. Record expected allow/deny behavior, rate/duration ceilings, stop conditions and evidence to collect. List missing approvals and capabilities explicitly. Produce a proposed plan for human review; do not start traffic, call tools or claim that a policy passed.",
      ko: "선행 조건: 승인된 DUT와 SINK, 소유자, 격리 네트워크, 작업 시간, 검증할 정책과 복구 담당자를 확인합니다. 선택한 트래픽 템플릿은 실행 자산이 아닌 초안으로 검토합니다. 예상 허용·차단 동작, 속도·시간 상한, 중지 조건과 수집할 증거를 기록합니다. 누락된 승인과 기능을 명시합니다. 사람이 검토할 계획만 제안하고 트래픽 생성, 도구 호출 또는 정책 통과 주장을 하지 않습니다.",
    },
    version: "1.0.0",
    category: "planning",
    status: "template",
    allowed_operations: ["draft_plan", "review_prerequisites"],
    required_capabilities: ["approved_scope", "safety_gate"],
    safety_rules: [
      {
        en: "Guidance is not authority. LIVE, MCP connections and inference are disabled in UI-01.",
        ko: "지침은 실행 권한이 아닙니다. UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
      },
      {
        en: "Require operator scope approval and a future Safety Gate before any device operation; never place secrets in drafts or instructions.",
        ko: "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. 초안이나 지침에 비밀 정보를 넣지 마세요.",
      },
    ],
  },
  {
    id: "mcp-measurement",
    name: {
      en: "MCP measurement procedure",
      ko: "MCP 측정 절차",
    },
    description: {
      en: "Describe evidence collection through explicitly assigned MCP servers.",
      ko: "명시적으로 할당된 MCP 서버를 통한 증거 수집 절차를 설명합니다.",
    },
    instructions: {
      en: "Prerequisites: review the assigned MCP server's transport and usage instructions. Registration is draft metadata, not a handshake, discovered tool list or permission. Before future measurement, require verified tool schemas, capability bindings, operator authorization and Safety Gate approval. Plan bounded observation windows and label units, timestamps, source and capture limitations. Never guess available tools, invoke endpoints or execute a stdio identifier as a command. In this stage return only a collection checklist; mark all uncollected measurements as unavailable.",
      ko: "선행 조건: 할당된 MCP 서버의 전송 방식과 사용 지침을 검토합니다. 등록은 초안 메타데이터이며 연결 확인, 발견된 도구 목록 또는 권한이 아닙니다. 향후 측정 전에 검증된 도구 스키마, 기능 바인딩, 운영자 승인과 Safety Gate 승인이 필요합니다. 관찰 시간의 상한, 단위, 타임스탬프, 출처와 캡처 한계를 명시합니다. 도구를 추측하거나 엔드포인트를 호출하거나 stdio 식별자를 명령으로 실행하지 않습니다. 이 단계에서는 수집 체크리스트만 작성하고 미수집 측정치는 사용할 수 없다고 표시합니다.",
    },
    version: "1.0.0",
    category: "measurement",
    status: "template",
    allowed_operations: ["draft_measurement_checklist"],
    required_capabilities: ["verified_mcp_binding", "safety_gate"],
    safety_rules: [
      {
        en: "Guidance is not authority. LIVE, MCP connections and inference are disabled in UI-01.",
        ko: "지침은 실행 권한이 아닙니다. UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
      },
      {
        en: "Require operator scope approval and a future Safety Gate before any device operation; never place secrets in drafts or instructions.",
        ko: "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. 초안이나 지침에 비밀 정보를 넣지 마세요.",
      },
    ],
  },
  {
    id: "evidence-analysis",
    name: {
      en: "Evidence review",
      ko: "증거 검토",
    },
    description: {
      en: "Define a reproducible analysis checklist without inventing findings.",
      ko: "발견 사항을 만들어내지 않고 재현 가능한 분석 체크리스트를 정의합니다.",
    },
    instructions: {
      en: "Prerequisites: obtain genuine retained evidence with source identity, collection time, integrity digest and scope approval. Separate measured facts, hypotheses and unknowns. Compare observations with the explicitly stated policy and baseline, preserving units and missing-data limitations. Cite each proposed finding to its evidence and record reproducibility steps. No evidence means no finding, not a successful test. This workspace has no execution evidence; prepare a review checklist only and never fabricate packet counts, detections or approval.",
      ko: "선행 조건: 출처 식별자, 수집 시각, 무결성 해시와 범위 승인이 있는 실제 보관 증거를 확보합니다. 측정 사실, 가설과 미확인 사항을 분리합니다. 단위와 누락된 데이터의 한계를 보존하면서 명시된 정책 및 기준과 관찰 결과를 비교합니다. 발견 사항마다 근거와 재현 절차를 기록합니다. 증거가 없다는 것은 발견 사항이 없다는 뜻이지 테스트 성공이 아닙니다. 이 작업 공간에는 실행 증거가 없으므로 검토 체크리스트만 준비하고 패킷 수, 탐지 결과 또는 승인을 만들어내지 않습니다.",
    },
    version: "1.0.0",
    category: "analysis",
    status: "template",
    allowed_operations: ["draft_evidence_checklist"],
    required_capabilities: ["retained_evidence", "verified_provenance"],
    safety_rules: [
      {
        en: "Guidance is not authority. LIVE, MCP connections and inference are disabled in UI-01.",
        ko: "지침은 실행 권한이 아닙니다. UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
      },
      {
        en: "Require operator scope approval and a future Safety Gate before any device operation; never place secrets in drafts or instructions.",
        ko: "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. 초안이나 지침에 비밀 정보를 넣지 마세요.",
      },
    ],
  },
] as const;
