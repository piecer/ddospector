# S01 — bounded failed-save retention and explicit recovery

Current status: IMPLEMENTED_REVIEW_ACCEPTED. The actual store, offline recovery CLI and browser quarantine implement this contract. Independent correction-3 review `deleg_f50e0d17` accepts all six peer-fence rows and all 22 backend rows; S01-B01/B02 and S01-RET-REVIEW-01 are closed on the reviewed candidate without deleting predecessor REDs. Parent API/UI/Chromium and real browser→HTTP→CLI recovery gates pass on that source. `../SCENARIOS_VERIFICATION.md` separates these results from final-document, active-service and exact-commit release gates. Cumulative correction allowance is 3/3 consumed, never reset.

## Historical correction records

The authorization and blocked-candidate paragraphs below preserve prior decisions and evidence. They do not reopen approval or override the current accepted implementation status; all normative recovery clauses remain in force.

Current authority: CORRECTION_03_AUTHORIZED for S01-RET-REVIEW-01 only, under the user's explicit `이 결함에 한해 보정 1회 추가 허용` decision. Cumulative limit 3, prior cycles consumed 2, allowance not reset. This supersedes only the waiting-for-authorization status below; the failed candidate remains BLOCKED and all clauses remain unchanged. The approval receipt and shared regression matrix are `.hermes/artifacts/campaign-01/S01/peer-fence-correction-approval.json`. Require constructor/save admission serialization under the existing path coordinator lock, unchanged consumed-ticket and invalid-ticket sequential/overlap probes, canonical regression coverage, valid-peer/unrelated-path progress, retained live-error fencing, and fresh independent review. Do not hold the global registry guard while waiting for the path lock. No fourth automatic correction, policy expansion, active-data operation, or S02 admission is authorized.

Status: BLOCKED_CORRECTION_LIMIT; contract unchanged, product acceptance refused after correction 2 independent review. S01-RET-REVIEW-01 violates the existing coordinator-lock and invalid/consumed-ticket refusal clauses below; parent unchanged-probe reproduction confirms it. The two-cycle allowance is consumed, not reset. See `docs/IMPLEMENTATION_CAMPAIGN.md` and `.hermes/artifacts/campaign-01/S01/retention-review-result.json`. The frozen reviewed copy remains preserved. This addendum supersedes the S01 zero-failure-residue rule and the unaccepted disposable design's all-restarts/manual-recovery and unrecoverable-missing-candidate rules. It does not supersede immutable history, source snapshot/CAS rules, fixed envelopes, caller preservation or resource limits. The user approved retention → write quarantine → explicit recovery, then selected both normal verified restart and explicit acceptance of current valid state after preserving incomplete material. Approval receipts are `retention-policy-approval.json` and `retention-availability-approval.json` under `.hermes/artifacts/campaign-01/S01/`.

The predecessor filesystem model's 82 cases and CLI roundtrip were independently reproduced by the parent. They are primitive feasibility evidence, not actual ScenarioStore/API acceptance and not tests of the new restart/accept-current rules below. Preserve that original draft/model and all B01/B02 REDs. This contract governed product correction cycle 2 of 2; its contract check and full independent review have now completed. Passing bounded-retention, recovery and composed UI cases do not override the reproduced same-process peer blocker. No further correction is authorized by this status update.

## 1. Scope and ownership

- Local Linux, one cooperating API process, existing effective DraftStore path and scenario→draft lock order. No multiprocess transaction, network filesystem, authenticated filesystem provenance or power-loss availability claim.
- Supported interference includes real unlink/recreate of the exposed publication source and its replacement after the last observation on a failed publication. It does not include arbitrary hostile mutation of hidden private anchors/control objects. Never dismiss the supported source schedule merely because its directory is private.
- Backend owns `scenario_store.py`, new `scenario_recovery.py`, optional narrow new `scenario_persistence.py`, fixed text in `errors.py`, and minimal `app.py`/`scenarios.py` ticket wiring. Tests: existing S01 storage/ownership/scenario tests, plus new `test_scenario_retention.py` and `test_scenario_recovery.py` as needed. Do not modify legacy DraftStore, dependencies or unrelated tests.
- Frontend is a separate owner of `ScenarioLibrary.tsx` and its tests only. Parent owns documentation, integration, E2E, promotion and commits.
- No active `.local` data or credentials are read or recovered by this implementation campaign. Recovery acceptance runs only against owned isolated test state. No packet, device, model, MCP, browser/listener activity in the backend implementation slice.

## 2. Fixed namespace and budgets

Let R be the unchanged scenario registry path derived from the effective draft path. Its serialized ScenarioState remains unchanged and at most 16,777,216 bytes.

- Receipt: `R.with_name(R.name + '.s01-recovery')`, regular mode0600, exactly 4,096 bytes when valid; fixed-size in-place writes, never append.
- Holding directory: `R.with_name(R.name + '.s01-pending')`, mode0700, same filesystem as R.
- Private anchor: holding directory / `candidate`, exclusively created for one candidate inode of at most 16,777,216 bytes.
- Publication source: holding directory / `publish`, no-overwrite hard link to candidate; initially the same payload, not another copy. Only this name is supplied to registry replace.
- No next candidate while unresolved or either slot name exists. Repeated errors/reopens cannot grow product-managed pending data or allocate random new staging names. Caller-created/moved/substituted material remains caller-owned; do not delete it to satisfy a quota.
- A recovery invocation creates at most one explicit fresh no-overwrite archive root with `receipt.bin` (0..4,096 bytes of observed original metadata), `decision.json` (at most4,096 bytes), and `pending/` containing at most two regular entries, each at most16MiB. Logical archive cap is 33,562,624 bytes, at most two directories and four files; hard-link sharing may reduce actual data allocation. Operator archives are outside the managed pending budget and never automatically pruned. Bound each invocation and disclose lifetime operator accumulation.
- Enumerate only the two allowed pending names: bounded iterator, reject the third/unknown entry. Do not materialize an unbounded directory listing before rejecting. All reads are NOFOLLOW/NONBLOCK regular-file reads with cap+1 detection. No symlink/FIFO/device/directory payload adoption.
- Archive parent must already exist on the same filesystem. Reject archive paths equal to or nested under the holding directory, the registry/control paths, and any existing destination. Reject unsupported hard links, directory fsync or atomic no-replace directory rename; no copy/overwrite fallback.

## 3. Closed fixed receipt

Framing: bytes0..7 ASCII `S01RR001`; bytes8..11 big-endian unsigned JSON length L≤4052; bytes12.. contain canonical ASCII JSON of length L; zero padding through byte4063; bytes4064..4095 contain raw SHA256 of the preceding4064 bytes. Require exact4096 bytes, checksum, magic, zero padding, canonical re-encoding, depth≤8, exact keys, strict integers and no duplicate keys. Read at most4097 bytes. The checksum is integrity, not authentication.

Top-level exactly `{version,phase,generation,pre,post,size,recovery,token_hash}`:

- version: strict integer1.
- phase: ACTIVE/PREPARED/PUBLISHED/CLEAN/RECOVERING/READY.
- generation:32 lowercase hex; new per candidate, preserved during ordinary recovery; new on accept-current when prior receipt is malformed/missing.
- pre:64lowercase SHA256 of raw registry bytes or `ABSENT`.
- post:64lowercase SHA256 or null; non-null for PREPARED/PUBLISHED/CLEAN.
- size:strict integer0..16777216; expected candidate size. ACTIVE requires0 and post=null.
- recovery:null outside RECOVERING/READY; otherwise exactly `{archive,record_hash,decision_hash,registry_hash,entries}`. This five-field shape deliberately extends the four-field disposable model.
- archive:absolute local path, no NUL, at most1024 UTF-8 bytes, full frame must fit4052 JSON bytes. record_hash and decision_hash are64lowercase SHA256 of the archived exact files. registry_hash is64lowercase SHA256 or ABSENT. entries is a closed object with only optional candidate/publish keys, each exactly `{bytes,sha256}` with integer0..16777216 and64lowerhex.
- token_hash:64lowerhex only in READY; null otherwise. Ticket is64lowerhex generated from32 random bytes, not reflected in HTTP and not a web credential.

Use explicit validation exceptions, never assertions as production admission. Pre-encode every future frame and bounded CLI output before creating an archive. Torn/malformed/missing control data never defaults to CLEAN.

## 4. Coordinator, initialization and verified restart

Share a live coordinator with the existing path-keyed same-process lock across ScenarioStore peers. All admission and state transitions occur under that lock; preserve scenario→draft ordering. Construction and GET remain effect-free. An already errored live coordinator stays blocked even if a later GET sees a valid CLEAN frame. Losing a coordinator/new process is a reopen requiring the validation below, not automatic initialization.

First fully validated save may initialize only when both receipt and holding namespace are absent. Existing valid legacy R remains unchanged until the actual candidate commit. Exclusively create the holding directory and receipt; write/fsync/single-close ACTIVE, synchronize directory creation and its parent before enabling. A partial initialization or collision is retained, never cleaned up on error. For newly created ancestor directories, synchronize created entries up to the preexisting ancestor before admitting a candidate.

A fresh coordinator may resume WITHOUT operator recovery only if ALL are true:

1. Receipt is a valid CLEAN frame with recovery=null and token_hash=null.
2. R is present, bounded, validates fully as ScenarioState, and its exact raw SHA256 and byte length equal receipt.post and receipt.size.
3. Holding directory is the expected real nofollow directory and contains no entries.
4. Every required inspection and close succeeds; no explicit invalid or mismatching startup ticket was supplied.

This is the user's approved exception: a predecessor may have reported an error after writing the complete CLEAN marker; a fresh verified reopen can still resume. Do not claim permanent quarantine of that historical tail error. The errored predecessor coordinator itself does not auto-unlock. PREPARED, PUBLISHED, ACTIVE, RECOVERING, READY without a valid one-use ticket, malformed metadata, missing slot, mismatched R or remaining entries cannot use this restart path.

Read-only quarantine admission check is inserted after registry and locked draft-source reads but before CAS, returning SCENARIO_STATE_UNAVAILABLE for a quarantined otherwise-valid request. Registry corruption and source-specific STATE_* precedence remain unchanged. Resolve references, CAS, quotas and complete serialized candidate/response validation before initializing, consuming a ticket or allocating a candidate. `_write` independently enforces valid bounded candidate and admission; no internal bypass.

## 5. Save ordering and failure semantics

1. Validate complete candidate and response; prebuild fixed frames. Require live admission and empty slot. Mark the live coordinator blocked before persistence.
2. Write/fsync/single-close PREPARED before candidate creation. Use exact-offset writes, handle short writes, never O_TRUNC/append or exceed4096 bytes.
3. Exclusively create candidate; establish descriptor cleanup immediately. fstat, fdopen(closefd=False), bounded write, flush, file fsync, stream close, one raw close. Retain the named file on every error, including first fstat/fdopen. Close the descriptor, not the pathname.
4. Create publish as no-overwrite hard link. Synchronize holding directory. Observe publish regular-file identity against the private owned anchor. This observation is NOT conditional unlink authority.
5. Replace publish→R; record successful publication immediately after syscall return. Synchronize both changed source and destination directories.
6. Write/fsync/single-close PUBLISHED. Only then retire the private candidate hard link on the normal success path; bytes remain in committed R. This narrow authority derives from live creation custody and the excluded hidden-private-mutation scope, never from an exposed-source observation. Failure handlers do not retire either name.
7. Synchronize the holding directory; write/fsync/single-close CLEAN. Re-enable the live coordinator only after all mandatory work succeeds. No further required I/O after enabling. A caller-created/reappearing publish entry stays untouched and causes the next admission to fail.

Before successful replace: fixed SCENARIO_STATE_UNAVAILABLE503 and original R/draft preimages. After replace: SCENARIO_COMMIT_UNCERTAIN503, no rollback or replay; committed R remains history authority. Classify by publication, not marker bytes. A local syscall that raises before successful return uses the existing effect-free local failure contract; test post-return faults after recorded publication, not a wrapper that secretly commits then reports an effect-free failure.

Preserve the original internal exception object/type/message if cleanup also fails; do not expose it publicly. A close-only failure must not become success. Retire handles before one close attempt, never retry a possibly reused numeric FD. Fault tests include real-close-then-EIO. Use this discipline for scenario read/receipt/archive helpers as well, without changing unrelated legacy stores.

No failure handler deletes, truncates, overwrites, renames or replays pending payloads. No failure-marker write is required for safety: durable PREPARED and default blocked reopen supply the boundary, except for the explicitly approved validated CLEAN restart rule. Continued storage failure can prevent recovery; failed fsync bytes being readable does not prove durability.

## 6. Explicit offline inspection and recovery

Proposed executable module is `python -m aiddos.api.scenario_recovery`. It must not import the global app or start a server. API/cooperating writers must be stopped by the operator; this is an explicit offline precondition, not a new cross-process transaction guarantee.

Commands:

- `inspect --draft-path /ABS/drafts.json`
- `recover --draft-path /ABS/drafts.json --review HASH --archive /ABS/fresh-archive`
- `recover --draft-path /ABS/drafts.json --review HASH --archive /ABS/fresh-archive --accept-current`
- Add `--confirm-empty-registry` to accept-current if R is absent; absence must be shown explicitly in inspect, never silently treated as a known preserved nonempty history.

`inspect` does not modify anything. It validates R using actual ScenarioState; missing R is reported as ABSENT/revision0 per existing read contract. Corrupt/oversized/nonregular R is blocked and cannot be accepted as current. Read original receipt as bounded raw bytes even if framing is malformed; nonregular/oversized control files remain blocked. Missing receipt is reported separately from a present empty file. Inspect pending names boundedly even if candidate is missing; unknown/nonregular/oversized entries remain blocked.

Inspection output is closed bounded canonical JSON≤4096 bytes with exactly `{phase,receipt_present,receipt_bytes,record_hash,registry_hash,registry_revision,registry_bytes,pending_present,entries,review}`. Phase is a valid receipt phase or MISSING/MALFORMED. Missing receipt uses bytes0 and SHA256(empty) with receipt_present=false; missing R uses hash ABSENT, bytes0 and revision0. entries has the same closed shape as receipt.recovery.entries. review is SHA256 of canonical output without review. Do not return bodies, internal exception text or tickets.

Normal recovery requires valid prior metadata and appropriate preservation witnesses: PREPARED needs candidate; PUBLISHED/CLEAN need R matching post; ACTIVE needs empty slot and unchanged preimage. Missing/malformed metadata or missing PREPARED candidate needs explicit `--accept-current`, not an automatic fallback. `--accept-current` is operator authority to keep the currently validated committed R, preserve observed remnants, and abandon replay of the incomplete attempt. It never promotes a pending candidate, restores a prior R, deletes files, searches for moved material or fabricates missing data. If R is absent, require `--confirm-empty-registry`; record that explicit empty-state acceptance. Unsupported types/count/size still deny even with these flags.

### Archive decision record

Create immutable canonical `decision.json`≤4096 bytes with exactly `{format_version,action,review,observation,incomplete_attempt_abandoned,empty_registry_confirmed}`. format_version is integer1. action is RECONCILE or ACCEPT_CURRENT. observation is the exact nine-field inspection object excluding review. review must match it. incomplete_attempt_abandoned is true only for ACCEPT_CURRENT and means no future replay, NOT rollback of already committed R. empty_registry_confirmed is true only for explicit accept-current of ABSENT R. Preserve available bytes at their actual length; do not pad a torn receipt to impersonate the original valid frame.

Recovery order:

1. Reinspect and compare exact review, validate action/empty-state permission, all paths/types/bytes/counts and pre-encode frames, decision and final output. No effects on mismatch. Reject archive placement inside managed pending/control paths and cross-filesystem or existing archive destinations.
2. Create one fresh archive exclusively; copy observed raw receipt to receipt.bin (empty only when inspect recorded absence); write decision.json exclusively. Synchronize both files, close, archive directory and parent. Existing bytes are never overwritten. Errors return no ticket and retain artifacts.
3. Persist RECOVERING with exact archive path, hashes of both archive files, current registry hash and entry manifest. Use the valid old generation/metadata when available, otherwise a new generation and current registry hash as pre; no invented historical post. Synchronize/close before moving anything.
4. Move the entire reviewed holding directory to archive/pending with atomic no-replace rename, preserving candidate and any reviewed caller publish replacement. If holding was already absent and explicitly accepted as current, create an empty archive/pending and record its original absence in decision. Never use absence as implicit successful recovery. Verify archived manifest and decision. A post-observation change must cause refusal without deleting/restoring the changed material.
5. Synchronize each archived regular payload file, then archive/pending, archive and the source parent. Revalidate current R, decision, receipt and entry hashes. Directory fsync is not a substitute for a previously failed payload fsync.
6. Recreate the empty fixed holding directory exclusively if the move consumed it; a real empty already-created slot is permitted only as the matching resumable plan, while nonempty/type collisions deny. Synchronize its parent.
7. Generate a fresh ticket, persist/fsync/single-close READY with only its hash. Return bounded JSON with status READY, action, archive path, registry_hash and ticket ONLY after every required operation/close succeeds. The ticket is not persisted in plaintext or put in HTTP. Output failure is not permission to auto-start.

A valid RECOVERING/READY resume must use its exact archive, match the decision/action and verify all preserved material; no second archive or replay. After a failure before a valid recovery plan exists, a new explicit invocation may choose a fresh archive and leave the prior one untouched. After corrupted metadata, accept-current may similarly create a new bounded archive without scavenging/deleting former operator archives. No automatic retries. If a recorded archive loses material, normal resume remains blocked; accept-current may abandon that failed plan only after new explicit inspection/review, preserving current observable state and recording that choice, never pretending missing old material is present.

Exit0: successful inspection or completed recovery with emitted ticket. Exit2: syntax, mismatch, collision, bounds, unsupported primitive, invalid state or I/O/close failure. No `--force` deletion, replay or general filesystem repair mode.

## 7. Explicit startup handoff

Add only `AIDDOS_SCENARIO_RECOVERY_TICKET` as a narrow startup input (an explicit exception to the old no-new-env clause, not a second state-path configuration). A64lowerhex ticket is manually supplied with the existing state path on one API launch. No normalization. Never save it in .env, automatic restart configuration or HTTP logs.

The first fully validated save can consume matching READY by checking the current registry, empty slot, archived raw receipt, decision and entry manifest, then writing/fsyncing/single-closing ACTIVE before candidate acquisition. Forget the live token after that attempt; do not reread environment per request or remint it through another ScenarioStore peer. Invalid/old token denies writes. Ordinary verified CLEAN restart needs NO ticket. Replay after ACTIVE transition fails. Consume error returns no success and allocates no candidate; a later manual recovery can issue a new ticket. GET and construction do not consume or repair anything.

## 8. UI/API behavior

All existing HTTP success/error envelopes, routes and codes remain unchanged. Use fixed SCENARIO_STATE_UNAVAILABLE text `Scenario storage is unavailable or write-quarantined. History reads do not unlock saves; follow the offline recovery guide.` and SCENARIO_COMMIT_UNCERTAIN text `Scenario may have been saved. Read its history; unresolved storage failure requires offline recovery. Do not resubmit automatically.` Never say all healthy restarts require recovery.

The independently assigned ScenarioLibrary slice latches storageBlocked after mutation SCENARIO_STATE_UNAVAILABLE or SCENARIO_COMMIT_UNCERTAIN; disables creation/edit/submission across close, GET-only retry and discard/reopen; preserves history, pagination, draft review/copy and closing. Show EN/KO guidance distinguishing acknowledgement read from offline storage recovery. Page reload resets only local observation, not server enforcement; there is no new status polling or recovery web UI. Keep captured-definition/digest/exact-history acknowledgement, deadlines and focus contracts unchanged.

## 9. Mandatory executable acceptance

- Preserve unchanged original B01/B02 REDs. Rebind eliminated mkstemp/cleanup-stat probes to exclusive candidate acquisition and actual last publication-source observation, require every injection to fire. Zero-residue assertions change ONLY to bounded retention, preimage/foreign preservation and repeat/restart refusal.
- Actual candidate open/fstat/fdopen/write/short-write/flush/fsync/stream-close/raw-close/link; source and destination directory open/fsync/close; PREPARED/PUBLISHED/CLEAN receipt open/write/short-write/fsync/close; post-publication/retirement/final-marker faults. Inspect/recovery/archive/READY/consume equivalents, including primary plus secondary close errors and no descriptor retry.
- Real exposed-source unlink/recreate and last-observation replacements preserve exact caller bytes; late reappearing publish is retained and fences subsequent saves. Private normal committed-link retirement is separate from forbidden failure cleanup.
- Managed byte/count boundary and plus-one before effects; repeated same-process and actual fresh-process denial without growth; bounded unexpected-entry handling; nofollow/type/collision errors at every managed slot. Existing whole-registry/version quotas remain exercised by canonical tests.
- Actual full ScenarioState/API path: validated CLEAN restart permits next save without ticket; bad digest/size/nonempty slot/missing slot/torn receipt/non-CLEAN refuses. CLEAN final-tail error stays blocked in live owner but verified new owner may resume, explicitly classified as approved semantics.
- Explicit recover/accept-current CLI through subprocesses: valid/missing candidate, damaged/missing receipt, caller replacement, incomplete archive, exact review binding, required empty-state confirmation, archive no-overwrite/cross-filesystem rejection, no replay, immutable history/draft preimages, recovery interruption/resume and repeated faults. Prove new writes only after valid handoff or validated CLEAN restart.
- Every failed recovery returns no ticket; default startup never repairs state. Missing/changed archive material denies ordinary resume; only a separately explicit accept-current invocation may abandon it with a new decision record. Operator archives remain untouched.
- Real process-exit/reopen tests establish process visibility/admission, not device power-loss durability. Keep synthetic fault tests labeled separately from natural faults and production execution.
- Final source-bound API/UI/lint/build/browser gates, independent product review, active preservation/promotion and separate exact-commit verification remain mandatory. No current primitive PASS closes S01 or authorizes S02.
