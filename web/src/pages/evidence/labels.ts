import type { Locale } from "../../lib/contracts";
export const warning = (locale: Locale) =>
  locale === "ko"
    ? "OFFLINE 준비만 수행되었습니다. NOT_EVALUATED · 방어 판정 없음(null). 캡처 레코드셋의 단일 기준이며 DUT, 서비스, 세션, 트래픽 예산 또는 전체 시나리오의 성공을 입증하지 않습니다. UNKNOWN은 결론 불가이며 차단 성공이 아닙니다. AI 해석이 아닙니다."
    : "OFFLINE preparation only. NOT_EVALUATED · no defense verdict (null). One capture-recordset criterion: not proof of DUT, service, session, traffic-budget or whole-scenario success. UNKNOWN is inconclusive, never block success. No AI interpretation.";
const labels: Record<string, [string, string]> = {
  evidence: ["Evidence", "증거"],
  report: ["Retained report", "보관된 보고서"],
  schema_version: ["Schema version", "스키마 버전"],
  id: ["Evidence ID", "증거 ID"],
  request_id: ["Request ID", "요청 ID"],
  ordinal: ["Ordinal", "순번"],
  run_id: ["OFFLINE Run ID", "OFFLINE 실행 ID"],
  run_snapshot_digest: ["Run snapshot SHA256", "실행 스냅샷 SHA256"],
  created_at: ["Producer start time", "생산자 시작 시각"],
  provenance: ["Provenance", "출처"],
  sample_id: ["Recognized sample ID", "인식된 샘플 ID"],
  coverage: ["Coverage", "관측 범위"],
  ingress: ["Ingress", "유입"],
  egress: ["Egress", "유출"],
  name: ["Original filename", "원본 파일명"],
  size_bytes: ["Original bytes", "원본 바이트 수"],
  sha256: ["Original SHA256", "원본 SHA256"],
  analysis_state: ["Analysis state", "분석 상태"],
  kind: ["Kind", "종류"],
  rule_id: ["Criterion ID", "기준 ID"],
  scope: ["Scope", "평가 범위"],
  evidence_id: ["Evidence ID", "증거 ID"],
  outcome: ["Criterion outcome", "단일 기준 결과"],
  scenario_evaluation: ["Whole-scenario evaluation", "전체 시나리오 평가"],
  defense_verdict: ["Defense verdict", "방어 판정"],
  policy: ["Snapshot policy", "스냅샷 정책"],
  profile_id: ["Profile", "프로필"],
  ip_version: ["IP version", "IP 버전"],
  protocol: ["Protocol", "프로토콜"],
  expected_action: ["Expected action", "기대 동작"],
  delivery_expectation: ["Delivery expectation", "전달 기대"],
  detection_required: ["Detection required", "탐지 필요"],
  detection_deadline_ms: ["Detection deadline (ms)", "탐지 제한 (ms)"],
  minimum_delivery_pct: ["Minimum delivery (%)", "최소 전달 (%)"],
  maximum_delivery_pct: ["Maximum delivery (%)", "최대 전달 (%)"],
  evidence_requirements: ["Declared requirements", "선언된 증거 요건"],
  captures: ["Observed captures", "관측 캡처"],
  parse_error: ["Parser quality error", "파서 품질 오류"],
  packet_count: ["Observed packet records", "관측 패킷 레코드"],
  wire_bytes: [
    "Recorded wire bytes (not rate)",
    "기록된 전송 바이트 (속도 아님)",
  ],
  payload_bytes: ["Recorded payload bytes", "기록된 페이로드 바이트"],
  first_timestamp_ns: [
    "First observed timestamp (ns)",
    "첫 관측 타임스탬프 (ns)",
  ],
  last_timestamp_ns: [
    "Last observed timestamp (ns)",
    "마지막 관측 타임스탬프 (ns)",
  ],
  timestamps_ordered: ["Timestamps ordered", "타임스탬프 순서 유지"],
  facts: ["Observed matching facts", "관측 매칭 사실"],
  matched_packets: ["Matched records", "일치 레코드"],
  unmatched_ingress_packets: [
    "Missing egress records",
    "유출에서 누락된 레코드",
  ],
  unmatched_egress_packets: ["Egress-only records", "유출 전용 레코드"],
  delivery_basis_points_floor: [
    "Delivery basis points (floor)",
    "전달 베이시스 포인트 (내림)",
  ],
  issues: ["Inconclusive reasons", "결론 불가 사유"],
  unassessed_requirements: ["Unassessed requirements", "미평가 요건"],
  digest: ["Record SHA256", "레코드 SHA256"],
  declared_limits: ["Declared limits (not evaluated)", "선언된 제한 (미평가)"],
  traffic_budget: ["Traffic budget (not evaluated)", "트래픽 예산 (미평가)"],
  stop_conditions: ["Stop conditions (not evaluated)", "중지 조건 (미평가)"],
  max_pps: ["Maximum packets/s", "최대 초당 패킷"],
  max_bps: ["Maximum bits/s", "최대 초당 비트"],
  max_packets: ["Maximum packets", "최대 패킷"],
  max_bytes: ["Maximum bytes", "최대 바이트"],
  max_connections: ["Maximum connections", "최대 연결"],
  duration_seconds: ["Duration (s)", "지속 시간 (초)"],
  max_legitimate_loss_pct: [
    "Legitimate loss limit (%)",
    "정상 트래픽 손실 제한 (%)",
  ],
  max_service_latency_ms: [
    "Service latency limit (ms)",
    "서비스 지연 제한 (ms)",
  ],
  max_cpu_pct: ["CPU limit (%)", "CPU 제한 (%)"],
  max_memory_pct: ["Memory limit (%)", "메모리 제한 (%)"],
  max_sessions: ["Session limit", "세션 제한"],
  management_loss: ["Stop on management loss", "관리 연결 손실 시 중지"],
};
export function label(key: string, locale: Locale) {
  return labels[key]?.[locale === "ko" ? 1 : 0] ?? key;
}
export function status(value: string, locale: Locale) {
  const values: Record<string, [string, string]> = {
    REGISTERED: ["Registered · unassessed", "등록됨 · 미평가"],
    ANALYZED: ["Retained criterion result", "단일 기준 결과 보관됨"],
    SATISFIED: [
      "SATISFIED · criterion satisfied",
      "SATISFIED · 단일 기준 충족",
    ],
    VIOLATED: ["VIOLATED · criterion violated", "VIOLATED · 단일 기준 위반"],
    UNKNOWN: ["UNKNOWN · inconclusive", "UNKNOWN · 결론 불가"],
  };
  return values[value]?.[locale === "ko" ? 1 : 0] ?? value;
}
export function errorText(code: string, locale: Locale) {
  const en = locale === "en";
  if (code === "EVIDENCE_NOT_READY")
    return en
      ? "Evidence storage is not ready. Use an explicitly fresh Phase 2 workspace; no migration is performed here."
      : "증거 저장소가 준비되지 않았습니다. 명시적으로 새 Phase 2 워크스페이스를 사용하세요. 여기서는 마이그레이션하지 않습니다.";
  if (code === "EVIDENCE_NOT_FOUND")
    return en
      ? "Not found at this observation. A previous POST may still commit; retain the request ID and resolve again without reposting."
      : "현재 조회에서 찾지 못했습니다. 이전 POST가 나중에 커밋될 수 있으므로 요청 ID를 유지하고 재전송 없이 다시 조회하세요.";
  if (code === "EVIDENCE_RETENTION_FULL")
    return en
      ? "Retention is full (16 bundles). Existing records are preserved."
      : "보관 한도(16개)에 도달했습니다. 기존 기록은 유지됩니다.";
  if (code === "EVIDENCE_CLIENT_TIMEOUT")
    return en
      ? "The bounded operation timed out or was stopped. No automatic retry."
      : "제한된 작업 시간이 만료되었거나 중지되었습니다. 자동 재시도하지 않습니다.";
  return en
    ? "The operation could not be validated or storage is unavailable. No empty collection or result is inferred. Previous displayed data is stale."
    : "작업을 검증할 수 없거나 저장소를 사용할 수 없습니다. 빈 목록이나 결과로 간주하지 않습니다. 이전 표시 데이터는 오래된 데이터입니다.";
}
