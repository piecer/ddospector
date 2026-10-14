# P2-01 transport and storage contract

This freezes registration boundaries before integration. It does not claim any
endpoint is implemented yet. P2-00 parser limits remain unchanged.

The preceding introduction and P2-01 placeholder-report clauses preserve the
historical contract. Current status: P2-01 registration/readback and the P2-02
evaluation backend are implemented and independently accepted. The closed
[P2-02 evaluation contract](PHASE2_EVALUATION.md) supersedes only the temporary
report:null/REGISTERED-only behavior: validated retained reports can now produce
ANALYZED and Detail.report. HTTP still accepts no evaluation/report submission.
Evaluation is explicit through
`python -m ddospector.evidence.evaluate --evidence-id UUID` or
`make phase2-evaluate WORKSPACE=... EVIDENCE_ID=...` with original running-workspace
custody. `make test-phase2-evaluation` is the scoped backend gate.
This synthetic capture-record criterion is not DUT, session, service or defense
acceptance. P2-02 is committed at `546b82ca1285b5fd5d644f730ff9b90f51626c7c`. Evidence UI
and client-side EN/KO exports now have independent frontend acceptance and are
integrated without changing accepted runtime/test/fixture bytes. UI B1/B2 are
CLOSED; round-2 was a legitimate mock correction, not weakened assertions. See
[PHASE2_UI.md](PHASE2_UI.md) for the frozen acceptance and provenance. Historical
actual-producer Evidence fixtures are not fresh current-backend runs. Conservative
failed-POST pending (N1) remains unchanged: GET-only resolution, no automatic
retry or silent receipt clearing. Actual P2-03 browser → API → PostgreSQL →
explicit CLI evaluator → exports → ordinary-open acceptance remains PENDING.
No full Phase-2 or DUT acceptance is claimed; a commit does not close that gate.

## Deliberately small upload budget

For this first generated-PCAP workflow, the HTTP service accepts **1–65,536 raw
bytes per side**, not the parser's broader 1 MiB defensive ceiling. This keeps
both base64 inputs plus metadata inside the existing 256 KiB pre-framework JSON
body limit; do not enlarge every API route's body allowance. UI, CLI guidance,
server admission, storage constraints and tests must expose this 64 KiB limit.
The pure parser still hard-refuses input beyond 1 MiB. Larger real captures are
future scope, not silently truncated uploads.

Use the existing body/framing reader: Origin/Host, duplicate security headers,
JSON encoding, 256 KiB, 4096 body frames and five-second body reception remain.
Evidence GET/HEAD routes also reject body/transfer framing. Database operations
reuse the existing four-retained-operation manager with a five-second operation
deadline after body admission; existing retirement and error behavior are retained.
No new worker/executor is created by registration or read requests.

### Pre-body admission (independent review B1)

Permit exactly **one evidence upload pipeline per API process**, shared across
application instances in that process, using a non-waiting bounded semaphore.
After common Host/Origin/header validation and before the first body receive,
acquire it for every POST under the exact evidence namespace (root or slash
descendant). If occupied, return fixed **429 EVIDENCE_BUSY** without reading any
body, JSON/base64 decoding, invoking the handler or entering the DB manager.
Do not enqueue or retry the request. Reject other mutation methods in this
namespace before receiving their body, so an unsupported method cannot bypass
the acquisition limit. GET/HEAD reject body framing; OPTIONS remains the existing
header-only preflight. Other namespaces retain their existing behavior and caps.

The request owns the permit through body reception, framing/JSON/base64 validation,
DB wait and application response/exception completion. Release exactly once in
the outer ASGI finally path, including disconnect, body timeout, invalid data,
handler exception, cancellation and send failure. Do not release on a timer while
that request still owns buffers or its application task remains active. No parser,
DB worker or client callback may independently release this permit.

Delayed DB disposal after an HTTP request exits remains held by the existing
four-operation Manager until actual retirement; returning the upload permit does
NOT assert DB retirement. These are two distinct bounds, not one interchangeable
counter. Supported operation remains one API process per workspace; no claim of
a cross-process/distributed upload semaphore is made.

Executable gate: hold the sole permit with an incomplete body; a second POST
must return 429 with zero receive/decode/handler/DB calls. Exercise release and
subsequent admission after disconnect, timeout, framing/validation rejection,
handler failure, cancellation and failed send; hold through a stalled response.
Check shared-process application instances and unsupported-method bypasses.
Keep the unchanged offline-runs 1024-byte and generic 256 KiB positive controls.

## HTTP namespace

Prefix `/api/v1/evidence`; identifiers use the existing literal lowercase UUIDv4
validator. Reject unknown/duplicate query fields and unknown JSON keys.

- POST root: closed JSON `{request_id, run_id, ingress, egress}`.
  Each side is exactly `{name, base64}`. Names are 1–128 characters, at most 256
  UTF-8 bytes, no control characters or lone surrogates, preserved verbatim.
  Character count means Unicode code points. Reject U+0000–001F, U+007F–009F,
  unpaired U+D800–DFFF, and bidi controls U+202A–202E/U+2066–2069; do not trim,
  normalize or rewrite accepted names or identifiers.
  Names are display metadata, never filesystem paths or download headers.
  Validate encoded length before base64 decoding; require canonical standard
  base64 and decoded length in 1–65,536. Compute length/SHA256 server-side.
  Require an existing SUCCEEDED OFFLINE preparation Run with valid immutable
  snapshot/result. Registration stores evidence, not a claim of valid parsing.
- New registration: 201 Detail. Same request ID and identical complete input:
  200 original Detail without allocating another record. Same ID/different
  input: 409. Commit uncertainty is explicit; no automatic POST replay.
- GET root: closed `{schema_version:1,items:[Summary],total}`. At most 16 rows,
  ascending immutable ordinal; no raw blobs, packet lists or evaluation outcome
  in the list projection. Missing/unready storage is not an empty list.
- GET `/by-request/{request_id}` and `/{id}`: Detail or explicit 404. The former
  is the read-only resolution path for an unacknowledged submission.
- GET `/{id}/raw/{side}` with side ingress/egress: original verified bytes,
  fixed safe UUID/side download filename, bounded size and no content encoding.
  Verify stored byte length and SHA256 before emitting a response.
- Sample catalog/download and report export are added in later slices, not
  disguised as retained uploads or measurements.

Summary fields are exactly:
`id, request_id, ordinal, run_id, run_snapshot_digest, created_at, provenance,
sample_id, coverage, ingress, egress, analysis_state`.
Side descriptors are exactly `{name,size_bytes,sha256}`.
`provenance` is SYNTHETIC or UNVERIFIED; `sample_id` is the exact recognized
built-in pair ID or null; `coverage` is COMPLETE_SYNTHETIC or UNKNOWN.
These are derived from original pair digests, never caller flags.
`analysis_state` is REGISTERED or ANALYZED, derived from immutable report presence.
Detail is exactly `{schema_version:1,evidence:Summary,report:null|Report}`.
Report's closed schema is frozen separately before P2-02; initially no report
exists. Do not accept arbitrary unvalidated JSON in the future report slot.

Storage metadata is at most 4096 canonical UTF-8 bytes per bundle. Reserve a
32768-byte maximum immutable report body for P2-02; no public endpoint accepts a
report body. P2-01 responses have `report:null` and REGISTERED state; an unexpected
stored report is refused until a closed report validator is implemented. JSON
list/detail response ceilings are 65536 bytes, with no truncation. Bound fields
and collection counts before serialization; enforce exact-byte ceilings too.
Timestamps use the existing UTC microsecond `timestamp()` representation. Digests
are exactly 64 lowercase hexadecimal characters; integer fields reject booleans.

## PostgreSQL ownership, atomicity and immutability

Use `ddospector_evidence_v1`, separate from unchanged `aiddos_runs_v1`.
An explicit version/checksum/shape-checked owner-role migration installs it.
Do not run migrations on HTTP requests or ordinary workspace reopen. P2-01
onboarding is a fresh `create --evidence` workspace: install both schemas during
the original creator's bootstrap grant, before serving the API. Ordinary Phase-1
create remains unchanged. The normal end-to-end test creates its completed Run
in this new workspace rather than modifying the retained Phase-1 environment.

Do not add an existing-workspace initialization/upgrade command in this milestone:
`retained_pg` restores start/stop custody, not bootstrap authority. An old Phase-1
workspace still opens without mutation; its evidence endpoints report
EVIDENCE_NOT_READY and explain the fresh Phase-2 workspace path. Restoring
bootstrap grants, copying/adopting a foreign DB, and migrating old workspaces
require a separately designed explicit capability and are not implied here.
On any new-workspace initialization failure, preserve its owned data and show the
failure; do not launch the API with a claimed ready evidence schema.

- One quota row: retained_count 0–16, raw byte total bounded by two 64 KiB sides
  per pair; validate counters against actual rows using bounded scalar queries.
- Immutable bundle row: UUID, unique request UUID, ordinal, linked Run UUID,
  source snapshot digest, request identity digest, both original bytea captures
  and bounded metadata. Raw captures and metadata are one transaction, not split
  file/DB writes. Runtime role gets SELECT/INSERT, no bundle UPDATE/DELETE.
- Separate immutable report row keyed by bundle UUID, bounded report bytes and
  digest. Runtime role gets SELECT/INSERT, no report UPDATE/DELETE. A unique key
  prevents a second publication; this does not modify the Run or its result.
- Acquire quota lock before allocating ordinal/inserting; an invalid/over-limit
  request leaves counters and records unchanged. Recheck existing request ID in
  the serialized transaction BEFORE rejecting a new allocation for full retention:
  an identical replay of a retained record still succeeds at capacity.
  Unknown COMMIT outcome remains unknown until GET.
- Read only scalar/metadata projections for lists; fetch at most the one selected
  pair for detail/download/integrity checks. A corrupt record never disappears
  silently from an otherwise successful list. List validation does not claim
  that raw blobs were fetched or rehashed; selected detail/download/analysis
  verifies original bytes before relying on them.
- No purge or automatic repair. Preserve Phase-1 schema readiness, jobs, events,
  result bytes, retained operator data and ordinary open semantics.

Use the existing public JSON error envelope `{code,message}` with fixed messages.
Add stable EVIDENCE_NOT_READY (503), EVIDENCE_NOT_FOUND (404),
EVIDENCE_RUN_NOT_READY (409), EVIDENCE_IDEMPOTENCY_CONFLICT (409),
EVIDENCE_RETENTION_FULL (409), EVIDENCE_STATE_CORRUPT (503),
EVIDENCE_CAPTURE_TOO_LARGE (413), EVIDENCE_BUSY (429, "Another evidence upload is in progress."). Existing framing/validation and shared RUN_*
resource/uncertain-commit errors remain possible and must be accepted by the
new client; do not expose driver messages, server paths or raw exception text.

## UI admission and verification

No fabricated rows. Preserve unavailable/error/empty distinctions. Retain request
identity after ambiguous POST and offer GET-by-request, never automatic resubmit.
Validate file sizes before reading them into browser memory; keep only one active
upload form. Verify all response fields/enums/digests/counts before rendering.

Required proof: exact/+1 byte and count boundaries; malformed/canonical base64,
wrong types/duplicate keys, no admission on rejection, idempotent replay/conflict,
missing schema/refused linked Run, corruption and raw-byte download integrity.
Then real owned PostgreSQL + TCP API + browser upload of generated files, with
unchanged original Run bytes and retained results across ordinary reopen. Keep
simple supported errors separate from the deferred W2 fault/recovery matrix.
