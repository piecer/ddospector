# Scenario storage: bounded retention and offline recovery

This guide describes the implemented S01 storage and recovery workflow. Verification scope is documented in `SCENARIOS_VERIFICATION.md`, with release gates tracked in `IMPLEMENTATION_CAMPAIGN.md`; neither document claims power-loss durability. The normative contract is `stages/S01_RETENTION_RECOVERY.md`.

## What is retained

For an effective draft path `/absolute/private/drafts.json`, the separate scenario registry is `drafts.json.scenarios.json`. Alongside it are:

- `drafts.json.scenarios.json.s01-recovery`: a fixed 4,096-byte control receipt (0600).
- `drafts.json.scenarios.json.s01-pending/`: a private holding directory (0700).
- `candidate` and `publish` inside that directory: normally two hard links to one candidate inode, at most 16 MiB. An observable caller replacement is preserved rather than deleted.

A failed save does not delete, truncate or replay these payloads. Further scenario saves are denied; valid committed history remains readable. A pre-publication failure returns `SCENARIO_STATE_UNAVAILABLE`; a failure after replacement returns `SCENARIO_COMMIT_UNCERTAIN`. The latter may already be present in history: never automatically submit the request again. Drafts, targets and AI settings have their separate existing storage contract.

The errored running owner remains write-blocked. A fresh process may save without recovery only when the CLEAN receipt, exact valid registry bytes/size and empty real holding directory all agree. This includes an error after a complete CLEAN record was written. Restart is not a general repair: incomplete/missing metadata, pending files or a mismatching registry still deny writes. Health reports process liveness, not writable storage.

The browser additionally blocks scenario create/edit/save after either storage mutation error. GET-only acknowledgement retry, draft review/copy, closing and history navigation remain available. Closing/discarding the editor or retrying a read does not unlock writes. A full page reload resets only that browser's observation; the API still enforces storage admission. A conflict or lost acknowledgement without a storage error has its separate readback workflow.

## Preconditions

- Use the same checkout/environment and exact effective draft path as the stopped API. Run from the repository root with its installed `.venv`.
- Stop all cooperating API writers using their normal, owner-verified shutdown procedure. Do not recover while an API process is running. There is no cross-process recovery lock or multiwriter transaction guarantee.
- Keep the containing directory trusted/private. Do not move or edit pending files, clear the receipt, restore an old registry over a newer one, or infer cleanup authority from a filename/hash.
- Choose an existing private archive parent on the same local filesystem. Each archive destination must be a new absolute path, not a managed file/directory or a child of the pending directory. Symlink parent traversal, cross-filesystem moves and existing archive destinations are refused.
- Only valid current registries are recoverable. A corrupt, oversized or nonregular registry must be preserved for separate operator diagnosis; `--accept-current` does not bypass that check.

Examples below use Bash placeholders. Replace them with the reviewed local paths; they are not defaults. No command contacts a DUT, model or MCP service.

## Inspect before deciding

```sh
DRAFT_PATH=/absolute/private/drafts.json
.venv/bin/python -m ddospector.api.scenario_recovery inspect --draft-path "$DRAFT_PATH"
```

Inspection is read-only. Its bounded JSON includes receipt phase/presence, current registry hash/revision/size, pending-file hashes/sizes, and `review`. It does not print scenario bodies or a ticket. `ABSENT` is not the same as a validated nonempty history. Missing and malformed receipts are distinguished.

Review the observation and compare current history with the attempted save. Copy that exact `review` hash into the recovery invocation; any changed observation is refused without silently accepting a new review. Exit 0 means inspection completed, not that saves are enabled. Exit 2 is refusal or an I/O/close error; do not treat a partial output as success.

## Reconcile retained material

For valid prior metadata and complete preservation witnesses:

```sh
.venv/bin/python -m ddospector.api.scenario_recovery recover \
  --draft-path "$DRAFT_PATH" \
  --review REVIEW_HASH_FROM_INSPECTION \
  --archive /absolute/private/new-recovery-archive
```

For missing/damaged control material or an incomplete attempt whose missing candidate cannot be reconstructed, explicitly choose the currently validated committed registry instead:

```sh
.venv/bin/python -m ddospector.api.scenario_recovery recover \
  --draft-path "$DRAFT_PATH" \
  --review REVIEW_HASH_FROM_INSPECTION \
  --archive /absolute/private/new-recovery-archive \
  --accept-current
```

If that inspection says the current registry is `ABSENT`, this acceptance also requires `--confirm-empty-registry`. Do not add it without reviewing the loss/absence of current history. It explicitly records acceptance of an empty registry; it does not recover lost versions.

`--accept-current` preserves the valid current registry and observable remnants. It records abandonment of an unacknowledged attempt, never replay, rollback, candidate promotion or restoration of missing data. Unknown pending names, nonregular entries, oversized material and unsupported filesystem primitives are still refused.

Successful recovery preserves the observed raw receipt in `receipt.bin`, an immutable decision in `decision.json`, and the reviewed holding directory in `pending/` under the archive. It returns READY with one startup ticket only after required operations complete. The exact-byte/count bound per invocation is 33,562,624 bytes: at most two 16 MiB payloads plus two files of at most 4,096 bytes. Hard links can share physical storage. Operator-created archives accumulate across explicit invocations; the product never automatically prunes them.

## Start once with the handoff

The legacy `aiddos` commands and `AIDDOS_*` settings remain supported. A present
`DDOSPECTOR_*` setting takes precedence even when empty; remove conflicting newer
settings before intentionally using a legacy setting. The one-use ticket and
retained-data rules below are unchanged by the rename.

Do not save tickets in `.env`, scripts, shell history, logs, persistent service configuration or HTTP requests. A ticket is a short-lived local recovery capability, not a model/API credential. Use only a complete recovery result with exit 0. Enter the returned ticket into a private shell without echo:

```sh
IFS= read -r -s -p 'Recovery ticket: ' recovery_ticket
printf '\n'
DDOSPECTOR_UI_STATE_PATH="$DRAFT_PATH" \
DDOSPECTOR_SCENARIO_RECOVERY_TICKET="$recovery_ticket" \
  .venv/bin/python -m uvicorn ddospector.api.app:app \
  --host 127.0.0.1 --port 5180 --workers 1 --no-proxy-headers
unset recovery_ticket
```

Construction and GET do not consume the ticket. The first fully validated scenario save verifies the current registry, empty slot and archived decision/material, then consumes the handoff before candidate acquisition. Invalid requests do not consume it. A failed consume remains blocked; the old ticket cannot be reused after the durable ACTIVE transition. A later normal CLEAN restart needs no ticket. Never preserve the ticket in an automatic restart environment.

After restarting the API, reload the browser to clear its local block, inspect immutable history, and deliberately author any next version against the latest revision. Do not replay the failed request automatically or assume a 503 meant nothing was saved.

## Interrupted or refused recovery

Do not delete partial archives to retry. Reinspect. A valid RECOVERING/READY plan with intact material resumes only the same archive and action; use its current `review` and the same flags, including empty-registry confirmation when applicable. A reviewed holding directory still present before the move is an intact preservation witness, not permission to create another archive.

If material in a recorded archive is lost/invalid, ordinary resume is denied. A separately reviewed `--accept-current` operation may abandon that plan using a fresh archive, preserving whatever is currently observable and leaving all earlier archives untouched. A failure before a valid plan exists may likewise require a fresh archive. Permission/device I/O failures do not establish that material is lost. Persistent storage errors can prevent all recovery; there is no force-delete or general repair option.

Same-host subprocess restart tests establish visibility and admission behavior. They are not a promise of power-loss recovery, network-filesystem support, authenticated receipts or safe concurrent writers.

## 한국어 운영 요약

1. 저장 오류가 발생하면 실패 요청을 다시 보내지 말고 현재 이력을 확인합니다. `SCENARIO_COMMIT_UNCERTAIN`은 이미 저장됐을 수 있다는 뜻입니다. GET 재시도는 저장소 복구가 아닙니다.
2. 실행 중 오류를 경험한 API는 계속 쓰기를 차단합니다. 새 프로세스는 유효한 CLEAN 기록·정확한 저장본·빈 대기 영역이 모두 일치할 때만 수동 복구 없이 재개합니다. 단순 재시작이 손상 자료를 자동 초기화하지 않습니다.
3. 모든 관련 API 쓰기 프로세스를 소유권 확인 후 정상 종료합니다. 같은 환경에서 실제 초안 파일의 절대 경로를 지정하여 위 `inspect` 명령을 실행합니다. 출력의 phase, registry hash/revision, pending 파일과 `review`를 검토합니다.
4. 완전한 자료는 일반 `recover`로 보관·조정합니다. 자료가 없거나 손상되어 현재의 유효한 저장본을 유지하기로 명시적으로 결정했다면 `--accept-current`를 사용합니다. 저장본이 ABSENT라면 빈 상태 수용을 확인한 뒤에만 `--confirm-empty-registry`를 추가합니다.
5. archive는 같은 파일시스템의 새 절대 경로여야 합니다. 최대 두 개의 16 MiB payload와 각각 최대 4 KiB인 원본 receipt/decision을 보관합니다. 기존 파일을 덮어쓰거나 자동 삭제하지 않습니다. 여러 차례의 운영자 보관본 누적은 이 1회 한도와 별개입니다.
6. 종료 코드 0의 완전한 READY 결과에서 받은 ticket을 위 무표시 입력으로 한 번의 API 시작에만 전달합니다. 환경 파일·서비스 자동 재시작 설정·로그에 저장하지 않습니다. 첫 유효 저장 요청이 handoff를 소비하며, GET이나 잘못된 입력은 소비하지 않습니다.
7. 브라우저를 새로고침하고 이력을 확인합니다. UI의 로컬 차단이 사라져도 API 차단을 우회할 수 없습니다. 새 저장이 필요하다면 최신 revision을 기준으로 의도적으로 작성합니다.
8. 복구가 중단되면 원본과 보관본을 그대로 두고 다시 inspect합니다. 유효한 복구 계획은 동일 archive/동일 동작으로만 재개합니다. 남은 자료를 삭제해 우회하지 마세요. 손상된 현재 레지스트리, 지원하지 않는 파일 종류/개수/크기, 계속되는 I/O 오류에는 이 명령으로 복구할 수 없습니다.
