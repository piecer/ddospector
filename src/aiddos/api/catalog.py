"""Versioned, review-only guidance; these templates confer no execution authority.

TrafficProfile's frozen wire contract has no version field. Its catalog is versioned
here alongside the instruction catalog; changes require a catalog version bump.
"""

from copy import deepcopy

CATALOG_VERSION = "1.0.0"


def localized(en: str, ko: str) -> dict[str, str]:
    return {"en": en, "ko": ko}


SAFETY_RULES = [
    localized(
        "Guidance is not authority. LIVE, MCP connections and inference are disabled in UI-01.",
        "지침은 실행 권한이 아닙니다. UI-01에서는 LIVE, MCP 연결, 추론이 비활성화됩니다.",
    ),
    localized(
        "Require operator scope approval and a future Safety Gate before any device operation; "
        "never place secrets in drafts or instructions.",
        "장비 작업 전 운영자의 범위 승인과 향후 Safety Gate 검증이 필요합니다. "
        "초안이나 지침에 비밀 정보를 넣지 마세요.",
    ),
]

SKILLS_V1 = [
    {
        "id": "policy-validation",
        "name": localized("Policy validation planning", "정책 검증 계획"),
        "description": localized(
            "Prepare a bounded, reviewable validation plan without generating traffic.",
            "트래픽을 생성하지 않고 범위가 제한된 검토용 검증 계획을 준비합니다.",
        ),
        "instructions": localized(
            "Prerequisites: identify the authorized DUT and SINK, owner, isolated network, "
            "maintenance window, intended policy and rollback owner. Review the selected traffic "
            "template as a draft, not an executable asset. Record expected allow/deny behavior, "
            "rate/duration ceilings, stop conditions and evidence to collect. List missing "
            "approvals and capabilities explicitly. Produce a proposed plan for human review; "
            "do not start traffic, call tools or claim that a policy passed.",
            "선행 조건: 승인된 DUT와 SINK, 소유자, 격리 네트워크, 작업 시간, 검증할 정책과 "
            "복구 담당자를 확인합니다. 선택한 트래픽 템플릿은 실행 자산이 아닌 초안으로 "
            "검토합니다. 예상 허용·차단 동작, 속도·시간 상한, 중지 조건과 수집할 증거를 "
            "기록합니다. 누락된 승인과 기능을 명시합니다. 사람이 검토할 계획만 제안하고 "
            "트래픽 생성, 도구 호출 또는 정책 통과 주장을 하지 않습니다.",
        ),
        "version": CATALOG_VERSION,
        "category": "planning",
        "status": "template",
        "allowed_operations": ["draft_plan", "review_prerequisites"],
        "required_capabilities": ["approved_scope", "safety_gate"],
        "safety_rules": SAFETY_RULES,
    },
    {
        "id": "mcp-measurement",
        "name": localized("MCP measurement procedure", "MCP 측정 절차"),
        "description": localized(
            "Describe evidence collection through explicitly assigned MCP servers.",
            "명시적으로 할당된 MCP 서버를 통한 증거 수집 절차를 설명합니다.",
        ),
        "instructions": localized(
            "Prerequisites: review the assigned MCP server's transport and usage instructions. "
            "Registration is draft metadata, not a handshake, discovered tool list or permission. "
            "Before future measurement, require verified tool schemas, capability bindings, "
            "operator authorization and Safety Gate approval. Plan bounded observation windows "
            "and label units, timestamps, source and capture limitations. Never guess available "
            "tools, invoke endpoints or execute a stdio identifier as a command. In this stage "
            "return only a collection checklist; mark all uncollected measurements as unavailable.",
            "선행 조건: 할당된 MCP 서버의 전송 방식과 사용 지침을 검토합니다. 등록은 초안 "
            "메타데이터이며 연결 확인, 발견된 도구 목록 또는 권한이 아닙니다. 향후 측정 전에 "
            "검증된 도구 스키마, 기능 바인딩, 운영자 승인과 Safety Gate 승인이 필요합니다. "
            "관찰 시간의 상한, 단위, 타임스탬프, 출처와 캡처 한계를 명시합니다. 도구를 "
            "추측하거나 엔드포인트를 호출하거나 stdio 식별자를 명령으로 실행하지 않습니다. "
            "이 단계에서는 수집 체크리스트만 작성하고 미수집 측정치는 사용할 수 없다고 표시합니다.",
        ),
        "version": CATALOG_VERSION,
        "category": "measurement",
        "status": "template",
        "allowed_operations": ["draft_measurement_checklist"],
        "required_capabilities": ["verified_mcp_binding", "safety_gate"],
        "safety_rules": SAFETY_RULES,
    },
    {
        "id": "evidence-analysis",
        "name": localized("Evidence review", "증거 검토"),
        "description": localized(
            "Define a reproducible analysis checklist without inventing findings.",
            "발견 사항을 만들어내지 않고 재현 가능한 분석 체크리스트를 정의합니다.",
        ),
        "instructions": localized(
            "Prerequisites: obtain genuine retained evidence with source identity, collection "
            "time, integrity digest and scope approval. Separate measured facts, hypotheses and "
            "unknowns. Compare observations with the explicitly stated policy and baseline, "
            "preserving units and missing-data limitations. Cite each proposed finding to its "
            "evidence and record reproducibility steps. No evidence means no finding, not a "
            "successful test. This workspace has no execution evidence; prepare a review "
            "checklist only and never fabricate packet counts, detections or approval.",
            "선행 조건: 출처 식별자, 수집 시각, 무결성 해시와 범위 승인이 있는 실제 보관 "
            "증거를 확보합니다. 측정 사실, 가설과 미확인 사항을 분리합니다. 단위와 누락된 "
            "데이터의 한계를 보존하면서 명시된 정책 및 기준과 관찰 결과를 비교합니다. "
            "발견 사항마다 근거와 재현 절차를 기록합니다. 증거가 없다는 것은 발견 사항이 "
            "없다는 뜻이지 테스트 성공이 아닙니다. 이 작업 공간에는 실행 증거가 없으므로 "
            "검토 체크리스트만 준비하고 패킷 수, 탐지 결과 또는 승인을 만들어내지 않습니다.",
        ),
        "version": CATALOG_VERSION,
        "category": "analysis",
        "status": "template",
        "allowed_operations": ["draft_evidence_checklist"],
        "required_capabilities": ["retained_evidence", "verified_provenance"],
        "safety_rules": SAFETY_RULES,
    },
]

PROFILES_V1 = [
    {
        "id": "tcpreplay-policy",
        "name": localized("Packet replay policy check", "패킷 재생 정책 점검"),
        "description": localized(
            "Planning template: operator-owned capture, isolated DUT/SINK, bounded rate and "
            "duration, explicit stop/rollback criteria. No capture loaded or packets emitted.",
            "계획 템플릿: 운영자 소유 캡처, 격리된 DUT/SINK, 속도·시간 제한 및 명시적 "
            "중지·복구 기준이 필요합니다. 캡처를 로드하거나 패킷을 전송하지 않습니다.",
        ),
        "engine": "tcpreplay",
        "layer": "L2–L4",
        "status": "template",
    },
    {
        "id": "tcpdump-observer",
        "name": localized("Passive packet observation", "수동 패킷 관찰"),
        "description": localized(
            "Planning template: approved observation interface, bounded capture filter, "
            "duration/storage caps and evidence handling. No interface opened or capture started.",
            "계획 템플릿: 승인된 관찰 인터페이스, 제한된 캡처 필터, 시간·저장 용량 상한과 "
            "증거 처리 절차가 필요합니다. 인터페이스를 열거나 캡처를 시작하지 않습니다.",
        ),
        "engine": "tcpdump",
        "layer": "L2–L7",
        "status": "template",
    },
    {
        "id": "k6-http",
        "name": localized("HTTP policy scenario", "HTTP 정책 시나리오"),
        "description": localized(
            "Planning template: approved lab HTTP service, bounded users/request rate/duration, "
            "expected responses and abort criteria. No script executed or HTTP request sent.",
            "계획 템플릿: 승인된 실험실 HTTP 서비스, 사용자·요청 속도·시간 상한, 예상 응답과 "
            "중단 기준이 필요합니다. 스크립트를 실행하거나 HTTP 요청을 보내지 않습니다.",
        ),
        "engine": "k6",
        "layer": "L7",
        "status": "template",
    },
]


def initial_workspace() -> dict:
    return deepcopy(
        {
            "meta": {
                "version": "0.1.0-ui",
                "mode": "OFFLINE",
                "live_enabled": False,
                "live_limit": 1,
                "storage": "local_drafts",
                "deployment": "loopback_development",
                "audit_retention": {"limit": 500, "retained": 0, "total_recorded": 0, "dropped": 0},
            },
            "targets": [],
            "instruments": [],
            "mcp_servers": [],
            "profiles": PROFILES_V1,
            "skills": SKILLS_V1,
            "agent_profile": {
                "name": "Review agent",
                "skill_ids": [],
                "mcp_server_ids": [],
                "autonomy": "REVIEW_ONLY",
                "execution_enabled": False,
            },
            "campaigns": [],
            "runs": [],
            "findings": [],
            "evidence": [],
            "approvals": [],
            "audit": [],
            "capabilities": {
                "draft_editing": True,
                "context_preview": True,
                "live_execution": False,
                "mcp_connect": False,
                "llm_inference": False,
            },
        }
    )
