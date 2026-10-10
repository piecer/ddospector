# S01 — Versioned scenario definitions and expected policies

Current status: IMPLEMENTED_REVIEW_ACCEPTED. Independent correction-3 review `deleg_f50e0d17` closes S01-RET-REVIEW-01 on the corrected source: all six correction rows and 22 backend rows pass. Parent isolated verification passes API 1160, UI 319, Chromium 86 and eight real browser storage-error/recovery cases plus three accept-current cases. The approved retention/recovery policy remains unchanged. See `../SCENARIOS_VERIFICATION.md`. Final-document canonical gates, active-service preservation, commit and exact-commit verification are separate release gates recorded in the local campaign receipt; S02 cannot begin before they pass. Three correction cycles are consumed, with no fourth automatic correction.

## Historical correction records

The following authorization and failure paragraphs record predecessor states, not current open findings. Their original evidence is preserved; the current status above supersedes their pending/blocked labels, not their normative contract clauses.

Current authority: CORRECTION_03_AUTHORIZED. After the recorded two-cycle BLOCKED result below, the user explicitly approved one additional fix-and-reverify cycle limited to S01-RET-REVIEW-01. Cumulative S01 limit is 3, previously consumed cycles remain 2, and no existing recovery or product contract changes. See `.hermes/artifacts/campaign-01/S01/peer-fence-correction-approval.json` and the controlling retention addendum. The following status paragraph is the preserved correction-2 outcome, not an unanswered approval request or permission to waive the failure.

Status: BLOCKED_CORRECTION_LIMIT; RETENTION_AND_AVAILABILITY_POLICIES_APPROVED. Parent: `80f7da4c9a3d09702f165e40c824de46823b1e76`. Governing sequence: `docs/IMPLEMENTATION_CAMPAIGN.md`. Initial independent review `deleg_5f90a2b4` identified S01-C01 (acknowledgement binding) and S01-C02 (historical references). Corrective independent review `deleg_d1892f57` accepted both fixes and N01/N02 clarifications. Later product review `deleg_69a7575a` passed frontend composition but reproduced S01-B01 (caller replacement deletion) and S01-B02 (initial metadata-failure residue). Corrective cycle 1 `deleg_9207279d` added durable failing regressions without changing production code; both blockers remained at that time. The user approved bounded retention/write quarantine/explicit recovery, then verified CLEAN restart and explicit acceptance of current valid state after preserving incomplete material. `docs/stages/S01_RETENTION_RECOVERY.md` is the controlling correction contract; its explicit policy deltas supersede conflicting persistence/precedence/no-new-env/file-ownership clauses here. It does not waive caller preservation, immutable history, byte/count limits or independent verification. See `.hermes/artifacts/campaign-01/S01/retention-policy-approval.json` and `retention-availability-approval.json`. Correction cycle 2 and independent review `deleg_4b1519b4` completed: B01/B02 pass under the approved policy, but S01-RET-REVIEW-01 reproduces concurrent peer construction erasing a consumed-ticket fence. The parent reran the unchanged real-child probe: sequential control PASS, overlapping peer FAIL (201 instead of 503). Both correction cycles are consumed, with no reset or further product repair. Product acceptance, active promotion, commit and S02 remain blocked. Current evidence is `.hermes/artifacts/campaign-01/S01/retention-review-result.json`; frozen review inputs remain preserved separately.

## Product scope

Extend the existing `/profiles` page with a real scenario library: create a definition, inspect it, save a new immutable revision, and inspect every historical revision. Preserve template details and all existing routes. Add a link from campaign planning to this library; do not change legacy CampaignInput or pretend a scenario is already a runnable/approved campaign. Frozen run binding is S02; autonomous multi-case campaign execution is S12.

No inference, MCP connection, DNS, file upload/read of user-supplied paths, device action, or packet transmission. Registration is NOT approval. This stage records a declared PCAP identity, not a verified or imported asset. Existing UI-01 and AI-02 wire/persistence shapes remain unchanged.

## Files and ownership

Backend implementation slice:
- New `src/aiddos/api/scenarios.py` (closed models and API router), `src/aiddos/api/scenario_store.py` (registry storage).
- Modify only backend wiring in `src/aiddos/api/app.py` and new fixed codes in `src/aiddos/api/errors.py`.
- New `tests/api/test_scenarios.py`, `tests/api/test_scenario_storage.py` plus producer fixture generator if required under `tests/api/`.
- No changes to existing draft models/store/catalog/boundary behavior, dependencies, or legacy tests unless a demonstrated unavoidable regression needs a parent-approved contract update.

Frontend implementation slice:
- New `web/src/pages/scenarios/` modules, tests, styles and producer-consumer fixtures.
- Modify `web/src/pages/lab/profiles.tsx` only to mount the scenario library and `web/src/pages/operations/CampaignsPage.tsx` only for its navigation link.
- Extend corresponding existing tests only when the new nested UI genuinely needs test setup; preserve their behavioral assertions.
- No edits to App, Dialog, existing AI-settings implementation, dependency manifests, navigation/route list or existing API contracts.

Parent integration:
- `web/e2e/scenarios.spec.ts`, documentation, source manifests, final gates and commit.
- One owner at a time for shared files; implementation workers never edit the active checkout or commit.

## Closed definition schema

Every listed field is required, including explicit null. Models use strict primitive types, extra fields forbidden recursively, no coercion of strings/bools to numbers. Existing bounded text validators apply unchanged; never resolve addresses or normalize stored literal strings. Name limits count Unicode code points as the Python producer does. Browser acceptance must use producer-compatible validation, not native lowercase/URL guesses.

S01-specific browser validation preserves leading/trailing whitespace when the existing Python Name/Goal validator permits it, rejects all-whitespace text, counts non-BMP code points once, and permits only the Goal multiline control exceptions. Do not reuse the stricter AI `literalText` helper or UTF-16 `.length` as a drop-in rule. Raw response JSON must reject duplicate object keys (including escaped aliases), nesting over 32, invalid UTF-8, non-finite values and floating-point/exponent numeric tokens before JSON.parse erases token distinctions. All admitted numeric fields are integers; direct object validators additionally reject unsafe integers and bool/string coercion. Existing API request grammar and legacy consumers remain unchanged.

`ScenarioDefinition`:

| Field | Contract |
|---|---|
| `name` | Existing Name: 1–120 code points, nonblank, no prohibited controls |
| `objective` | Existing Goal: 1–2000 code points, multiline rules |
| `target_id` | Existing Identifier referring to an existing DUT target |
| `sink_id` | Existing Identifier referring to an existing SINK target; different from DUT |
| `dut_version` | Existing Name; operator declaration, not discovered firmware |
| `policy_version` | Existing Name; operator declaration, not independently verified policy |
| `profile_id` | Literal `tcpreplay-policy` or `k6-http`; passive capture template is not a source |
| `protocol` | `TCP`, `UDP`, `DNS`, `HTTP`; k6-http requires HTTP; replay supports TCP/UDP/DNS only |
| `ip_version` | Strict integer 4 or 6; a hostname target remains unresolved, not claimed IPv4/IPv6 compatible |
| `expected_action` | `ALLOW`, `BLOCK`, `ALERT` |
| `delivery_expectation` | `ALLOW` or `BLOCK`; must equal expected_action for ALLOW/BLOCK; explicit independent choice for ALERT |
| `detection_required` | boolean; ALERT requires true |
| `pcap_asset` | null or closed `{label:Name, sha256:64 lowercase hex ASCII, size_bytes:integer 1..67108864}`; k6 requires null. Replay may be null for a definition with asset missing. No file path, URL or executable content |
| `traffic_budget` | Closed six-field object below; no implied safe defaults |
| `success_criteria` | Closed three-field object below |
| `stop_conditions` | Closed six-field object below |
| `evidence_requirements` | Unique array, 1..5 entries selected from `ingress_pcap`, `egress_pcap`, `dut_events`, `service_probe`, `resource_metrics` |

`traffic_budget`: `max_pps` 1..1000000000, `max_bps` 1..1000000000000, `max_packets` 1..1000000000000, `max_bytes` 1..1000000000000, `max_connections` 1..1000000, `duration_seconds` 1..3600. All strict integers and representational ceilings, NOT device-safe values. Future LIVE admission must intersect capability and operator approval; S01 never approves them. A configured connection bound does not prove replay supports counting actual sessions.

`success_criteria`: `minimum_delivery_pct` integer 0..100, `maximum_delivery_pct` integer 0..100, `detection_deadline_ms` integer 1..60000 or null. Minimum <= maximum. ALLOW delivery requires maximum=100; BLOCK delivery requires minimum=0. Detection required means a non-null deadline; otherwise deadline must be null. These are expected observation bounds, not a passed measurement.

`stop_conditions`: `max_legitimate_loss_pct` integer 0..100, `max_service_latency_ms` integer 1..60000, `max_cpu_pct` integer 1..100 or null, `max_memory_pct` integer 1..100 or null, `max_sessions` integer 1..1000000 or null, `management_loss` literal true. Emergency/operator stop remains mandatory globally and cannot be disabled through this schema. Threshold values are operator declarations only.

Cross-field evidence rules: ingress_pcap and egress_pcap are required for replay; service_probe required for every definition; dut_events required when detection_required; resource_metrics required when any CPU/memory/session stop threshold is non-null. k6 requires service_probe but no mandatory PCAP roles. Order is preserved; duplicates rejected.

## Immutable version and snapshot binding

`ScenarioVersion` has exactly:
- `id`: server UUID string under existing Identifier grammar.
- `version`: integer 1..10, consecutive within scenario identity.
- `created_at`: existing timezone-aware Timestamp.
- `status`: literal `definition`.
- `execution_enabled`: literal false.
- `definition`: ScenarioDefinition above.
- `target_snapshot`, `sink_snapshot`: full existing Target wire objects copied on each authorized version save, with matching IDs and DUT/SINK kinds.
- `profile_snapshot`: exact matching existing PROFILES_V1 record, not a mutable reference.
- `catalog_version`: literal current catalog `1.0.0`.
- `digest`: SHA256 of UTF-8 `json.dumps(record_without_digest, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)` bytes. No floats in this contract. Persisted reads and browser response validation recompute this digest and validate the internal snapshot/cross-field invariants below. Browser canonical serialization must match these exact producer bytes; field keys are ASCII, text literals are not normalized.

A new version may choose a different registered target/sink/profile or declared DUT/policy version; its snapshots and digest reflect that choice while earlier records remain byte-equivalent as JSON values. Future run planning selects one exact `(id, version, digest)`. No destructive update/delete. Names need not be unique; immutable ID/version are identity, avoiding accidental text casefold identity.

Save-time references and historical replay are different boundaries:
- POST/PUT hold the path-keyed scenario lock, then acquire the existing DraftStore lock, read one validated draft snapshot and keep it stable through reference selection and scenario publication. Copy the selected complete DUT/SINK records and exact pinned catalog record. Existing draft writers do not acquire the scenario lock, avoiding reverse lock order.
- GET list/history read ONLY the scenario registry. Validate embedded target/sink IDs against definition IDs, DUT/SINK kinds, closed target schemas, exact pinned profile/catalog, consecutive versions, counts and digests. Never look up or rebind historical records against today's draft file.
- A missing/changed/corrupt current draft source must not destroy access to valid scenario history. A missing draft file means an empty source on mutation, so references fail with INVALID_REFERENCE. A corrupt/unavailable draft source retains existing STATE_CORRUPT/STATE_UNAVAILABLE; SCENARIO_STATE_* is reserved for registry failures. Failed mutations change neither file.
- 'Foreign snapshot' means internally inconsistent embedded links or pinned catalog, NOT a historical target missing from today's draft source. A self-consistent locally edited record with a recomputed hash is not authenticated provenance; the digest detects accidental inconsistency, not hostile filesystem tampering.

## API

All responses use existing no-store/Origin/Host/body admission. All new error bodies use the existing fixed `{code,message}` envelope; never reflect input or filesystem errors.

- `GET /api/v1/scenarios?offset=0&limit=50` → 200 `{revision,total,offset,limit,items,execution_enabled:false}`. Items are latest ScenarioVersion in insertion order. Strict ASCII decimal query values; offset 0..100, limit 1..100. Unknown/duplicate query keys, empty/sign/leading-zero except literal 0/fraction/bool rejected with 422. Omitted keys use the defaults. offset beyond total returns empty. `revision` is global registry CAS counter, 0 for empty.
- `POST /api/v1/scenarios` request `{revision,definition}` → 201 `{revision,scenario,execution_enabled:false}` with global revision incremented, fresh UUID/version=1.
- `GET /api/v1/scenarios/{id}` → 200 `{revision,scenario_id,versions,execution_enabled:false}`. Full chronological 1..10 history. Malformed ID →422, well-formed absent ID→404.
- `PUT /api/v1/scenarios/{id}` request `{revision,definition}` →200 same mutation envelope, append next immutable version. Uses the registry revision loaded when edit opened, not latest ambient workspace state.
- `revision` request integer 0..9007199254740990; response <=9007199254740991. These are syntactic safe-integer bounds. Under the count invariant, a valid registry revision is the total number of saved versions and is at most 1000; larger persisted revisions are corruption, not a reachable terminal-counter state. Test actual identity/version quotas rather than fabricating a valid terminal-counter registry.
- Failures: `SCENARIO_CONFLICT`409 (stale revision), `SCENARIO_NOT_FOUND`404, `SCENARIO_LIMIT_REACHED`409 (100 identities or 10 versions per identity), `SCENARIO_STATE_CORRUPT`503, `SCENARIO_STATE_UNAVAILABLE`503, `SCENARIO_COMMIT_UNCERTAIN`503. Invalid schema/cross-field/serialized record >8192 UTF-8 bytes → existing VALIDATION_ERROR422; invalid DUT/SINK ID/kind → existing INVALID_REFERENCE422. Existing request transport errors retain precedence.
- Mutation precedence after transport/schema validation: read/validate registry and one locked draft source; CAS conflict; referenced target/sink/profile validation; identity/version/count admission; serialize complete candidate; atomic publication. Missing ID takes SCENARIO_NOT_FOUND after CAS and reference validation on PUT. GET list/history never require draft-source access. Existing STATE_CORRUPT/STATE_UNAVAILABLE from the draft source pass through without remapping.

## Persistence and budgets

- Separate single-process registry, derived from the effective existing DraftStore path using `draft_path.with_name(draft_path.name + '.scenarios.json')`. Thus isolated test state stays isolated. Do not introduce another environment variable or read live `.local` state during tests.
- Exact persisted shape: `{format_version:1, revision, scenarios:[{id,versions:[ScenarioVersion,...]}]}`. Empty revision0 requires empty scenarios; every create/append increments exactly once, so revision equals total version count. Max100 identities ×10 versions. IDs are unique and each nested record matches its owning ID.
- Missing file means empty; malformed/incomplete/wrong primitive/wrong digest/nonconsecutive version/oversized/foreign snapshot state means corrupt. GET never creates/rewrites/repairs a file.
- Use path-keyed same-process lock, NOFOLLOW/NONBLOCK regular-file reads, maximum16MiB read, temp write in same parent, fsync, replace, directory fsync. Preserve preimage before publication failure; return uncertain after replace/fsync failure. Never follow symlinks or delete caller files. No multiprocess guarantee; S02 execution state is separately transactional.
- Each ScenarioVersion's complete serialized wire record <=8192 UTF-8 bytes. Latest-page response <=1MiB; history response <=256KiB; mutations <=256KiB. Enforce server serialized output budgets and browser raw-byte limits, not character estimates. Max1000 records remains under state budget, with explicit serialized prewrite validation.
- Scenario revisions are their own append-only local history, not an execution approval log. Do not extend existing workspace/audit payload with unknown fields.

### Approved failure-retention boundary

The approved correction retains at most one pending candidate of 16 MiB per registry plus a fixed 4 KiB receipt. Failed named staging is never automatically unlinked, overwritten or replayed. Unresolved failure denies further writes, including after restart, while valid history remains readable. The explicit approved exception is a fresh coordinator's verified CLEAN restart with matching valid registry hash/size and an empty real pending directory; even a predecessor's final-marker tail error need not remain permanently quarantined after that check. Explicit operator-reviewed recovery may preserve observable remnants and accept current valid state despite missing pending material or damaged receipt, recording abandonment without replay or rollback. Follow `S01_RETENTION_RECOVERY.md` for the exact framing, bounded archive/decision record, action/empty-state confirmations, handoff, failure matrix and test-selector adaptations. Existing foreign entries remain foreign regardless of recognizable names. The bound covers product-managed pending data, not arbitrary caller-created or explicitly operator-archived artifacts. No live-data recovery is authorized by test implementation alone; policy approval is not product GREEN.

## Browser workflow and failure lifecycle

- Existing `/profiles` page mounts library with own GET and explicit reload; template panel remains functional. Creation needs a DUT and SINK and a valid library load; missing prerequisites offer existing Targets navigation. Existing App fail-closed behavior is retained.
- Real form fields for every definition field, localized English/Korean labels/help/errors; no JSON textarea as the only editor. Keep user-authored text literal and original language.
- Show ID, version, declared firmware/policy, expected action/delivery/detection, snapshot identities, required evidence, budgets/thresholds, asset identity or missing status, digest, and history. All entries remain accessible with pagination.
- Native dialog scroll/focus at 1440/1024/390. No clipping, label association, keyboard controls, close while pending, no duplicate submit or late-settlement focus theft.
- Loading/read failure is not an empty list. Disable all writes while loading/stale/unacknowledged, preserve draft values, expose explicit read retry and close. Do not auto replay mutation, rebase an open draft to a newer revision, or manufacture success after request abort.
- Capture the exact submitted definition and edit-opening registry revision/version before sending. A mutation response is valid only when its registry revision equals submitted revision+1, its definition is deeply equal to the captured submission with exact literals/nulls/array order, and its digest recomputes correctly. POST must return a valid server-generated UUID and version1; PUT must return the selected ID and opened version+1. Never use a newly fetched ambient revision to rebase the captured submission.
- Acknowledgement additionally requires GET history for that exact ID, with readback registry revision at least the mutation revision, containing the identical complete acknowledged record. A concurrent append may make another version latest; do not require the latest-page item to retain the acknowledged digest. Reload the list for navigation independently. Wrong definition, wrong digest, stale/contradictory history or transport/readback failure enters read-only recovery. Preserve draft values for review/copy and offer explicit retry-read/close/discard-and-reopen; no mutation replay. Retain a valid mutation receipt so retry can repeat history verification without resending.
- Request deadline10s covers response body and validation; abort must settle even if fetch ignores abort. No redirects; same-origin credentials; bounded raw response decode; closed recursive response schemas.

## Required TDD and acceptance inventory

1. Empty read without files; create against real registered DUT/SINK; process-local reopen retains record and exact immutable history; v2 draft/AI state unchanged. Historical list/history remain readable after draft file removal, mutation or corruption; mutation against the same broken source fails without changing either file and with the specified source-specific error.
2. New revision + changed definition/snapshots; old snapshot/digest preserved; POST and PUT stale CAS deny without write; concurrent same-process instances accept only one competing revision.
3. Strict schemas, Unicode text/codepoint boundaries and literal preservation (including surrounding whitespace, multiline Goal and non-BMP text), unsafe metadata, all action/detection/profile/evidence combinations, ints/bools/floats/missing/extra, exact limit and limit+1; actual producer bytes through browser parser. Mutate duplicate/escaped duplicate JSON keys and integer tokens to floats/exponents before the raw browser decoder.
4. Identity/version/list limits and strict pagination, complete reachable histories, fixed errors; unsupported methods and no hidden delete.
5. Storage malformed/oversize/symlink/nonregular/digest tamper/nonconsecutive version, no GET repair, filesystem failures before/after replace preserving truthful uncertainty. Returned structures cannot mutate persisted state.
6. Existing model/LIVE/agent denial path still rejects malformed and valid inputs without execution. No outbound requests in any S01 API operation.
7. UI create/edit/history, all fields and both languages, invalid/missing references, initial error/retry, stale conflict, uncertain save, readback failure, pending close/late settlement, byte/timeout response boundaries, responsive keyboard accessibility. Reject otherwise-valid wrong-definition acknowledgements and wrong digests; accept an identical acknowledged record retained in history after a concurrent append. Retry recovery sends GET only.
8. Parent E2E uses actual canonical API/Chromium and isolated state: create targets→UI create revision1→UI edit revision2→history revision1 unchanged→reload; both locales; 390px; real API CAS conflict; no execution. Existing full browser suite remains green.
9. Independent read-only source review plus fresh canonical gates after final edits and exact-commit verification. No manufactured counts or silent skips.

## Future boundary

This stage does not implement Run queue, DB migrations, evidence import, evaluation, approval, discovery or inference. The fact that a definition records a limit or asset digest does not establish feasibility, safety, ownership or artifact integrity. Those are explicit later gates; UI warnings must preserve that distinction.
