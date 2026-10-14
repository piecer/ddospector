# P2-01 immutable paired evidence storage

This slice implements registration and readback only. It does not evaluate TCP
forwarding, claim valid PCAP parsing, show a DUT result, or add UI/report export.
The original completed Run remains an OFFLINE preparation result.

Current status: P2-01 storage and the separately implemented P2-02 evaluation
backend have independent acceptance. The P2-01-only statements below describe
that slice's historical boundary. P2-02 now validates immutable reports under the
closed [evaluation contract](PHASE2_EVALUATION.md); it does not turn a synthetic
record criterion into a DUT/session/service/defense PASS. Use the explicit
`python -m ddospector.evidence.evaluate --evidence-id UUID` command, or the owned
running-workspace `make phase2-evaluate WORKSPACE=... EVIDENCE_ID=...` helper.

## Fresh-only provisioning

Use an explicitly new, private, durable workspace:

```sh
.venv/bin/python tools/phase1_local.py create --workspace /absolute/new-workspace --evidence
```

The equivalent Make entrypoint is `make phase2-local WORKSPACE=/absolute/new-workspace`.

The original creator provisions core Runs first, then invokes
`python -m ddospector.evidence.migrate` while fresh bootstrap authority is live,
before launching either server. A matching migration is read-only; a mismatched
schema is refused. Failure preserves data and leaves the workspace BLOCKED, not
ready. The low-level migration wrapper does not restore any bootstrap authority.

Ordinary `create` is unchanged. `open` and `worker` do not accept `--evidence`;
ordinary open never installs anything. A Phase-1 workspace without the separate
namespace returns `EVIDENCE_NOT_READY` from evidence endpoints. There is no
existing-workspace upgrade, grant restoration, purge, or automatic repair command.
The original private-UDS, sole-volume and retained-custody protocols are unchanged.

## Registration and reads

`POST /api/v1/evidence` accepts exactly `request_id`, `run_id`, `ingress`, `egress`.
Each side is exactly `{name,base64}`. UUIDs are literal lowercase UUIDv4. Names are
preserved, not normalized or treated as paths. The frozen control/bidi/UTF-8 rules
and canonical standard base64 rules are enforced before database admission.

Each side must contain 1–65,536 decoded bytes. This is deliberately smaller than
the parser's separate 1 MiB limit. Registration does not invoke the parser:
unsupported or malformed captures may be retained without a validity claim.
Both SHA256 values and synthetic-pair provenance are server-derived. An actual
validated SUCCEEDED OFFLINE Run is required; its immutable snapshot digest is
pinned without reading scenario files or rewriting Run inputs/results/events.

- New pair: 201. Identical request replay: 200, same original bundle.
- Changed input for a retained request ID: 409, including when retention is full.
- At most 16 pairs; a new seventeenth request is refused, never purged/truncated.
- GET root: bounded metadata-only summaries, ordinal ascending, exact total.
- GET `/by-request/{request_id}`: read-only resolution after an uncertain POST.
- GET `/{id}`: selected pair integrity verification before returning Detail.
- GET `/{id}/raw/ingress` or `/egress`: exact original bytes, verified length/SHA,
  fixed UUID/side attachment filename, octet-stream and nosniff, no content encoding.

List does not fetch or rehash all raw blobs; it validates every returned metadata
record and scalar quota counters. Selected reads fetch one pair and rehash both.
Unknown query fields, duplicate JSON fields and unknown object fields are refused.
Unavailable/unready/corrupt storage is not presented as an empty collection.

The accepted B1 process-wide one-upload permit and existing four-operation manager
remain unchanged. Existing body/framing limits, deadlines, disconnect handling,
retirement and uncertain-COMMIT errors apply. Do not automatically replay POST
when acknowledgement is uncertain; resolve by request ID first.

## Storage invariants

`ddospector_evidence_v1` has its own migration checksum/catalog shape marker. It
checks the core role/durability settings without changing the core schema. Marker
missing-table/column faults are EVIDENCE_NOT_READY, not connection unavailability.

The serialized quota row, immutable bundle (both bytea originals + canonical
metadata) and counter update commit together. Runtime receives SELECT/INSERT on
bundles/reports, no UPDATE/DELETE, and only the two quota-counter UPDATE privileges.
Immutable triggers add a second guard. A distinct report table reserves at most
32,768 bytes per bundle; no HTTP endpoint accepts report data.

Canonical metadata is capped at 4,096 bytes. JSON list/detail is capped at 65,536
bytes, with closed scalar/type validation before serialization and no truncation.
The closed Summary's valid scalar bounds keep ordinary projections below these
outer ceilings. SQL exact/+1 metadata/report tests establish storage-envelope
limits, not validity of arbitrary JSON at the ceiling.

P2-01 returns REGISTERED and report:null. Any unexpected stored report fails closed
until P2-02 introduces a closed validator; unvalidated future report JSON is never
published. No evaluator, analysis result or defense verdict is invented here.

## Verification and remaining acceptance

Focused pure/API tests cover strict admission, pre-serialization validation and
shared-manager error classification. The selected `tests/runs/test_evidence_postgres.py`
uses the original owned PostgreSQL fixture and one coherent normal PG16 instance
per invocation. It creates a real Run, runs the explicit separate one-shot worker,
registers all three generated pairs, verifies raw downloads and full-capacity
replay/conflict, compares original core request/snapshot/result/event bytes, checks
ACLs and SQL limits, and records actual ASGI response bytes plus source hashes.

Its corruption controls are disclosed owner-SQL fixtures inside that disposable
owned database, not runtime permissions or outage/recovery acceptance. The atomic
rollback control raises once after a real INSERT; it never restarts/kills the DB
or worker. Process exit, API clean drain and harness cleanup are recorded separately.

Independent review accepted the backend after closing retained timestamp hydration
misclassification. Unrepresentable stored timestamps are refused as corruption,
not mistaken for database unavailability; normal timestamps and original bytes
remain unchanged. The regression includes actual stored faults on all read/replay
paths, restoration controls and unchanged generic DB error handling.

Use `make test-phase2-storage` for the scoped storage gate, alongside canonical
API/web/lint/build checks and source-bound normal-wire fixture freshness. The final
retained fresh-workspace TCP/browser/ordinary-open gate remains pending; this
ASGI/PG proof does not replace it. The P2-02 evaluation backend is implemented and
independently accepted; `make test-phase2-evaluation` selects its scoped gate.
P2-02 is committed at `546b82ca1285b5fd5d644f730ff9b90f51626c7c`. Evidence UI
and client-side EN/KO exports now have independent frontend acceptance and are
integrated without changing accepted runtime/test/fixture bytes. UI B1/B2 are
CLOSED; round-2 was a legitimate mock correction, not weakened assertions. See
[PHASE2_UI.md](PHASE2_UI.md) for the frozen acceptance and provenance. Historical
actual-producer Evidence fixtures are not fresh current-backend runs. Conservative
failed-POST pending (N1) remains unchanged: GET-only resolution, no automatic
retry or silent receipt clearing. Actual P2-03 browser → API → PostgreSQL →
explicit CLI evaluator → exports → ordinary-open acceptance remains PENDING.
No full Phase-2 or DUT acceptance is claimed; a commit does not close that gate. Full S02,
W2, HA, multiworker, live capture/replay, DUT traffic and AI/MCP remain deferred.
