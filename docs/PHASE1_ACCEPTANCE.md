# 1차 목표 수용 결과 — 감독형 단일 OFFLINE 실행

## 판정

**승인된 1차 목표 완료.** 사람이 감독하는 단일 워커로 한 가지 시나리오를
등록·준비 실행하고, 실제 저장 결과를 UI에서 확인하는 로컬 경로를 검증했다.
원래 S02 전체, 자동 장애복구·다중 워커·LIVE/DUT 시험을 완료했다는 뜻은 아니다.

## 구현 커밋

- `124c6df`: 새 1차 목표와 기존 로드맵의 보류 범위 문서화.
- `6e2959c64bced3aa19f9da36999a289c15c10bbe`: 지정한 최초 시도 Run만 처리하는
  one-shot worker, 로컬 배타 소유권, 자동 복구·재연결·queue drain 배제.
- `662ee18a82cdcd67d6c1cc286fbaaa6850f06adf`: 원본 소유권을 검증하는 retained
  workspace create/open/worker, 정상 종료 시 데이터 보존, 운영 명령과 browser case.

## 최종 소스로 직접 확인한 경로

1. 통합 checkout에서 새 private PostgreSQL·loopback API/UI workspace 생성.
2. Chromium UI로 DUT/SINK **메타데이터**와 시나리오 v1, OFFLINE Run 생성.
3. 브라우저 밖의 명시적 CLI로 해당 Run의 worker를 정확히 한 번 실행.
4. 실제 `SUCCEEDED`, attempt 1, 이벤트 5개와 EN/KO manifest 표시 확인.
5. 별도 PostgreSQL SELECT의 snapshot/result 바이트와 HTTP 결과의 일치 확인.
6. 정상 종료·명시적 reopen 후 같은 terminal/result 바이트가 유지됨을 확인.
7. API/UI/worker와 관찰된 Chromium 자손 identity를 기록하고 native retirement
   clean/잔여 자손 없음 확인. 데이터 volume과 원본 기록은 삭제하지 않고 보존.

최종 Run은 `88f57384-d8d7-4b7c-b882-f4af530e3fb8`이다. 결과는
`NOT_EVALUATED`, measurements null, defense_verdict null이다. 실제 DUT로 시험
트래픽을 보낸 적은 없으며, 로컬 API/DB 제어 통신을 무통신으로 표현하지 않는다.

## 검증과 증거

- 최종 `make test-phase1`: **813 passed**. 원래 W2 fault suite는 실행하지 않았다.
- 최종 `make test-web`: **2076 passed / 56 files**.
- `make lint`, `make build`, 새 browser case/config의 명시적 TypeScript·ESLint: PASS.
- 실제 Chromium: fresh normal flow 1건과 같은 Run의 read-only reopen 1건 PASS.
  이는 worker 실행 2회가 아니라 **한 번의 실행과 보존 결과 재조회**다.
- 독립 worker 검토 및 local workspace 소스·단위 검토에서 blocker 없음.
  독립 검토와 부모의 최종 runtime 실행은 별도 증거로 구분한다.
- 기존 UI bundle 크기 경고와 libpq `/dev/null` passfile 경고는 남아 있다.
  숨기거나 실패를 skip/xfail로 바꾸지 않았다.

기계 판독 증거는 로컬 `.hermes/artifacts/phase1/`에 보존한다:
`worker-commit.json`, `local-commit.json`, `worker-review/`, `local-review/`,
`final-normal/result.json`, `final-normal/native-retirement.json`, browser raw
responses/screenshots와 `state.json`. 작성자의 sanitizer 이전 체인을 최종
소스의 fresh 실행으로 재사용하지 않고, 부모가 최종 통합 소스로 새로 실행했다.

## 사용과 한계

운영 명령은 `PHASE1_LOCAL.md`, worker 종료 코드는 `PHASE1_WORKER.md`를 따른다.
검증 workspace는 정상 STOPPED 상태로 보존했으며, 재개는 명시적 `open`이다.
새 workspace에는 `create`, 새로운 queued Run에는 정확한 ID의 `worker`를 쓴다.
이미 완료된 Run의 재실행이나 중단된 작업의 자동 수리는 지원하지 않는다.

- 단일 머신·동일 사용자·협력적 진입점·loopback 개발 운영 범위다.
- 멈췄거나 불확실한 작업은 보존하고 차단한다. 자동 복구/HA 보장은 없다.
- 기존 history 목록은 명시적 새로고침이 필요할 수 있다. 기존 UI의 시도/동시성
  상한 표시는 원래 저장 형식의 한도이며, Phase 1의 자동 재시도·다중 워커 허용이 아니다.
- LIVE, 외부 대상 송신, DUT 계측·방어 판정, MCP/AI 실행은 후속 범위다.
- 원래 S02의 미완료·제공자 중단 기록은 그대로 남으며 S03–S12로 자동 진입하지 않는다.
