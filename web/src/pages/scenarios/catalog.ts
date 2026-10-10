import type { TrafficProfile } from "../../lib/contracts";
/** Pinned PROFILES_V1 projection; wire.test verifies against the local Python catalog. */
export const scenarioProfiles: Record<
  "tcpreplay-policy" | "k6-http",
  TrafficProfile
> = {
  "tcpreplay-policy": {
    id: "tcpreplay-policy",
    name: { en: "Packet replay policy check", ko: "패킷 재생 정책 점검" },
    description: {
      en: "Planning template: operator-owned capture, isolated DUT/SINK, bounded rate and duration, explicit stop/rollback criteria. No capture loaded or packets emitted.",
      ko: "계획 템플릿: 운영자 소유 캡처, 격리된 DUT/SINK, 속도·시간 제한 및 명시적 중지·복구 기준이 필요합니다. 캡처를 로드하거나 패킷을 전송하지 않습니다.",
    },
    engine: "tcpreplay",
    layer: "L2–L4",
    status: "template",
  },
  "k6-http": {
    id: "k6-http",
    name: { en: "HTTP policy scenario", ko: "HTTP 정책 시나리오" },
    description: {
      en: "Planning template: approved lab HTTP service, bounded users/request rate/duration, expected responses and abort criteria. No script executed or HTTP request sent.",
      ko: "계획 템플릿: 승인된 실험실 HTTP 서비스, 사용자·요청 속도·시간 상한, 예상 응답과 중단 기준이 필요합니다. 스크립트를 실행하거나 HTTP 요청을 보내지 않습니다.",
    },
    engine: "k6",
    layer: "L7",
    status: "template",
  },
};
