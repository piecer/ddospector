# P3-01a · 단일 사용 로컬 세션 소유자

**상태: P3-01a 구현·독립 구현 검토 완료.** 이 문서는 로컬 library의
계약이며 정상 서비스 PASS, 실제 HTTP/capture, Agent/LLM/MCP 실행 수용이 아니다.
P3-00 CLI의 `CONFIG_VALID_NO_NETWORK`, `baseline_execution_supported:false`와
기존 API/Run/Evidence schema는 그대로다. 기존 API/CLI는 이 모듈을 import하지 않는다.

## 명시적 Python API

`from ddospector.lab.session import SessionOwner, SessionError, AttemptPermit`
로만 선택한다. 실제 구현은 `aiddos.lab.session`이고 공개 namespace는 재노출만 한다.
CLI 명령, 문자열 실행, tool registry, 자동 실행·재시도·resume·환경변수 설정 탐색은 없다.

| 호출 | 반환 / 계약 |
| --- | --- |
| `SessionOwner.admit(raw_profile, confirmed_profile_sha256, state_directory)` | 새 owner 또는 `SessionError`. exact bytes profile과 별도로 제공한 canonical SHA256 승인을 요구한다. |
| `owner.run_attempt(action)` | 현재 permit을 받는 신뢰된 동기 callback을 한 번 호출한다. callback은 None만 반환한다. 성공한 end persistence와 post-check 뒤 1-based attempt 정수를 반환하며 서비스 판정은 아니다. |
| `owner.request_stop()` | None. 잠금 아래 stop을 latch하되 callback/파일 I/O 완료를 기다리지 않는다. 물리적 정지 증명이 아니다. |
| `owner.snapshot()` | 아래 exact schema의 새 dict. 파일 재탐색·durable history 조회가 아니다. |
| `owner.finish()` | active/finalizing 중 SESSION_BUSY, 아니면 단일 retirement와 마지막 검사를 마친 새 snapshot. 조기 정상 finish는 INCOMPLETE다. |
| `owner.close()` | stop 요청. active/finalizing이면 False, 그 외 retirement 후 `retired and not cleanup_uncertain`. callback-free unwind도 close_pending을 수행한다. |

승인 hash를 validator 결과에서 자동 복사하여 승인으로 간주하지 않는다. 신뢰된
운영자/호출자가 검토한 profile의 hash를 별도 전달해야 한다. 이 경계는 같은 프로세스의
악의적인 Python에 대한 인증·sandbox가 아니다. 서로 다른 명시적 디렉터리는 별도
세션 범위이며 전역 머신 동시성 제어가 아니다.

호출자는 admit 성공 후 반드시 finish/close를 호출해야 한다. 자동 destructor,
background finalizer, 강제 thread 종료는 없다. Callback은 작업을 다른 thread/process로
분리하거나 permit을 나중 작업 권한으로 재사용하면 안 된다. 후속 adapter는 실제
자원 수명과 cooperative checkpoint를 지켜야 한다. 현재 모듈 자체에는 네트워크
연결·DNS·자식 프로세스 생성·capture 구현이 없고 시험 callback도 inert다.

### Permit

- 읽기 전용 `attempt:int`, `deadline:float`(절대 monotonic 시각), `profile:dict`.
- profile은 **매 접근마다** 새 detached copy다. callback이 수정해도 승인 내용은 불변이다.
- `checkpoint()`는 정상 None, 현재 stop은 CANCELLED, deadline 이상은 EXPIRED다.
  양쪽을 관측하면 CANCELLED가 우선한다. attempt가 끝난 permit은 PERMIT_RETIRED다.
- permit은 active slot 반환 전에 폐기한다. 속성의 read-only 보장은 공개 API이며
  내부 `_` 필드 변경이나 arbitrary interpreter corruption을 방어한다는 뜻은 아니다.

## Admission 순서와 borrowed 디렉터리

1. admission 진입에서 monotonic 시작을 기록한다. 기존 bounded `profile.evaluate`로
   exact bytes, 최대 16384 bytes, 완전한 profile을 검증한다.
2. 별도 승인은 exact str, lowercase64hex, 평가된 canonical digest 일치가 필수다.
3. 디렉터리는 exact str, **encoding/copy/OS 접근 전 1..4096자**, strict UTF-8
   최대 4096 bytes다. NUL, encoding 불가, 상대 경로, leading `//`, 빈 내부 component,
   `.`/`..`, root `/` 이외 trailing slash를 거절한다. resolve/정규화하지 않는다.
4. POSIX dirfd/O_DIRECTORY/O_NOFOLLOW/O_CLOEXEC 등 지원을 확인한 뒤 root를 연다.
   실제 fstat에서 directory, 현재 effective UID 소유, group/other 권한 0을 확인한다.
   final symlink는 거절한다. root `/`도 private/UID 조건을 면제받지 않는다.
5. root FD와 dev/inode를 pin하고 exclusive claim을 기록·fsync·close한 뒤 디렉터리도
   fsync한다. identity와 원래 전체 deadline의 마지막 확인을 통과해야 owner를 반환한다.

경로 문법/type, 확인된 non-directory/symlink/wrongUID/nonprivate는
STATE_DIRECTORY_INVALID다. 일반 open/fstat 실패는 STATE_DIRECTORY_IO_ERROR다.
O_NOFOLLOW|O_DIRECTORY 실패의 보조 관찰은 final-leaf no-follow stat뿐이며,
불명/없음/기타 실패는 IO_ERROR다. 잘못된 승인+잘못된 경로는 APPROVAL_REQUIRED다.
모든 preclaim 거절은 claim0/callback0이며 취득 FD는 single-close한다.

상위 경로는 운영자가 신뢰하는 namespace다. hostile filesystem sandbox나 arbitrary
syscall latency 상한은 없다. root는 **borrowed**이며 library는 chmod, truncate,
rename, unlink, rmdir하지 않는다. unrelated 항목을 순회하거나 삭제하지 않는다.
root pathname 교체를 발견하면 OWNERSHIP_LOST로 추가 작업을 막고 기존 FD만 종료한다.
실제 callback 진입 전 및 최종 publication 전후 identity를 다시 확인한다.

## 단일 사용 및 고정 metadata

`baseline-claim.json`은 pinned dirfd 기준
`O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`, mode0600으로 만든다.
같은 이름의 file/directory/symlink/동일 내용 모두 SESSION_ALREADY_USED이며 열어 읽거나
채택하지 않는다. 부분 write/fsync/close 실패도 claim을 소비한다. 실패 파일을
삭제·재기록하지 않으며 프로세스 재시작으로 다시 사용할 수 없다.

모든 record는 같은 exclusive 방식이다. 제품이 만드는 최대 **8 files × 4096 bytes**,
총 최대 **32768 bytes**, 기존 `profile.canonical` JSON + LF다. raw target/query/CA 경로,
response body, 원문 예외/notes는 넣지 않는다. caller의 기존 unrelated 파일은 이 제품
출력 개수와 구분한다. 아래 key 외 추가 key는 없다.

공통 필드: `schema_version:1`, `profile_sha256:<lowercase64hex>`, `kind`.

| leaf | kind | 추가 필드 |
| --- | --- | --- |
| baseline-claim.json | BASELINE_SESSION_CLAIM | `budget`: exact validated budget dictionary |
| attempt-N-start.json (N=1..3) | ATTEMPT_START | `attempt:N` |
| attempt-N-end.json | ATTEMPT_END | `attempt:N`, `outcome:RETURNED/FAILED/CANCELLED/EXPIRED`, `callback_started:bool` |
| terminal.json | RETIREMENT_INTENT | `attempts_admitted:int`, `callbacks_started:int`, `attempts_completed:int`, `code:null/closedcode` |

**RETIREMENT_INTENT는 durable completion/stop acknowledgement가 아니다.** intent 뒤에도
file close/fsync, directory fsync/identity, root close, 마지막 overall deadline/stop 검사가
필요하다. 디스크 intent를 성공으로 승격하는 reader/reopen API는 없다. claim은 언제나
재사용을 막는다. end의 RETURNED도 callback 반환만 증명하며 post-write 만료로
runtime EXPIRED가 될 수 있다. 이 경우 attempts_completed를 늘리지 않는다.

## 예산과 동시성

검증된 profile의 max_attempts≤3, retries=0, concurrency=1, min_interval_ms≥1000,
request_timeout_ms≤3000, overall_timeout_ms≤30000을 사용한다. 다음 sample은 실패의
재시도가 아니며 한 번 실패하면 남은 callback은 0이다.

- 실제 직전 callback-entry checkpoint + min_interval 이전에는 RATE_LIMITED다.
  refusal은 파일/attempt를 소비하지 않고 owner가 sleep/wait/retry하지 않는다.
  첫 start I/O가 0→0.9 지연됐으면 다음 reservation은 1.9 이전에 불가하다.
- attempt deadline은 `min(overall_deadline, reservation + request_timeout)`이다.
  start I/O 후에도 재설정하지 않으며 실패한 reservation을 환불하지 않는다.
- active는 reservation/identity admission, start I/O, callback, end I/O, post-check를
  모두 덮는다. coordinator는 짧은 상태 작업만 하며 OS I/O와 callback은 밖에서 실행한다.
- close_pending unwind는 callback 미진입일 때도 active→finalizer를 원자적으로 넘긴다.
  동시 finish/close가 다른 intent나 root close를 시작하지 않는다.
- 성공 attempt의 반환은 그 attempt의 retirement 결정에 고정되어, slot 반환 직후
  시작한 다음 caller의 실패로 앞선 성공을 재분류하지 않는다.

## 오류와 최종 settlement

`SessionError`의 공개 필드는 `code`, `cleanup_uncertain:bool`다. str/repr는 고정 code와
필요한 경우 고정 `cleanup_uncertain` label만 표시하며 원문 cause는 출력하지 않는다.
Closed codes:

```text
INVALID_PROFILE PROFILE_TOO_LARGE SITE_CONFIGURATION_REQUIRED APPROVAL_REQUIRED
STATE_DIRECTORY_INVALID STATE_DIRECTORY_IO_ERROR UNSUPPORTED_PLATFORM
SESSION_ALREADY_USED OWNERSHIP_LOST RECORD_IO_ERROR RETIREMENT_UNCERTAIN
SESSION_BUSY RATE_LIMITED BUDGET_EXHAUSTED SESSION_CLOSED
CANCELLED EXPIRED ACTION_FAILED PERMIT_RETIRED
```

현재 permit이 만든 private control 예외만 CANCELLED/EXPIRED를 유지한다. 임의
SessionError, 다른/오래된 permit 예외, 일반 Exception, non-None 반환은 ACTION_FAILED다.
ordinary failure 뒤 stop/expiry/secondary persistence/close는 primary를 교체하지 않는다.
BaseException은 내부 ACTION_FAILED를 기록하고 permit/active를 정리한 뒤 **원래 객체를
재전파**한다. close_pending과 secondary 실패도 이 원래 예외를 교체하지 않는다.

각 FD 슬롯은 단 한 번의 close 시도 **전에** 비운다. ambiguous close를 재시도하거나
재사용된 FD 번호를 닫지 않는다. 별도 primary 없는 persistence 실패는
RECORD_IO_ERROR/UNCERTAIN, root close만 실패하면 RETIREMENT_UNCERTAIN/UNCERTAIN이다.
`cleanup_uncertain`은 FD disposition뿐 아니라 record durability 불확실성도 포함한다.

FAILED/CANCELLED/EXPIRED/UNCERTAIN과 `retired:false`는 settled가 아니다. finish/close가
남은 retirement를 해야 한다. finalizer가 끝나면 불확실성이 있어도 딱 한 번 settle한다.
이후 finish는 동일 내용의 새 dict, close는 저장된 clean-retired truth, request_stop은
no-op이다. 시간이 지나도 재분류·재기록·재close하지 않는다.

Snapshot/finish의 exact keys:

```text
schema_version:1, profile_sha256:lowercase64hex,
state:READY|RUNNING|STOP_REQUESTED|COMPLETED|INCOMPLETE|FAILED|CANCELLED|EXPIRED|UNCERTAIN,
attempts_admitted:int0..3, callbacks_started:int0..3, attempts_completed:int0..3,
active:bool, stop_requested:bool, retired:bool, cleanup_uncertain:bool,
code:null|closedcode
```

COMPLETED는 configured max_attempts만큼 admitted=started=completed이고 모든 최종 검사가
성공한 **로컬 lifecycle** 결과다. 서비스 PASS는 아니다. `retired:true`는 모든 owner FD의
close 시도를 소비했다는 뜻이며 `cleanup_uncertain:true`와 함께라면 **clean STOPPED가
아니다**. v1에는 STOPPED state가 없다. READY도 마지막 checkpoint 관찰일 뿐 재사용
permit이 아니며 callback이 멈췄는지 snapshot만 보고 추론해서는 안 된다.

## 검증 범위와 후속 gate

`make test-phase3-config`가 기존 lab 시험과 새 `test_session*.py`를 수집한다.
실제 private directory, FD/inode pin, 부분 write와 fsync/close fault, thread event barrier,
두 fresh process claim 경쟁 및 성공/실패 후 reopen을 검사한다. clock/OS fault만
통제된 synthetic seam이며 injection fired를 별도 확인한다. 새 process probe는 제품
import 전에 socket/DNS/connect/child audit veto를 설치하고 positive control을 포함한다.
검증기가 생성한 자식은 PID/start/boot를 기록하고 wait 후 부재를 확인한다.

필수 후보 gate: 전체 lab, evidence, tooling 및 canonical Python Ruff. tooling의
소유 loopback/Vite fixture는 제품 네트워크 기능이나 실제 DUT 증거가 아니다.
통합 검증·commit readback은 `.hermes/artifacts/phase3/session-owner/`에 기록한다.
capture readiness, HTTP(S) adapter,
실제 폐쇄망/센서/장비 수용, 실제 Agent action routing은 후속 미완료 gate로 남긴다.
