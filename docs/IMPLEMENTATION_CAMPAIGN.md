# 기능 1–12 순차 구현 정본

## 현재 우선순위 변경 — 감독형 OFFLINE 1차 목표

사용자가 첫 목표를 사람이 감독하는 단일 워커·단일 시나리오로 변경했고,
추가 선택에서 **외부 송신 없는 OFFLINE 실행**과 **프로젝트 전용 로컬 환경**을
확정했다. 현재 구현 순서와 수용 기준은 `docs/PHASE1_SUPERVISED_OFFLINE.md`를
우선한다. 자동 장애복구·다중 워커와 원래 S02의 전체 W2 수용은 후속으로 보류한다.
아래 S01–S12 순서는 장기 로드맵/이력으로 보존하며, 보류를 PASS로 바꾸거나 기존
실패·제공자 중단·보정 한도를 지우지 않는다. 1차 목표 완료는 전체 S02 완료나
S03 이후 자동 진입을 의미하지 않는다. 작은 수정→필요 검증→로컬 커밋으로 진행한다.

## 권한과 기준

- 사용자 승인: "1~12번까지 개별적으로 커밋하면서 검증하고 진행해줘. 전체 플랜을 까먹지 않도록 명확히 문서화 하고 그 문서를 기준으로 순서대로 1.개발/검증/커밋/ 2.개발/검증..... 으로 진행해줘."
- 시작 revision: `80f7da4c9a3d09702f165e40c824de46823b1e76`, `master`.
- 기능 정의의 출발점은 2026-10-09 제시한 12개 기능 목록이다. 이 문서가 현재 순서·상태·완료 기준의 정본이다. 원본 PLAN.md, 이전 계획, UI-01/AI-02 계약과 기록은 보존한다.
- 구현·검증·각 기능의 별도 로컬 커밋이 승인됐다. push, 운영망 시험, 사용자 소유 자원 삭제, 임의 외부 endpoint/실장비 조작은 승인에 포함하지 않는다.
- `S01 → S02 → … → S12` 순서를 지킨다. 같은 단계 안에서만 격리된 파일 소유권으로 병렬 구현한다. 다음 단계 제품 구현은 이전 단계의 필수 검증·독립 리뷰·커밋 readback이 끝난 뒤 시작한다.
- 초안·설정·시뮬레이터·실제 모델·Lab·실장비 수용은 서로 다른 결과다. mock PASS, skip, 준비 코드, 버튼 비활성 해제만으로 제품 완료를 선언하지 않는다.
- 장비/권한/환경이 필요한 필수 gate가 막히면 해당 단계를 BLOCKED로 기록하고, 다음 단계로 건너뛰지 않는다. 이미 승인된 정상 개발에 대해서는 매번 재승인을 묻지 않는다.

### S02 수동 검토 체크포인트 예외

사용자가 “백엔드 실제 브라우저 통합 검증 제외하고 commit 해줘. 우선 동작 검토해볼게”라고 명시 승인했다. 이번에 한해 현재 후보를 수동 검토용 중간 커밋으로 남기고 backend·실제 브라우저 통합 수용을 보류한다. Web 검증 및 정확한 파일/커밋 대조는 유지한다. 이는 S02 완료 선언이나 S03 진입, 미검증 backend의 수용, 차단 작업 우회, 운영 서비스 변경, push 또는 naming/history 변경 승인이 아니다. 기존 실패 기록과 미완료 항목은 `docs/S02_REVIEW_CHECKPOINT.md` 및 로컬 campaign receipt에 보존한다. 아래의 전체 단계 완료 절차는 S02 최종 수용에 계속 적용한다.

## 완료 절차 — 매 단계 동일

1. 현재 HEAD/index/작업 상태, 직전 gate와 기존 사용자 파일을 재확인한다.
2. 해당 단계 계약에 schema, 상태 전이, 권한, deadline/byte/count 예산, 실패 처리, 파일 소유권, 테스트와 수용 기준을 고정한다. 독립 계약 검토 후 구현한다.
3. 실제 동작을 대상으로 RED→GREEN TDD를 수행한다. import/설치 오류는 기능 RED로 세지 않는다.
4. UI·API·저장소/worker/transport까지 요구된 실제 경로를 검증한다. 원본 증거와 테스트 산출물을 구분한다.
5. 동결된 소스에 독립 명세·품질 리뷰를 수행하고 blocker를 재현·수정한다. 수정/재검토는 기본 최대 2회, 이후 남은 blocker와 필요한 결정을 보고한다. S01의 S01-RET-REVIEW-01에 한해 사용자 추가 승인으로 누적 최대 3회이며, 다른 단계/결함의 한도를 초기화하지 않는다.
6. 마지막 편집 뒤 canonical `make test`, `make lint`, `make build`, `make test-e2e` 및 해당 단계의 추가 gate를 실행한다. 새로운 테스트 디렉터리는 반드시 canonical target에 포함한다.
7. 명시된 파일만 stage하고 index blobs/modes와 수용 manifest가 같은지 확인하여 한 기능을 한 커밋으로 기록한다. 필요한 수정 커밋이 생기면 기존 이력을 고치지 않고 대상 단계와 사유를 명시한다.
8. 새 commit/parent/tree를 읽어 확인하고 별도 exact-commit checkout에서 gate를 검증한다. 단계 status와 receipt에 commit SHA·실제 명령·결과·검증 범위·한계를 남긴다.
9. 완료된 단계는 자동으로 다음 단계에 진입한다. 완료 문구를 먼저 쓰거나, 다음 단계 기능을 앞선 커밋에 섞지 않는다.

문서의 자기 commit SHA는 자기참조가 불가능하므로 각 기능 커밋에는 단계 ID와 수용 기준을 기록하고, 생성된 SHA/최종 readback은 `.hermes/artifacts/campaign-01/state.json`에 즉시 남긴다. 다음 단계 커밋에서 아래 표의 직전 단계 SHA를 갱신한다. 마지막에는 별도 closeout 문서 커밋으로 정확한 전체 이력을 정리한다. 이 기록용 커밋은 기능을 분할/합치는 수단이 아니다.

## 단계별 계약·완료 기준

| 순서 | 기능 / 의도한 commit subject | 필수 제품 결과 | 추가 수용 gate | 현재 상태 |
|---|---|---|---|---|
| S01 | `feat(scenarios): add versioned test definitions and expected policies` | 실제 대상/DUT·정책 버전/프로필/자산 메타데이터/기대 정책/예산/증거 요구를 연결한 불변 시나리오 revision, 생성·수정·이력·영한 UI | 저장 재개, CAS 충돌, 원본 이력 보존, API→Chromium, 초안 등록 부작용 0 | IMPLEMENTED_REVIEW_ACCEPTED · 독립 6+22행 및 부모 API1160/UI319/Chromium86/복구8+3 PASS. 최종 문서·활성·커밋/exact는 receipt로 별도 확인; 완료 전 S02 금지 |
| S02 | `feat(runs): add durable offline job orchestration` | PostgreSQL의 실행 snapshot·큐·worker claim/fence·상태·취소·재시작 복구, 실제 Run UI | 실제 DB와 별도 worker, 중복 claim/재시작/late completion, OFFLINE만 허용, LIVE 거절 유지 | PENDING |
| S03 | `feat(evidence): ingest and retain bounded measurement evidence` | PCAP/정형 DUT 로그/메트릭 입력, 원본/digest/manifest, 출처·단위·시각·누락 품질, Run 연결 | 실제 파일→worker→API/UI, 파일/DB crash 복구, quota·손상·path traversal·시간 불확실성 | PENDING |
| S04 | `feat(evaluation): add deterministic verdicts and bilingual reports` | 6종 판정, 개별 기준 SATISFIED/VIOLATED/UNKNOWN, 실제 Findings/Evidence/Run detail, 영한 JSON/HTML | 전체 정책/탐지/전달 진리표, 사실·해석 분리, 동일 증거 재현, 실제 worker/브라우저/export | PENDING |
| S05 | `feat(governance): enforce roles approvals and credential boundaries` | viewer/operator/admin, 승인 범위/만료/취소, secret reference 해석, 안전한 outbound 접속 정책, 감사 | 역할×동작 denial matrix, stale/expired 승인 부작용 0, 비밀 비노출, 로그인/CSRF, 실제 접속 정책 경계 | PENDING |
| S06 | `feat(mcp): connect reviewed tools through an instrument broker` | 명시적 연결/discovery, 실제 wire schema 검증·pin, tool/물리 자원 binding, effects 분류·오류 처리 | 별도 실제 MCP 프로세스/HTTP transport, schema drift·response loss·redirect·SSRF·budget; simulator 라벨 유지 | PENDING |
| S07 | `feat(safety): enforce independent lab limits and verified stops` | 승인 대상/전체 예산·LIVE 1, 독립 Guardian, permit/lease/fence, 실제 중단·소유 복구·격리 | 소유 격리 환경의 실제 송신 관측, baseline permission 분리, 제어 경로 hang·heartbeat 생존·소진 fault, 정지/반납 readback | PENDING |
| S08 | `feat(lab): run bounded replay and collect independent observations` | 별도 Linux Lab의 tcpreplay/tcpdump/probe·DUT 로그, 센서 준비→baseline→시험→수집/정리→판정 | UI→worker→실제 MCP→프로세스→PCAP→판정, baseline 실패 부하 0, 정지/누락/손실 fault, 실제 DUT 경로 | PENDING |
| S09 | `feat(ai): connect configured models for bounded evidence analysis` | 모델 프로필 실제 호출/연결 테스트, Skill 컨텍스트, 구조화된 증거 기반 분석, 취소·호출 예산·감사 | 승인된 실제 모델 endpoint, timeout/stream/cancel·없는 evidence·비밀 노출 방지; 장비 동작 비활성 | PENDING |
| S10 | `feat(agent): execute typed actions within approved scope` | REVIEW_ONLY/APPROVED_AUTONOMOUS, 검증된 typed action→같은 Safety Gate/Broker, episode/round 예산 | 실제 모델→MCP Lab→관측/cleanup 연결, 허구 tool·prompt injection·범위 초과 거절, 모델 중단 시 결정론적 종료 | PENDING |
| S11 | `feat(instruments): integrate and verify the first external device` | 실제 계측기 1종 identity/소유 예약/설정 readback/계측/native 결과/복구·반납 | 실제 AI→승인 action→해당 실장비→측정→소유 반납의 단일 증거 trace; 능동 출력은 별도 safety gate | PENDING_EXTERNAL_INPUT |
| S12 | `feat(campaigns): add bounded repetition and regression comparison` | 승인된 시나리오 자동 반복, 총량 회계, 유효/무효 재현율, DUT/정책 버전 비교·재검증·coverage | 실제 수동/AI campaign 종단, 중단/복구·예산 소진, 최소 20개 독립 시험 전체 MVP gate 및 UI/보고서, 재명명 count 부풀리기 금지 | PENDING |

위 subject는 계획이며 실제 기능과 gate가 달라지면 완료 범위를 축소하지 말고 먼저 blocker를 기록한다. 준비용 산출물만 만들었으면 완료용 subject를 쓰지 않는다.

### S01 보정과 승인된 복구 정책 — 2026-10-10 이력

아래 1·2차 BLOCKED 및 3차 검토 중 문구는 당시 기록이다. 현재 판정은 이력 뒤의 "S01 독립 수용 결과"와 표를 따르며, 원본 실패 자료는 그대로 보존한다.

- 독립 UI/조합 검토는 통과했지만, 저장 실패 정리에서 caller 대체 파일을 삭제하는 S01-B01과 최초 fstat 실패 후 임시 파일이 남는 S01-B02가 재현됐다.
- 1차 보정 `deleg_9207279d`는 진단과 회귀 테스트 추가로 종료됐다. 제품 수정/GREEN은 없다. canonical API 922 PASS / 3 FAIL, 별도 UI 301 PASS, lint PASS. 부모도 새 회귀 15개 중 3개 실패를 직접 재현했다.
- 사용자 승인 원문: `“실패 데이터 한도 내 보존 → 추가 저장 차단 → 명시적 복구” 으로 진행해줘.` 이전 무응답 기록은 이 승인으로 해소됐다. 동일한 정책을 다시 승인받지 않는다.
- 저장소별 최대 16 MiB의 대기 데이터와 크기가 제한된 복구 기록을 보존한다. 실패 경로에서 자동 삭제·재전송하지 않고 추가 저장을 차단하며, 유효한 기존 이력 조회는 유지한다. 아래 2차 후보에서 보존·복구·재시작의 여러 실제 경로가 검증됐지만, 동일 프로세스 peer 차단 경쟁 조건 때문에 전체 제품 수용은 미완료다.
- 이 승인은 통상 실패 시 잔여 파일 0 기준을 명시적 한도·보존·복구 기준으로 바꾼다. caller 파일 보존, 이력 불변성, publication 전 preimage, publication 후 불확실성, 전체 byte/count 한도 및 독립 검토를 면제하지 않는다. 기존 실패 증거와 테스트 변경 사유를 남긴다.
- 근거: `.hermes/artifacts/campaign-01/S01/correction-01-result.json` 및 `retention-policy-approval.json`. 1차 보정 후 남은 2차 보정을 이 정책으로 진행했으며 현재 두 회차가 모두 소진됐다. 보정 횟수는 초기화하지 않는다. 실제 복구 계약·TDD·독립 검토·전체 gate가 끝나기 전 S01 커밋 및 S02 진입을 하지 않는다.
- 설계 초안 `deleg_3ee1f128`의 파일시스템 모형 82개 및 CLI 왕복은 부모도 재실행해 통과했다. 제품 parser/API/UI 수용이나 B01/B02 수정 성공은 아니다. 해당 초안의 모든 재시작 수동 복구와 일부 초기 실패의 CLI 복구 불가 제약은 채택하지 않았다.
- 추가 확인에서 사용자는 `완료 기록·저장본·대기 파일 검증 후 정상 재시작 허용` 및 `운영자의 명시 확인·보관 후 현재 유효 저장본으로 복구 허용`을 모두 선택했다. `retention-availability-approval.json`에 정확한 범위를 기록했으며 같은 결정을 다시 묻지 않는다. 완료 기록 직후 오류라도 새 소유자의 CLEAN 검증이 통과하면 재개할 수 있고, 불완전 자료는 자동 초기화가 아니라 명시적 accept-current 보관·결정 기록으로만 처리한다.
- `docs/stages/S01_RETENTION_RECOVERY.md`가 2차 보정의 상세 정본이다. 16 MiB pending·4 KiB receipt·한도 있는 무덮어쓰기 archive/decision, 실제 recovery CLI, fresh-process/오류/정상 재시작, canonical 및 독립 수용이 필요하다. 모형의 GREEN을 새 정책이나 제품의 GREEN으로 전환하지 않는다.
- 영·한 안내 및 UI write-block latch는 `retention-ui-contract.json`의 좁은 승인 범위로 `deleg_1c270bae`가 별도 작업공간에서 TDD 보정했다. 부모가 2개 변경 파일/178개 보호 파일을 확인하고 UI 319개와 lint/build를 다시 실행해 통과했다. 서버 격리를 UI latch로 대체하지 않으며 모든 재시작에 수동 복구가 필요하다는 문구는 넣지 않는다.
- backend `deleg_b33b08f1`의 10개 변경 파일과 175개 보호 파일, 소스에 결합된 API 1144/UI 301·focused 293 실행 증거를 부모가 확인했다. 이는 증거 검증이며 부모의 재실행이나 독립 수용을 뜻하지 않는다. UI 보정과 영·한 운영 안내를 합친 186개 파일 후보는 별도 `s01-retention-integrated`에 있으며, 독립 `deleg_4b1519b4`의 저장소와 실제 Chromium→API→offline CLI→재시작 조합 검토가 완료됐다. 부모 통합 lint/build와 전체 `make test`(API 1144/UI 319, exit 0)가 통과했다. 색상 코드 때문에 집계 wrapper만 exit 1이었던 기록은 보존했고, 외부 검증 스크립트의 RED→GREEN 및 원본 로그/JUnit 재집계로 구분했다. 제품 소스 수정이나 전체 시험 재실행으로 표현하지 않는다.
- 독립 backend: 필수 22행 중 20 PASS, COORDINATOR/SINGLE_USE_HANDOFF 2행 BLOCKED. focused 293 및 추가 API 205 PASS, 별도 adversarial 40 PASS/3 FAIL이며 세 실패는 같은 원인의 재현이다. 기존 B01/B02는 승인된 보존 정책과 실제 selector firing 기준으로 해당 후보에서 해소됐고, 원본 RED는 보존한다.
- 새 P2 `S01-RET-REVIEW-01`: `scenario_store.py:36-44,145-149`에서 진행 중인 성공 저장이 동시에 생성된 peer의 invalid/consumed-ticket 차단을 지운다. 환경을 바꾸지 않은 실제 자식 프로세스에서 ACTIVE→PREPARED→PUBLISHED→CLEAN 이후 peer 요청이 503 대신 HTTP 201/revision 3을 반환했다. 부모도 변경 없는 `test_consumed_ticket_peer.py`를 재실행해 순차 대조 1 PASS/동시 실행 1 FAIL(exit 1)을 확인했다. 이는 시나리오 메타데이터 저장 허용 결함이며 원격 인증 우회나 실제 장비 동작을 입증한 것은 아니다.
- 독립 UI: UI 319/lint/build/기존 Chromium E2E 86 PASS, 실제 브라우저 저장 오류 수명주기 8개 및 accept-current CLI/API 3개 PASS. syscall fault만 합성이며 Chromium/HTTP/CLI/저장소는 실제 실행이다. 이 조합 PASS는 backend 경쟁 조건을 면제하지 않는다.
- 현재 판정은 `BLOCKED_CORRECTION_LIMIT`. 부모는 보고서·XML·소스 186개·HEAD/NUL index와 재현 결과를 확인했다. 제품 추가 수정·활성 코드/서비스/데이터 반영·커밋·S02는 하지 않았다. 이미 승인된 복구 정책은 유지하며 추가 보정은 별도 명시 결정이 필요하다. 정본 결과: `.hermes/artifacts/campaign-01/S01/retention-review-result.json`. 동결 후보의 문서는 당시 검토 입력으로 보존하고, 이 현재 상태 기록과 구분한다.

### S01 peer 차단 한정 추가 보정 승인 — 2026-10-10

- 위 `BLOCKED_CORRECTION_LIMIT`은 2차 종료 당시의 실패 기록이다. 이후 사용자가 `이 결함에 한해 보정 1회 추가 허용`을 선택했다. `peer-fence-correction-approval.json`이 정확한 질문·응답·수용 행을 보존한다. 승인 대기만 해소됐으며 실패 판정은 아직 해소되지 않았다.
- 기존 2회 소비를 유지하고 S01-RET-REVIEW-01만 1회를 추가한다(누적 한도 3회). 보존·복구·CLEAN 재시작·accept-current 정책과 API/UI/CLI 계약은 변경하지 않는다. 원본 RED와 동결 후보를 보존하고 별도 격리 후보에서 최소 보정한다.
- 동일 coordinator의 생성자 admission/차단 전이와 저장 완료가 같은 path lock으로 직렬화되어야 한다. 전역 registry guard를 잡고 path lock을 기다려 다른 저장소까지 막지 않는다. 이미 사용한 티켓의 동일 환경 실제 프로세스 및 invalid-ticket의 순차/겹침 재현을 canonical 회귀로 고정하고, 정당한 peer 공유·다른 path 진행·오류 owner 차단·새 CLEAN 재시작을 검증한다.
- 독립 재검토와 변경 후 전체 gate를 다시 수행한다. 추가 회차도 실패하면 더 수정하지 않고 보고한다. 기존 순차 개발·별도 커밋 권한은 유지하지만, S01 blocker가 닫히기 전 활성 승격·커밋·S02 진입은 없다.
- `deleg_38054f1d` 구현 완료: 제품 변경은 `scenario_store.py` 생성자의 peer 차단을 전역 guard 해제 후 path lock 안으로 옮기는 최소 수정이며, canonical peer 회귀 16개를 추가했다. 원본/첫 canonical RED를 보존했고 구현 실행은 외부 probes 43, focused 309, 전체 API 1160 및 Ruff PASS다. 부모는 185개 보호 파일/7개 원본 증거와 실행 receipt/hash를 확인하고, 정확한 preimage에 patch를 적용해 187개 postimage 바이트 일치를 검증했다. 이 확인을 부모의 API 재실행이나 독립 수용으로 세지 않는다.
- 통합 후보는 `s01-peer-fence-integrated`, manifest는 `s01-peer-fence-review-manifest.json`이다. 부모 lint/build와 전체 `make test`(API1160/UI319, 실제 make/wrapper 모두 exit0)가 통과했다. `proc_2522f5c8c302`는 종료됐으며 새 peer 회귀16개 수집·API 실패/오류/skip0·187파일 불변을 확인했다. 별도 read-only `deleg_f50e0d17`이 공유 6행과 기존 backend 22행을 재검토한다. 차단 리뷰가 닫힌 뒤 실제 Chromium/CLI 복구·활성 반영·로컬 커밋/exact gate를 완료해야 한다. 현재 결과는 `.hermes/artifacts/campaign-01/S01/peer-fence-integration-result.json`에 기록했으며 기존 실패 기록과 추가 회차의 소비를 유지한다.

### S01 독립 수용 결과 — 2026-10-10

- `deleg_f50e0d17`의 read-only 독립 검토가 완료됐다. 공유 보정 6행과 기존 backend 22행 모두 PASS다. 변경 없는 원본 probes 43개, canonical focused 309개와 새 독립 6개가 통과했다(독립 실행 358개, API 전체 수와 중복 합산하지 않음). Ruff PASS. 모든 제품 187파일·원본 증거 7파일·HEAD/NUL index가 불변이다.
- 부모는 전체 API1160/UI319·lint/build PASS를 확인했고, 독립 검토 종료 후 Chromium E2E86과 실제 브라우저 저장 실패→차단→offline CLI→fresh API 복구 8개 및 accept-current 3개를 실행해 통과했다. fault syscall만 합성이며 HTTP/브라우저/CLI/저장소는 실제다. E2E 자체는 exit0이지만 처음 wrapper가 TIME_WAIT를 listener로 오인한 exit1을 보존했다. 실제 listener 거절/TIME_WAIT 재사용 두 개의 harness 대조로 관찰기를 수정했고, 제품 소스 수정이나 E2E 재실행으로 표현하지 않는다.
- S01-B01/B02 및 S01-RET-REVIEW-01은 승인된 계약과 현재 구현에서 해소됐다. 보정은 누적3/3회 소비했으며 실패 기록과 과거 검토 입력은 보존한다. 실제 소스·테스트를 바꾸지 않은 최종 문서 묶음에서도 canonical gates를 실행해야 한다. 소유권·저장본 보존을 확인한 활성 반영, 로컬 커밋 readback과 exact-commit 검증까지 통과한 뒤에만 S02에 진입한다.
- `docs/SCENARIOS_VERIFICATION.md`가 현재 구현의 검증 범위를 요약한다. `.hermes/artifacts/campaign-01/S01/isolated-acceptance.json` 및 `peer-fence-review-result.json`은 격리 수용 기록이며, 생성된 commit SHA·최종 release/active/exact 결과는 로컬 `state.json`에 기록한다. 이 문서 자체의 커밋을 검증했다고 미리 선언하지 않는다.

## 유지할 공통 계약

- AI 없이도 핵심 실행·중단·판정·보고서가 동작한다. AI는 정책/승인/예산/측정값/판정을 수정하지 못한다.
- 영어/한국어 UI와 보고서, 긴 식별자 원문 접근, 모든 증거 접근을 유지한다. fixture를 실측처럼 채우지 않는다.
- API/queue/worker/SDK/장비/파일/UI에 크기·시간·개수 제한이 실제 집행되어야 한다. 설정 숫자만으로 보장을 주장하지 않는다.
- LIVE 단위는 송신 시간뿐 아니라 장비 예약부터 정지·반납 확인까지다. 불명 효과를 자동 재전송하거나 slot을 조기에 반환하지 않는다.
- baseline probe·시험 부하·monitor/recovery probe를 구분하고 합산 예산에 포함한다. 안전 중단은 모든 능동 송신을 중단한다.
- 기존 v2의 중단 시간 목표(로컬 신호 2초, 제어 경로 상실 5초)는 실제 패킷으로 검증할 설계 목표이며 사이트 안전 한도는 아니다.
- 업무상 stop 성공과 transport cancel은 다르다. 원격 effect 불명은 reconciliation/owned cleanup/quarantine으로 처리한다.
- 원본 증거, 실패 기록, 사용자 소유 파일·프로세스·장비 설정을 보존한다. `.env`/credential 원문은 읽거나 출력하지 않는다.
- 현재 local JSON 초안 저장은 실행 DB가 아니다. S02에서 실제 PostgreSQL 실행 저장을 추가하며 기존 초안은 명시적 migration/copy 경계로 보존한다.
- Python/브라우저가 strict schema·문자열·숫자 범위를 공유한다. producer 직렬화 바이트를 실제 consumer에 통과시키는 테스트를 유지한다.
- 활성 UI/API는 타 작업처럼 보호한다. 새 단계의 격리 canonical API/UI부터 검증한다. 기존 개발 서비스 반영은 소유권과 데이터 보존을 확인한 뒤에만 수행하며, 격리 검증을 활성 서비스 검증이라고 부르지 않는다.

## 파일·증거·중단 복구

- 단계 계약: `docs/stages/S01_SCENARIOS.md`부터 각 단계 시작 전에 작성·동결한다.
- 현재 receipt: `.hermes/artifacts/campaign-01/state.json`.
- 단계별 증거: `.hermes/artifacts/campaign-01/Sxx/`에 source manifest, RED/GREEN, 독립 review, final canonical, committed-tree receipt를 보존한다. 이 로컬 산출물은 기본 제품 commit에서 제외한다.
- 구현/리뷰 snapshot은 `$TMPDIR` 아래 소유한 별도 checkout을 사용한다. 부모만 active 통합·stage·commit을 수행한다.
- 세션 재개 순서: 이 문서→state.json→현재 Git→직전 단계 exact-commit receipt→열린 blocker/실행 중 소유 프로세스 확인→현재 미완료 gate부터 재개. 과거 요약의 '다음 예정'만으로 완료 단계를 반복하지 않는다.
- 사용자 기존 `PLAN.md`, `.hermes/` 기록과 `web/tsconfig.tsbuildinfo`는 보존하고 광범위 stage/delete/reset하지 않는다.

## 아직 필요한 실제 환경 정보

S01–S04의 OFFLINE 기능에는 실장비가 필요하지 않다. 이후 필요한 Lab Linux host/격리 인터페이스·DUT/정책·로그/한도, 실제 모델 endpoint/profile, 외부 계측기 모델/API/포트/권한은 실제 호출 전에 확정한다. 환경 부재를 mock 성공으로 대체하지 않으며 단계가 도달하기 전부터 전체 작업을 중단하지 않는다.
