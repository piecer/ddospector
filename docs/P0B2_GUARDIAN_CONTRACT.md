# P0-B2 · 독립 로컬 Guardian process 계약

## 범위

P0-B1의 신뢰된 동기 callback admission 다음 안전 tracer bullet이다. 이미 운영자가
소유하고 명시적으로 생성한 **로컬 child process 하나**를 별도 Guardian process가
Linux pidfd와 control pipe로 감시한다. controller pipe EOF, 명시 stop, invalid control,
또는 bounded monotonic deadline이 발생하면 SIGTERM 후 짧은 grace를 거쳐 필요하면
SIGKILL을 보낸다.

이는 process-stop primitive다. Guardian은 target을 spawn하지 않고, callback/명령을
해석하지 않으며, socket·DNS·HTTP·MCP·packet/device adapter를 열지 않는다. 기존
API/CLI의 LIVE 실행 거절과 `baseline_execution_supported:false`는 유지한다.

## 호출 경계

명시적 process entry point는 다음 하나다.

    python -m ddospector.lab.guardian \
      --spec-fd SPEC_FD \
      --target-pidfd TARGET_PIDFD \
      --control-fd CONTROL_READ_FD \
      --release-fd RELEASE_READ_FD \
      --ready-fd READY_WRITE_FD \
      --state-dir-fd PRIVATE_STATE_DIR_FD

모든 FD는 caller가 열고 `pass_fds`로 전달한다. Guardian은 경로를 탐색하거나 target을
자동 발견하지 않는다. caller는 target을 실제 action 이전 barrier에서 정지/대기시킨
상태로 생성해야 한다.

필수 순서는 다음과 같다.

1. P0-B1 `SessionOwner`가 생성한 private root와 `baseline-claim.json`을 보존한다.
2. target child를 실제 action 이전 barrier에서 `SIGSTOP` 상태로 만들고 pidfd를 연다.
3. 서로 다른 anonymous control/read, release/read, ready/write pipe와 read-only spec FD,
   private directory FD를 전달해 Guardian을 별도 process session에서 시작한다. named FIFO,
   잘못된 방향, 같은 pipe 재사용은 거절한다.
4. Guardian의 exact `READY\n`을 받은 뒤에도 target은 stopped 상태다. caller는 release write
   end에 exact `GO\n`을 쓰고 닫는다.
5. Guardian은 deadline/control을 다시 확인한 뒤 pidfd `SIGCONT`를 보내며, 이때부터만
   target action이 실행된다.
6. controller는 정상 소유 기간 동안 control write end 하나만 유지한다. EOF는 controller
   상실로 간주해 fail-closed stop을 수행한다. 다른 reader/writer 복제는 허용하지 않는다.

Guardian이 READY를 보내지 않았거나 Guardian이 `GO\n`을 소비하지 않았으면 target을
release해서는 안 된다. Guardian은 release 직전 stopped identity를 다시 확인하지만, 같은
UID의 다른 주체가 별도 PID/pidfd 권한으로 SIGCONT를 보내는 것까지 커널에서 독점하지는
못한다. P0-B2는 caller가 target을 별도 session에 두고 추가 signal sender/복제 권한을
만들지 않는 trusted local signal-authority 가정을 사용한다. capability FD만으로 action을
해제하는 future adapter가 이 가정을 제거하기 전까지 hostile same-UID 격리는 OPEN이다.

## Closed spec v1

Spec은 owner-only regular file의 strict UTF-8 JSON이며 최대 4096 bytes다. duplicate,
extra key, float, bool-as-int, NaN/Infinity 및 잘못된 encoding을 거절한다.

| 필드 | 계약 |
|---|---|
| `schema_version` | exact int `1` |
| `profile_sha256` | P0-B1 claim과 같은 lowercase64hex |
| `authority_sha256` | P0-B1 claim과 같은 lowercase64hex |
| `state` | exact `st_dev`, `st_ino`; inherited private dirfd의 fstat와 일치 |
| `target` | exact `pid`, `/proc` start ticks, current boot UUID |
| `deadline_monotonic_ns` | arm 시점보다 미래, 최대 300초 이내 |
| `term_grace_ms` | exact int 10–1000ms |

Guardian은 private owner-only directory FD, exact schema-2
`BASELINE_SESSION_CLAIM`, hash binding, P0-B1 budget 범위(max_attempts≤3,
min_interval_ms≥1000, concurrency=1, request_timeout_ms≤3000,
overall_timeout_ms≤30000, retries=0), state dev/inode, pidfd의 Pid, `/proc` stopped
state/start ticks와 boot ID, future deadline, 서로 다른 pipe 방향을 모두 검증한 뒤 READY를
보낸다. 하나라도 다르면 READY·signal·receipt 없이 exit 78로 거절한다.

이 claim/hash 검증은 같은 trusted local caller가 전달한 문서 사이의 **일관성 검사**다.
서명·remote issuer authentication 또는 독립적인 P0-B1 admission 증명은 아니며, Guardian
receipt도 실행 권한의 암호학적 증거로 해석하지 않는다.

## 감시와 중단

pidfd, control read FD, release read FD를 nonblocking poll한다. release 전에는 exact
`GO\n` 뒤 EOF만 허용하며, deadline/control을 마지막으로 다시 확인한 뒤 Guardian이
pidfd SIGCONT를 보낸다. release 뒤에는 pidfd와 control을 감시한다. 같은 poll cycle에서
우선순위는 target exit, deadline, control 순서다.

- pidfd readable: `TARGET_EXITED`; signal 없음.
- release EOF 전 exact `GO\n`: release 후보. 추가 byte/partial EOF는 `RELEASE_INVALID` 또는
  `RELEASE_LOST`이며 paused target을 fail closed로 중단한다.
- control EOF/read error: `CONTROL_LOST`.
- 첫 bounded frame exact `STOP\n`: `STOP_REQUESTED`.
- 그 외/초과 control frame: `CONTROL_INVALID`; fail closed.
- monotonic deadline: `DEADLINE`; 동시에 도착한 stop보다 deadline을 우선 기록한다.

stop trigger는 pidfd로 SIGTERM을 보내고 `term_grace_ms` 동안 기다린다. 계속 살아 있으면
SIGKILL을 보내고 bounded 1초 동안 pidfd stop을 확인한다. PID 번호로 `kill()`하지 않으며
pidfd/start/boot identity가 일치하지 않으면 signal을 보내지 않는다.

## Receipt와 오류

fixed leaf `guardian-receipt.json`을 owner-only O_EXCL/O_NOFOLLOW로 쓰고 file과 directory를
fsync한다. receipt는 schema/kind, 두 hash, state identity, target identity, trigger,
signal 목록, `released`, `stopped`, `cleanup_uncertain`만 포함한다.

- 자연 종료: `GUARDIAN_EXIT_RECEIPT`.
- Guardian 중단: `GUARDIAN_STOP_RECEIPT`.
- 정상 관측/중단과 durable receipt: exit 0.
- 입력/FD/binding/READY 거절: exit 78.
- stop 확인 또는 receipt durability 불확실: exit 75.

Receipt 충돌은 기존 파일을 읽거나 덮지 않는다. stop이 필요한 경우 stop을 먼저 수행하고
`RECEIPT_IO_ERROR`로 불확실 종료한다.

## 아직 열린 안전 gate

- Guardian process 자체의 crash/restart 및 별도 service-manager 감시.
- SessionOwner/실제 adapter가 paused target을 생성하고 READY 뒤 release하는 통합.
- hostile same-UID signal sender를 제거하는 target-side capability barrier/격리.
- process 종료 이후 packet/device 실제 중단 readback과 물리적 차단 수단.
- 여러 승인과 DUT 전체에 걸친 PPS/BPS/packet-byte/connection 누적 예산.
- passive sensor 준비, baseline/test-load 분리, 실제 격리망·장비·MCP 수용.
- remote issuer/RBAC 및 full S02/W2.

따라서 P0-B2는 독립 process-stop primitive 구현이지 LIVE 실행 권한이나 S07 완료가 아니다.
