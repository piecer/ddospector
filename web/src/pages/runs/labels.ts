import type { Locale } from "../../lib/contracts";
import { errors } from "./errors";
export const notices: Record<string, readonly [string, string]> = {
  RECOVERY_MEMORY_ONLY: [
    "Recovery is memory-only; reload loses it.",
    "메모리에서만 복구할 수 있으며 새로고침하면 잃습니다.",
  ],
  RECOVERY_CHECKPOINT_UNSAVED: [
    "Latest verification is not saved; reload restores only the saved checkpoint.",
    "최신 확인은 저장되지 않았으며 새로고침하면 저장된 확인 지점만 복원됩니다.",
  ],
  RECOVERY_STORAGE_UNKNOWN: [
    "Recovery storage cannot be read; new submissions are blocked.",
    "복구 저장소를 읽을 수 없어 새 제출이 차단되었습니다.",
  ],
  RECOVERY_STORAGE_INVALID: [
    "Invalid recovery data retained; explicit recovery required.",
    "잘못된 복구 데이터를 보존했습니다. 명시적 복구가 필요합니다.",
  ],
  RECOVERY_IDENTITY_CONFLICT: [
    "Recovery identity conflict; nothing was overwritten.",
    "복구 식별자 충돌로 덮어쓰지 않았습니다.",
  ],
  RECOVERY_CLEAR_UNCONFIRMED: [
    "Run verified; receipt clearing unconfirmed. New submissions remain blocked.",
    "실행을 확인했지만 복구 기록 해제는 미확인입니다. 새 제출은 계속 차단됩니다.",
  ],
  RECOVERY_READ_REQUIRED: [
    "Receipt-bound verification required. Retry the saved request read; no response was adopted.",
    "복구 기록에 연결된 확인이 필요합니다. 저장된 요청 읽기를 재시도하세요. 응답을 채택하지 않았습니다.",
  ],
  RUN_CLIENT_INVALID: [
    "The response could not be verified. Retained data is stale; retry a read before any mutation.",
    "응답을 검증하지 못했습니다. 보존된 데이터는 오래된 상태입니다. 변경 전에 읽기를 재시도하세요.",
  ],
  RUN_CLIENT_TIMEOUT: [
    "The request timed out. Its outcome is unconfirmed; read again, never resubmit automatically.",
    "요청 시간이 초과되었습니다. 결과는 미확인입니다. 다시 읽고 자동 재제출하지 마세요.",
  ],
  CANCELLATION_UNCONFIRMED: [
    "Cancellation unconfirmed. Read the run before requesting cancellation again.",
    "취소 확인 안 됨. 다시 취소하기 전에 실행 상태를 읽으세요.",
  ],
};
const korean: Record<string, string> = {
  RUN_BODY_TOO_LARGE: "OFFLINE 요청이 1024바이트 한도를 초과했습니다.",
  RUN_DB_NOT_CONFIGURED: "OFFLINE 실행 저장소가 구성되지 않았습니다.",
  RUN_DB_NOT_READY: "지원되는 스키마와 내구성 설정이 필요합니다.",
  RUN_DB_UNAVAILABLE: "OFFLINE 실행 저장소를 사용할 수 없습니다.",
  RUN_STATE_CORRUPT:
    "보존된 실행 데이터가 잘못되었습니다. 복구를 수행하지 않았습니다.",
  RUN_COMMIT_UNCERTAIN:
    "작업이 반영되었을 수 있습니다. 재시도 전에 요청 또는 실행 ID로 읽으세요.",
  RUN_NOT_FOUND:
    "해당 실행 또는 요청이 없습니다. 이 읽기 시점의 결과이며 진행 중인 요청의 미반영 증명은 아닙니다.",
  RUN_SOURCE_NOT_FOUND: "해당 시나리오 버전이 없습니다.",
  RUN_SOURCE_CONFLICT: "선택한 시나리오 다이제스트가 일치하지 않습니다.",
  RUN_IDEMPOTENCY_CONFLICT: "이 요청 ID는 다른 입력에 연결되어 있습니다.",
  RUN_QUEUE_FULL: "OFFLINE 실행 대기열이 가득 찼습니다.",
  RUN_RETENTION_FULL: "보관 한도에 도달했습니다. 기존 기록을 보존했습니다.",
  RUN_BUSY: "OFFLINE 저장소가 사용 중입니다.",
  SCENARIO_STATE_CORRUPT:
    "시나리오 저장소가 잘못되었습니다. 기존 실행은 독립적으로 읽을 수 있습니다.",
  SCENARIO_STATE_UNAVAILABLE:
    "시나리오 저장소를 사용할 수 없습니다. 기존 실행 읽기는 독립적입니다.",
  VALIDATION_ERROR: "요청 데이터가 잘못되었습니다.",
  LIVE_NOT_AVAILABLE: "LIVE 실행을 사용할 수 없습니다.",
  INTERNAL_ERROR: "서비스가 요청을 완료하지 못했습니다.",
  NOT_FOUND: "해당 API 경로가 없습니다.",
  METHOD_NOT_ALLOWED: "지원하지 않는 요청 방식입니다.",
  REQUEST_TIMEOUT: "요청 본문 수신 시간이 초과되었습니다.",
  ORIGIN_NOT_ALLOWED: "허용되지 않은 출처입니다.",
  HOST_NOT_ALLOWED: "로컬 개발 호스트만 허용합니다.",
  JSON_REQUIRED: "UTF-8 JSON이 필요합니다.",
  UNSUPPORTED_ENCODING: "인코딩된 본문은 지원하지 않습니다.",
  INVALID_FRAMING: "요청 프레이밍이 잘못되었습니다.",
  BODY_TOO_LARGE: "요청 본문이 한도를 초과했습니다.",
};
export function errorText(locale: Locale, code: string) {
  return (
    notices[code]?.[locale === "ko" ? 1 : 0] ??
    (locale === "ko" ? korean[code] : errors[code]?.[1]) ??
    notices.RUN_CLIENT_INVALID[locale === "ko" ? 1 : 0]
  );
}
const terms: Record<string, readonly [string, string]> = {
  QUEUED: ["Queued", "대기 중"],
  RUNNING: ["Preparing", "준비 중"],
  CANCEL_REQUESTED: ["Cancellation requested", "취소 요청됨"],
  SUCCEEDED: [
    "Offline preparation complete; defense not evaluated",
    "오프라인 준비 완료; 방어 결과 미평가",
  ],
  FAILED: ["Preparation failed", "준비 실패"],
  CANCELLED: ["Cancelled", "취소됨"],
  TIMED_OUT: ["Timed out", "시간 초과"],
  CLAIMED: ["Worker claimed", "작업자 할당"],
  SNAPSHOT_VERIFIED: ["Snapshot verified", "스냅샷 확인"],
  MANIFEST_COMPILED: ["Manifest compiled", "매니페스트 작성"],
  REQUEUED: ["Requeued", "다시 대기"],
  SNAPSHOT_INVALID: ["Captured snapshot invalid", "캡처 스냅샷 오류"],
  OFFLINE_PREPARATION_FAILED: [
    "Offline preparation failed",
    "오프라인 준비 실패",
  ],
  RESULT_LIMIT_EXCEEDED: ["Result limit exceeded", "결과 한도 초과"],
  RETRY_EXHAUSTED: ["Retry limit exhausted", "재시도 한도 소진"],
  DEADLINE_EXCEEDED: ["Absolute deadline exceeded", "절대 기한 초과"],
  BEFORE_CLAIM: ["Withdrawn before claim", "할당 전 철회"],
  WORKER_ACK: ["Worker acknowledged", "작업자 확인"],
  LEASE_REVOKED: ["Publication authority revoked", "게시 권한 철회"],
  LEASE_EXPIRED: ["Lease expired", "임대 만료"],
  NOT_APPLICABLE: ["Not applicable", "해당 없음"],
  NOT_DECLARED: ["Not declared", "미선언"],
  DECLARED_UNVERIFIED: ["Declared, not verified", "선언됨, 미검증"],
};
export const term = (locale: Locale, key: string) =>
  terms[key]?.[locale === "ko" ? 1 : 0] ?? key;
