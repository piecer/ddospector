# P0-B1 · 로컬 callback 실행 승인 계약

## 범위

PLAN_PROGRESS2 P0-B의 첫 수직 구현이다. 기존 `SessionOwner.admit → run_attempt`
경계에 별도 운영자 승인, 정확한 binding, 유효창 및 single-use를 집행한다.
선택되지 않는 별도 validator나 선택적 legacy 우회 경로가 아니다.

이는 **신뢰된 동기 callback의 로컬 admission**이다. 실제 HTTP/capture/packet
송신 adapter, 독립 Guardian, 물리적 중단, 현장 장비 수용을 구현했다는 뜻이 아니다.
P3-00의 `CONFIG_VALID_NO_NETWORK`, `baseline_execution_supported:false`,
`site_verified:false` 및 기존 API/CLI의 실행 거절은 유지한다.
OFFLINE 준비 worker와 시나리오 저장도 이 local callback API와 다른 경계다.

## 호출 및 호환성 변경

명시적 public namespace는 그대로다.

```python
from ddospector.lab.session import SessionOwner

owner = SessionOwner.admit(
    reviewed_profile_bytes,
    separately_confirmed_profile_sha256,
    private_state_directory,
    raw_authority=reviewed_authority_bytes,
    confirmed_authority_sha256=separately_confirmed_authority_sha256,
    site_binding=operator_supplied_site_context,
)
```

위 이름들은 호출자가 제공할 입력이지 자동 발견/승인 예제가 아니다. 성공 뒤에는
기존 `run_attempt`, `finish`/`close` lifecycle을 지켜야 한다.

- 기존 세 인자만의 유효 호출은 `AUTHORITY_REQUIRED`다.
- profile 확인과 실행 authority 확인은 별개다. 검증 결과의 hash를 자동으로 복사해
  승인으로 간주하는 factory/CLI/HTTP route는 제공하지 않는다.
- `admit_authorized` 같은 optional 경로와 성공하는 legacy admit을 병렬로 두지 않는다.
- 내부 parser는 `aiddos.lab.authority`다. 별도 public profile/authority module이나
  모델 도구·문자열 명령·자동 실행은 추가하지 않는다.
- local record/snapshot은 **schema 2**다. 기존 v1 claim을 읽거나 migration하지 않는다.

## Closed authority 문서 v1

Exact bytes, strict UTF-8 JSON, 최대 **8192 bytes**. 모든 key가 필수이며 객체마다
extra/duplicate key를 거절한다. float, bool-as-int, NaN/Infinity, 잘못된 encoding,
lone surrogate, decoder depth/정수 제한 오류는 `INVALID_AUTHORITY`다.
표준 JSON에서 `-0`는 int 0과 같은 값이다. 문자열은 trim/normalize하지 않는다.

| 객체 | exact keys / 제약 |
| --- | --- |
| root | `schema_version`, `scope`, `profile_sha256`, `site`, `owner`, `not_before_unix_ms`, `expires_unix_ms`, `budget` |
| schema_version | exact int 1 |
| scope | exact string `LOCAL_BASELINE_CALLBACK_ONLY` |
| profile_sha256 | lowercase64hex, 검증한 전체 profile의 canonical SHA256와 동일 |
| site | `site_id`, `dut_id`, `sink_id`, `isolation_ref` |
| owner | `state_directory`, `st_dev`, `st_ino` |
| budget | `max_attempts`, `min_interval_ms`, `concurrency`, `request_timeout_ms`, `overall_timeout_ms`, `retries` |

Site 값은 `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`이며 DUT/SINK ID는 서로 달라야 한다.
별도로 전달한 `site_binding`도 exact dict/str/key/value 형태여야 하며 문서의 site와
literal equality를 만족해야 한다. **운영자 선언의 일치일 뿐 실제 격리망·장비 인증이 아니다.**

Owner 경로는 기존 SessionOwner의 absolute/private-directory 문법이다. caller 경로와
동일해야 하며 resolve/정규화하지 않는다. dev/inode는 exact uint64이고 실제 취득한
private root FD의 fstat와 같아야 한다. root를 새 inode로 바꾸거나 다른 directory에
승인을 복사하는 것으로 사용할 수 없다.

Budget은 기존 profile validator의 범위도 만족하고, 검증한 profile의 여섯 값과
**정확히 일치**해야 한다. 적은 예산을 선택하려면 profile과 승인을 함께 새로 확정한다.
조용한 clamp/merge는 하지 않는다. 전체 profile hash가 목적지·source 주소·NIC 문자열·
HTTP 조건·예산을 고정하므로 새 profile 확인만으로 과거 authority를 재사용할 수 없다.

문서 canonical SHA256의 별도 확인이 필수다. canonical 규칙은 profile과 같은
UTF-8 JSON(sort_keys, compact separators, ensure_ascii=False)이며 LF는 hash에서 제외한다.
원본 JSON의 whitespace/key 순서는 의미를 바꾸지 않는다. hash는 내용 일관성과
별도 확인값의 일치를 검사하며 서명·인증 issuer 또는 악의적인 동일 Python 방어가 아니다.

## 유효창과 만료

- not-before/expiry는 exact nonnegative int64 Unix milliseconds다.
- `not_before < expires`, 차이는 최대 **300000 ms**다. 승인 사용창이지 트래픽 안전 한도가 아니다.
- 최초 wall 시각이 not-before 전이면 `AUTHORITY_NOT_YET_VALID`다. equality는 허용한다.
- `now >= expires`는 `EXPIRED`다. expiry equality는 거절한다.
- 최초 admission monotonic 시각을 기준으로 기존 overall budget과 최초 wall 시각에서
  계산한 승인 잔여시간 중 더 짧은 deadline을 고정한다. validation/I/O가 이 기점을 바꾸지 않는다.
- validation 후, 실제 root 취득 뒤 claim 직전, claim 후 마지막 반환에서 만료를 검사한다.
- reservation, 실제 callback-entry, permit checkpoint, callback/end post-check 및
  terminal/root-close 뒤 최종 settlement에서도 monotonic과 현재 wall expiry를 검사한다.
- wall 후퇴는 고정 monotonic lease를 연장하지 않는다. 만료를 이미 관측했다면 별도 latch가
  유지되므로 callback이 만료 예외를 잡고 wall 시각이 돌아와도 성공으로 복구되지 않는다.
- stop 우선순위와 이미 결정된 primary 오류는 유지한다. 만료 latch를 primary failure와
  혼동하여 늦은 현재-permit 취소를 가리거나 I/O/cleanup 오류를 덮지 않는다.

Admission 전 wall-clock 신뢰성은 전제다. callback hang, 임의 OS preemption 또는
filesystem latency의 물리적 상한을 보장하지 않는다. 이 검사는 cooperative하며
독립 watchdog을 대체하지 않는다.

## 거절과 부작용 순서

1. 기존 profile type/검증 → profile 확인 hash → 순수 caller 경로 문법 검사를 유지한다.
2. 필수 authority 입력 중 None이면 `AUTHORITY_REQUIRED`.
3. raw type/closed schema/값 오류는 `INVALID_AUTHORITY`, byte cap 초과는 `AUTHORITY_TOO_LARGE`.
4. 확인 hash/profile/site/path/예산 불일치는 `AUTHORITY_MISMATCH`.
5. 승인 사용창과 현재 기한 검사 뒤 platform/private-directory 취득을 수행한다.
6. 실제 root dev/inode 불일치도 `AUTHORITY_MISMATCH`이며 claim 전에 거절한다.
7. 유효 승인으로 이미 사용한 root의 claim을 만나면 `SESSION_ALREADY_USED`다.

잘못된 profile 확인은 `APPROVAL_REQUIRED`; 잘못된 caller 경로는 authority 누락보다
먼저 `STATE_DIRECTORY_INVALID`일 수 있다. 이 선행 경로 검증에는 OS 효과가 없다.
나머지 private-root/권한/FD 오류의 기존 분류는 그대로다.

Pure authority 거절에는 root open/claim/callback이 없다. 실제 identity를 검사해야 하는
단계는 root FD를 취득할 수 있으나 거절 시 single-close하며 claim/callback은 없다.
Claim은 원래 pinned-dirfd O_EXCL 방식이다. v1/부분/같은 내용의 기존 entry도 읽거나
채택하지 않는다. Claim 생성 뒤 실패는 소비 상태를 남기며 삭제·환불·자동 resume하지 않는다.

이것은 신뢰된 namespace의 root별 single-use다. caller가 root/claim을 삭제·복원하거나
다른 승인으로 여러 root를 사용하는 상황까지 막는 전역 replay/DUT 합산 ledger가 아니다.

## 기록·lifecycle 보존

모든 local record와 snapshot에 `schema_version:2`, `authority_sha256`를 넣는다.
나머지 exact shape, 최대 **8 files ×4096 bytes**, claim/attempt/retirement 의미는
`PHASE3_SESSION_OWNER.md`를 따른다. 원문 승인/site/path/주소/query/CA/예외 내용을
새 기록에 넣지 않는다. 입력 dict 변경이 admitted owner의 불변 승인에 영향을 주지 않는다.

기존 attempt 수·간격·동시성·request/overall deadline·무재시도, active/finalizer lifetime,
close_pending, permit 폐기, primary 예외, 불확실성 및 settlement 후 불변을 유지한다.
RETIREMENT_INTENT와 callback RETURNED는 durable completion/물리적 stop ACK가 아니다.
Callback이 멈춰 있으면 stop을 요청해도 `close=False`, `retired=False`일 수 있다.
새 STOPPED 상태나 패킷 중단 성공을 만들지 않는다.

## 검증과 보존 자료

현재 task 자료: `.hermes/artifacts/progress2-p0b1/attempt-5a1b1221c80b/`.

- `baseline.json`, `accepted-preimage/`: HEAD만 아닌 P0-A의 검토된 overlay와 보호 파일 기준.
- `plan-review.md`: 실행 가능한 계약에 대한 독립 계획 ACCEPT. 구현 수용과 구분한다.
- `authority-required-red.*`: profile 확인만으로 callback 1회 진입하던 실제 predecessor RED.
- `authority-binding-red.*`: 별도 입력을 무시하던 중간 구현의 binding/v2 RED.
- `authority-expiry-red.*`, `expiry-latch-red.xml`: runtime wall 만료 및 caught-expiry/rollback RED.
- `legacy-authority-prerequisite-red.*`: 기존 fixture의 새 승인 prerequisite 부재를 보존한 기록.
- `normal-wire-source-red.log`: 새 src 파일/변경으로 이전 corpus의 freshness가 거절된 기록.

기존 fault selector·주입-fired·상한·오류/정리 assertion을 유지하고, fixture에 합성 승인과
v2 기대값을 명시적으로 추가한다. 경쟁/reopen process는 부모가 만든 동일 승인 bytes/hash를
사용한다. 이 테스트 승인은 실제 운영자/현장 승인 출처의 증거가 아니다.

수용에는 `make test-phase3-config`, `make test-evidence`, `make test-tooling`,
`make test-web`, `make lint`, `make build`, focused API denial 회귀, 독립 구현 검토,
현재 src에 결합된 실제 normal-wire capture와 Node/Chromium parity가 필요하다.
각 실제 exit/집계/source/정리/통합 상태는 task의 `final-gates/closeout.json`에 기록한다.
그 기록이 없거나 실패하면 이 문서/부분 PASS만으로 수용 완료를 추론하지 않는다.

전체 Web gate에서는 별도의 native chat corpus도 이전 `session.py` hash를 고정하여
freshness 실패가 확인됐다. 이 실패를 보존하고 사용자 추가 승인으로 기존 helper의
Agent/Target/Skill 로컬 수집을 각 1회 수행했다. 합성 provider 요청은 총 9회이며
실제 모델·DUT·PG를 사용하지 않았다. 새 `producer-p0b1.json`은 실제 HTTP 65행의
원문과 104개 producer pin을 유지하며 기존 모든 chat bundle은 보존한다. 상세 범위와
증거는 `web/src/pages/ai/chat-skill-producer-data/README.md` 및 task의
`chat-refresh/`에 있다. 이는 새 채팅 기능이나 운영 환경 수용이 아닌 source 증거 갱신이다.

P0-A current corpus는 `tests/fixtures/runs/normal-wire-p0a.json`에 동일 bytes로 보존한다.
새 source에는 새로운 실제 normal-only capture만 current로 승격할 수 있다. 기존 39개
synthetic negative와 원래 `normal-wire.json`은 바꾸지 않는다. 이전 P0-A 2/2 allowance는
닫힌 상태로 유지하며, 이 task의 별도 bounded capture admission과 혼동하지 않는다.

## 아직 열린 P0-B / 현장 gate

- 독립 Guardian/Watchdog, AI/주 실행기 hang 및 제어 경로 상실에도 작동하는 중단.
- 실제 packet/process/device readback과 물리적 차단 수단/운영 절차.
- PPS/BPS/packet-byte/연결 상한 및 DUT별 여러 승인에 걸친 누적 예산·동시성.
- Passive sensor arming → 별도 bounded baseline 허가 → 결과 검증 → 별도 test-load 허가.
- 실제 HTTP(S)/capture adapter, TLS·센서 readiness·DUT/SINK/NIC/격리망의 현장 관측.
- 원격 issuer 인증/RBAC, 실제 모델/Agent 실행, caller 배포 및 full S02/W2.

P0-B1의 로컬 승인 계약 완료는 위 항목의 구현·실행 권한·수용을 의미하지 않는다.
