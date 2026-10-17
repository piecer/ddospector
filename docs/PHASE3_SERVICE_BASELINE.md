# Phase 3 · P3-00 배포 설정과 무통신 preflight

**상태: `P3-00 INDEPENDENTLY_ACCEPTED`.** 배포 설정·template·무통신 preflight 범위다.

P3-00은 배포 시 채울 profile, 엄격한 로컬 검증기와 공개 CLI를 제공한다.
정상 서비스 baseline 실행기·capture·실제 DUT 수용은 **미구현/미수용**이다.
현재 호스트의 주소·인터페이스·라우팅을 조사하거나 환경변수로 대상 값을 채우지 않는다.
사용자가 실제 시험을 다른 폐쇄망에서 수행하므로 현장 값은 배포 시 입력한다.
현장 수용 연기는 로컬 구현의 연기가 아니다.

## 공개 명령

프로젝트의 Python 환경에서 실행한다.

```sh
.venv/bin/python -m ddospector.lab template
.venv/bin/python -m ddospector.lab preflight --config /absolute/profile.json
make test-phase3-config
```

`template`은 목적지 예제 없이 모든 현장 필드를 null로 둔 JSON을 stdout에 내고
exit 0으로 종료한다. 파일 저장이 필요하면 운영자가 별도 경로를 선택해 stdout을
저장한다. CLI는 파일을 생성하거나 기존 파일을 덮어쓰지 않는다. Python import
cache와 호출자 stdout 리다이렉션은 제품 소유 파일 생성과 구분한다.

`preflight`는 요청한 설정 파일만 읽는다. DNS·socket·HTTP·추가 자식 프로세스·
인터페이스 조회·CA 파일 접근을 하지 않는다. `execute`, `--execute` 또는 HTTP
실행 route는 없다. 미지정/알 수 없는 명령과 인자는 argparse usage error/exit 2이며
아래 profile 결과 envelope와 구분한다. 축약 인자는 받지 않는다.

## Closed profile v1

UTF-8 JSON 최대 **16384 bytes**. 아래 key는 전부 필수이며 객체별 추가 key도
거절한다. duplicate key, NaN/Infinity, float, 숫자 대신 bool/string, 잘못된 UTF-8,
lone surrogate, 과도한 중첩 decoder 오류는 `INVALID_PROFILE`이다.
JSON 정수는 값 의미를 사용하므로 `retries:-0`는 0과 같다.

| 객체 | 정확한 key와 제약 |
| --- | --- |
| root | `schema_version`: 정수 1; `kind`: `NORMAL_SERVICE_BASELINE`; `target`, `source`, `budget`, `expected` |
| target | `connect_ipv4`, `port`, `scheme`, `http_host`, `path`, `ca_file` |
| source | `bind_ipv4`, `interface` |
| budget | `max_attempts`, `min_interval_ms`, `concurrency`, `request_timeout_ms`, `overall_timeout_ms`, `retries` |
| expected | `http_status`, `body_sha256` |

- `connect_ipv4`와 `bind_ipv4`: canonical dotted IPv4 문자열. unspecified,
  multicast, `255.255.255.255` 금지. loopback은 구성 가능하지만 현장 수용이 아니다.
  사설 주소 구성은 임의 사설망 접속 허가나 전역 SSRF 예외가 아니다.
- `port`: 정확한 정수 1..65535. `scheme`: 정확히 `http` 또는 `https`.
- `http_host`: ASCII DNS 이름 또는 canonical IPv4 literal, 1..253자.
  DNS label은 1..63자, 영숫자로 시작/끝, 내부 영숫자/hyphen만 허용한다.
  공백·제어문자·port·userinfo·후행 점은 거절한다. 대소문자를 유지하며 DNS 조회는 없다.
- `path`: ASCII origin-form, 1..1024자, `/`로 시작하되 `//` 금지.
  공백·제어문자·fragment·raw backslash 금지. percent escape는 완전한 `%HH`만
  허용하고 decoding하지 않는다. query와 escape 대소문자도 그대로 보존한다.
- `ca_file`: null 또는 절대 POSIX 경로, UTF-8 1..4096 bytes, NUL/제어문자 금지.
  HTTP에서는 null만 허용한다. 문법만 검사하고 stat/access/resolve/read하지 않는다.
  없는 CA 경로도 HTTPS 설정 문법상 유효하다. 인증서·신뢰 체인·TLS 준비 완료가 아니다.
  후속 HTTPS 실행기는 검증을 필수로 하며 insecure fallback을 제공하지 않아야 한다.
- `interface`: ASCII 1..64자, 영숫자와 `_ . : -`만 허용하며 원문 유지.
  현장 존재나 해당 주소 할당은 검사하지 않는다.
- `http_status`: 정확한 정수 200..299. redirect를 성공 기준으로 구성할 수 없다.
- `body_sha256`: null 또는 lowercase hex 64자. null은 후속 실행 시 status만
  검사한다는 뜻이며 서비스 전체 가용성 보장이 아니다. 별도 secret/header 필드는 없다.

### 승인된 baseline 예산

| key | 허용값 | template |
| --- | --- | --- |
| max_attempts | 정수 1..3 | 3 |
| min_interval_ms | 정수 1000..30000 | 1000 |
| concurrency | 정확히 정수 1 | 1 |
| request_timeout_ms | 정수 1..3000 | 3000 |
| overall_timeout_ms | 정수 1..30000 | 30000 |
| retries | 정확히 정수 0 | 0 |

`request_timeout_ms <= overall_timeout_ms`도 필수다. 작은 전체 deadline 때문에
모든 시도를 시작할 수 없는 구성도 유효하며 후속 실행기는 deadline을 우선해야 한다.
이 수치 검증은 요청 실행·요청률·PPS/BPS 집행 증거가 아니다.

### 현장 미기입과 오류 우선순위

Template의 target `connect_ipv4/port/scheme/http_host/path`, source
`bind_ipv4/interface`, expected `http_status`는 null이다. 이 현장 leaf가 null이면,
**다른 모든 제공 값이 유효한 경우에만** `SITE_CONFIGURATION_REQUIRED`다.
누락 key나 다른 오류는 먼저 `INVALID_PROFILE`로 거절한다.
`ca_file` 및 `body_sha256`의 null은 정상 선택이며 현장 미기입이 아니다.
`scheme:null`과 문법상 유효한 CA 경로는 scheme을 추정하지 않고 미기입으로 남긴다.

## 파일 경계와 FD 종료

`--config`는 절대 경로여야 한다. read-only·nonblocking·final-component
no-follow로 열고 실제 FD의 fstat에서 regular file인 경우에만 읽는다.
FIFO/device/directory는 읽기 전에 거절한다. partial read에도 누적 **cap+1 bytes**를
초과하여 읽지 않으며 초과를 조용히 잘라 성공 처리하지 않는다.
caller 파일은 수정/삭제하지 않는다.

상위 디렉터리는 운영자 소유의 **신뢰 namespace**라는 전제다. 악의적인 상위
경로 교체에 대한 filesystem sandbox나 임의 filesystem latency 상한을 주장하지 않는다.

취득 FD는 모든 종료 경로에서 한 번만 close를 시도하며 호출 전에 소유 슬롯을
비운다. ambiguous close를 재시도하지 않는다. FD 미취득이면 close 0회다.
stdout 게시는 반드시 close 시도 후다.

| close 전 결과 | close 성공 | close 실패 |
| --- | --- | --- |
| 유효 profile | CONFIG_VALID_NO_NETWORK / 0 | PROFILE_IO_ERROR / 2 |
| PROFILE_TOO_LARGE | 동일 거절 / 2 | 동일 거절 / 2 |
| INVALID_PROFILE | 동일 거절 / 2 | 동일 거절 / 2 |
| SITE_CONFIGURATION_REQUIRED | 동일 거절 / 2 | 동일 거절 / 2 |
| open 이후 fstat/read 실패 | PROFILE_IO_ERROR / 2 | PROFILE_IO_ERROR / 2 |

원문 exception·notes·traceback·입력 주소·query·경로는 profile 결과의 stdout/stderr에
출력하지 않는다. 상대 경로, open/fstat/read 실패도 고정 `PROFILE_IO_ERROR`다.

## 출력과 digest

Template와 모든 profile 결과는 다음 canonical JSON 뒤 LF 하나다.

`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`의 UTF-8 bytes.

성공 exit 0의 exact keys:

```json
{"baseline_execution_supported":false,"network_io_performed":false,"profile_sha256":"<64 lowercase hex>","schema_version":1,"site_verified":false,"status":"CONFIG_VALID_NO_NETWORK"}
```

`profile_sha256`은 검증한 입력 객체의 canonical bytes에 대한 SHA256이며 LF는
제외한다. JSON key 순서/whitespace는 digest에 영향을 주지 않지만 실제 문자열은
normalize/trim하지 않는다. 이 hash나 유효 판정은 실행 권한·격리망 증명이 아니다.

거절 exit 2의 exact keys:

```json
{"code":"INVALID_PROFILE","schema_version":1,"status":"REFUSED"}
```

code는 `PROFILE_IO_ERROR`, `PROFILE_TOO_LARGE`, `INVALID_PROFILE`,
`SITE_CONFIGURATION_REQUIRED` 중 하나다. 성공과 거절을 함께 선출력하지 않는다.

미기입 template의 canonical bytes는 LF 제외 382 bytes,
SHA256 `7c3c1e45082eb3870ccda5bb10566645da712a2fae31f6985202b3d7bd776b57`다.
이는 직렬화 oracle이지 유효 profile 판정이 아니다.

## 검증과 다음 단계

`make test-phase3-config`는 `tests/lab`를 명시 수집하고 기본 `make test` 집계와
Python Ruff에도 연결된다. CLI subprocess의 제품 import 전 audit 관찰기로
socket 생성·resolver·connect·추가 child launch 0을 확인하며 positive control은
실제 효과 전에 차단한다. connect positive control은 socket을 만들지 않는 audit
이벤트 대조다. FD fault는 실제 로컬 FD와 좁은 syscall adapter를 사용한다.
device mode 거절은 실제 장비를 열지 않고 regular FD의 fstat mode만 주입해 검사한다.

P3-00 검증 범위는 profile/로컬 파일/무통신 CLI다. 기존 runs/evidence/API/UI,
의존성, DB schema와 과거 Phase 1/2 산출물은 변경하지 않는다.
독립 리뷰에서 신규 289개 시험과 Python Ruff를 통과했으며, 기존 evidence 238개와
전체 tooling 67개도 source/hash/JUnit으로 확인했다. tooling의 소유 loopback
HTTP/Vite fixture는 제품 CLI의 무통신 계약과 구분한다. 통합 후에는 동일 scoped
gate를 다시 실행하며 실제 결과와 commit readback은 `.hermes/artifacts/phase3/`에
기록한다. full W2, Docker/PG/제품 앱 서버/브라우저, 실제 DUT 접속·송신·캡처는
이 단계의 검증으로 재개하지 않는다.

후속 단계는 별도 실행 admission, 소유권·capture readiness·중지 확인과 실제
HTTP(S) GET baseline이다. 범위는 BASELINE_ONLY이며 baseline 성공만으로 별도
예산 없는 후속 통신을 자동 시작하지 않는다. 후속 실행기의 설계 상한인 header
16384 bytes, body 32768 bytes, diagnostic 4096 bytes는 **현재 집행되지 않는다**.
현장 topology·권한·인증서·센서·패킷/바이트 한도와 실제 DUT 수용은 배포 시 결합한다.
