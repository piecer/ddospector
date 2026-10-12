# S02 수동 검토용 중간 커밋 / Manual-review checkpoint

## 이번 커밋의 범위

사용자가 “백엔드 실제 브라우저 통합 검증 제외하고 commit 해줘. 우선 동작 검토해볼게”라고 승인한 중간 검토본이다. 기존 S02 전체 완료 후 커밋 규칙의 이번 체크포인트 예외이며, S02 완료나 S03 진행 승인이 아니다.

- 포함: OFFLINE Runs UI, strict 응답 파서, 저장된 요청 복구, 제한된 polling, 이벤트/상세 조회, 기존 격리 후보의 API·저장소·worker 구현 및 테스트.
- UI 수정: 재전송 후 조회 실패 시 stale/취소 차단, 원래 300초 예산을 넘긴 자동 조회 금지, 응답 유실 복구 후 올바른 실행 링크.
- UI에 포함된 테스트 입력은 `tests/fixtures/runs/`에 byte-exact 보존했다. 테스트 경로만 옮겼으며 입력·예상 판정은 재생성하지 않았다.
- 검증 범위: Web 단위 테스트, lint, typecheck, build. Web 테스트가 사용하는 기존 로컬 Python oracle은 포함되지만 별도 backend suite나 실제 서버/브라우저 통합 시험은 제외된다.
- 이전 격리 후보의 Web 2,016건/53파일, UI 회귀 20건, Node 입력 5,259건 및 lint/typecheck/build 성공 기록은 보존한다. 커밋용 소스의 재검증 결과와 실제 commit/tree는 로컬 campaign receipt에 기록한다.

Backend and real-browser integration acceptance is explicitly deferred, not passed. This checkpoint does not claim a completed S02 release or production readiness.

## 후속 I3 전용 재개 — 체크포인트 이후

이번 재개는 browser harness 이식과 기존 full-mode 정상 경로만 승인받았다.
`tools/s02_web_probe.py`와 `web/playwright.runs.config.ts`는 저장소 상대 경로,
명시적 own-origin/output, 허용 시험 포트의 실제 소유·ready 증명 및 격리된
PG/API/Vite/worker 수명을 사용한다. fixture와 예상 판정은 변경하지 않았다.

- 최초 실제 full-mode 2개 case가 성공했다: 브라우저 생성·QUEUED 취소·두 번째
  생성의 HTTP 응답 유실·GET-only 새로고침·별도 worker SUCCEEDED·독립 PG
  Snapshot/Result 대조, EN/KO·키보드·390px 확인과 동결 5,259건 Chromium parity.
- 초기 성공 실행의 직접 파일 stderr에서 재오픈 diagnostic이 앞부분을 덮는
  관측기 문제가 발견되어, 원본을 보존하고 harness-only RED→GREEN으로 pipe
  수집을 추가했다. 최종 helper의 실행·Web gates·cleanup은 새 source-bound
  `browser-evidence/report.md`와 `verdict.json`으로 구분한다.
- 기존 30초 test / 10초 expect / 90초 caller 제한, retry=0을 유지한다.
  새로운 허용 포트는 실제 bind 후에만 사용하며 active 5173/5180은 접촉하지 않는다.
- 아래의 “이번 커밋” 및 과거 미완료 항목은 역사 기록이다. 이번 제한된 정상
  경로 성공은 W2 DB fault/COMMIT/fencing/corruption/outage, 최종 producer parity,
  전체 A16–A19, 독립 통합 검토·active/exact-commit 수용을 완료하지 않는다.
  소스/backend/보호 harness와 과거 승인·실패·복구 횟수는 그대로 유지한다.

## 로컬 화면 검토

```sh
make setup
make api       # 별도 터미널: loopback 127.0.0.1:5180
make web       # 별도 터미널: loopback 127.0.0.1:5173
```

브라우저에서 `http://127.0.0.1:5173`의 Runs/실행 메뉴를 검토한다. 이 커밋 작업 자체는 기존 API/UI를 재시작하거나 DB를 만들지 않는다. 포트가 이미 사용 중이면 다른 프로젝트 프로세스를 종료하지 않는다.

기존 초안·시나리오 데이터는 유지된다. 새 버전으로 수동 실행하기 전에 본인 데이터를 백업한다. `.env`, 자격 증명, 실행 중인 외부 자원, 테스트 DB 내용을 제품 상태로 복사하지 않는다.

OFFLINE 실행 이력과 생성/취소에는 별도로 준비된 전용 PostgreSQL과 worker가 필요하다. `AIDDOS_RUN_DB_SOCKET`이 설정되지 않으면 Runs 저장소는 `RUN_DB_NOT_CONFIGURED` 상태이며 자동 생성되지 않는다. 이는 빈 이력이나 성공으로 표시하면 안 되는 정상적인 미설정 경계다. 전체 backend 동작은 이번 검증 범위에 포함되지 않는다.

LIVE 송신, 장비 제어, 모델 호출, 방어 판정은 사용할 수 없다. OFFLINE 준비 결과는 `NOT_EVALUATED`이며 측정값·방어 판정은 null이다.

## 이번에 실행할 Web 검증

```sh
make test-web
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run build
```

먼저 `make setup`으로 프로젝트 Python 3.12 환경과 잠긴 Node 의존성을 설치해야 한다. Web 테스트 일부는 기존 Python catalog/validation/Unicode 또는 네트워크를 거부하는 in-process AI-settings oracle을 호출한다.

## 미완료·알려진 한계

- 최종 backend fault/경쟁·worker/API 통합, 최종 producer byte parity와 전체 S02 A16–A19는 미완료다. 중단된 W2 후보의 추가 변경은 이번 검토본에 합치지 않았다.
- W1 독립 검토의 잘못된 snapshot 오류 분류 및 실행 중 successor fencing 증거 공백은 전체 backend 수용에서 여전히 열린 항목이다.
- 실제 브라우저 생성·취소·복구는 Origin 허용목록과 시험 포트 준비 문제로 완료되지 않았다. 보호 경계를 완화하거나 Origin을 위조하지 않았다.
- 일부 backend/browser 검증 스크립트는 이전 campaign의 `inputs/`, `cohort-evidence/`, 전용 scratch 경로를 요구한다. 이들은 이 체크포인트에서 실행·이식 검증하지 않았으며, `make test`, `make test-runs`, `make test-e2e`의 깨끗한 checkout 성공을 보장하지 않는다. Web 단위 테스트 입력만 독립적으로 포함했다.
- 과거 검증기의 active API GET 접촉 사고, helper 역사본 공백, 중단된 실행·cleanup 증거 공백은 최신 성공으로 소거하지 않았다.
- Vite chunk-size 경고는 숨기거나 기준을 올리지 않고 보존한다.
- 이름 전환/과거 이력 재작성, 서비스 배포·재시작 및 push는 이번 커밋 범위가 아니다.
