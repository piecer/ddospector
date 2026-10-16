# P2-02 frozen implementation contract

Base: f8a8a9b1d263299260092e9905ce447c81db84ab. P2-01 backend accepted;
final Evidence UI/TCP/ordinary-open acceptance remains P2-03. Files/retained bytes
only: no packet transmission/capture/DUT, LIVE, AI/MCP, W2 or recovery campaign.

## Single criterion and source

Use the selected bundle's original bytes and its actual immutable completed Run
snapshot, not current scenario drafts, filenames, generator expectations or a
caller-provided outcome. Verify stored metadata/raw SHA and source Run before work.
Pin evidence_id, run_id and run_snapshot_digest into the result. Existing Run
request/snapshot/result/events must remain byte-identical.

Rule TCP_ALLOW_CAPTURE_V1 is applicable only to snapshot definition with profile
`tcpreplay-policy`, IPv4, protocol TCP, expected_action ALLOW,
delivery_expectation ALLOW and detection_required false. All other valid scenarios
produce UNKNOWN/UNSUPPORTED_SCENARIO, not inferred block/defense success.

Read minimum_delivery_pct and maximum_delivery_pct from that snapshot's
success_criteria. They are exact integers 0..100 under the existing ScenarioDefinition
contract. Do not hardcode95. For valid ingress count n>0 and matched multiset count m,
SATISFIED iff minimum*n <= 100*m <= maximum*n. Otherwise VIOLATED. Judge only when
applicable, both parsers succeed and coverage is COMPLETE_SYNTHETIC. Any unmet
eligibility/coverage/data-quality condition produces UNKNOWN. Empty ingress is UNKNOWN.
Compute m as sum of minima of fingerprint multiplicities, not set intersection.
Egress-only records do not increase m. No timestamp-based latency/session inference.

recognize_pair against actual byte digests is the sole synthetic/coverage authority.
An unrecognized pair remains UNVERIFIED/UNKNOWN even with perfect observed matching.
The reference95..100 policy must yield complete SATISFIED, violation VIOLATED,
unknown UNKNOWN. At minimum90, violation may satisfy this partial criterion.

This is CAPTURE_RECORDSET_ONLY, not proof of replay asset identity, traffic-budget,
endpoint, session, service or whole-scenario compliance. Always retain
scenario_evaluation NOT_EVALUATED and defense_verdict null. Report requirements
other than ingress_pcap/egress_pcap as unassessed, preserving declared order.

## Closed report v1 (all fields required, no extras)

Report keys:
 schema_version: exact integer1
 kind: offline_capture_criterion
 rule_id: TCP_ALLOW_CAPTURE_V1
 scope: CAPTURE_RECORDSET_ONLY
 evidence_id, run_id: literal canonical UUIDv4
 run_snapshot_digest: lowercase64hex
 created_at: existing UTC microsecond timestamp representation; actual producer
   start time obtained from DB, not capture time or a claimed completion timestamp
 provenance: SYNTHETIC|UNVERIFIED
 sample_id: complete|violation|unknown|null, consistent with exact digest recognition
 coverage: COMPLETE_SYNTHETIC|UNKNOWN
 outcome: SATISFIED|VIOLATED|UNKNOWN
 scenario_evaluation: NOT_EVALUATED
 defense_verdict: null
 policy: closed subset below
 captures: exactly ingress and egress SideFacts below
 facts: MatchingFacts below, or null if either parser failed
 issues: unique codes in fixed order UNSUPPORTED_SCENARIO,
   CAPTURE_COVERAGE_UNKNOWN, NO_INGRESS_RECORDS when applicable; at most3
 unassessed_requirements: snapshot evidence_requirements excluding ingress/egress,
   exact original order, no duplicates (at most3)
 digest: record_digest over canonical report excluding digest itself

policy keys exactly: profile_id, ip_version, protocol, expected_action,
delivery_expectation, detection_required, detection_deadline_ms,
minimum_delivery_pct, maximum_delivery_pct, evidence_requirements. Values and
coherence match the existing ScenarioDefinition source; no implicit coercion.

SideFacts keys exactly: sha256, size_bytes, parse_error, packet_count, wire_bytes,
payload_bytes, first_timestamp_ns, last_timestamp_ns, timestamps_ordered.
size_bytes is1..65536 and sha256 authenticates the complete original even on error.
parse_error is null or one of the six existing PcapError codes. On parser failure
all statistic fields after parse_error are null. On success counts are bounded
exact integers (packet_count0..4096); wire_bytes/payload_bytes are recorded bytes,
not link-rate/goodput. Timestamp values are canonical unsigned decimal strings or
null for empty captures. Preserve observed first/last order, not invented minima.
Empty valid capture: zero counts, null timestamps, timestamps_ordered true.

MatchingFacts keys exactly: matched_packets, unmatched_ingress_packets,
unmatched_egress_packets, delivery_basis_points_floor. Counts are exact nonnegative
integers consistent with both SideFacts. Basis points are floor(10000*m/n), or null
when n=0. They are presentation only; never drive the criterion comparison.

Validate raw size before JSON decoding, shape/cardinality/scalars before canonical
serialization; reject duplicate fields, numeric aliases/bools, noncanonical JSON,
wrong digest and inconsistent facts/outcome/provenance/issues. Report <=32768 bytes,
Detail/list <=65536 bytes, no truncation. A decoded saved report must also be bound
to actual bundle identifiers/raw descriptors and actual verified snapshot policy.
No arbitrary report JSON accepted from HTTP. Parser PcapError alone becomes a
quality result; cancellation/deadline/I/O/programming exceptions must not become UNKNOWN.

## Explicit operation and publication

Implement one-shot public `python -m ddospector.evidence.evaluate --evidence-id UUID`
and fresh-workspace helper `make phase2-evaluate WORKSPACE=... EVIDENCE_ID=...`.
No polling daemon, auto-evaluation, new queue/claim/recovery or HTTP evaluation POST.
Validate before admission; use exclusive nonblocking flock on the existing private
DB socket directory inode, compatible with the current selected Run worker lock.
Reuse existing guarded connection/operation lifetime and five-second deadline,
including parser checkpoints and before publishing. Retire actual work/connection
before releasing ownership; no pool/retry or background task left by normal exit.

Append one immutable canonical report row using existing reports table/body/SHA
limits; do not change DDL/migration. Existing valid report is returned as already
analyzed without new computation/write. Invalid existing report is refused, never
overwritten or repaired. Atomic INSERT; no full metadata/Run update. Report's DB
SHA covers complete stored bytes, separately from its internal record digest.

Extend GET/list/by-request/raw paths to coexist with reports. Original stored
Summary remains REGISTERED and byte-identical; public analysis_state is derived
ANALYZED only from a validated retained report. List never fetches captured PCAP
blobs. It may read at most16 derived report bodies, each at most32768 bytes, to
validate hash/closed schema and metadata binding before projecting compact summaries.
Validate each and discard decoded report objects instead of including them in the
list response. Invalid reports still make list/detail/raw refuse, preserving the
existing stored-{} regression. Full snapshot-policy binding is required on selected
reads; list validation does not claim capture rehashing or new evaluation. Public
Detail.report is the validated Report object (not a free-form wrapper), or null.
Selected reads validate report digest/schema/binding before publishing. Raw downloads
remain original bytes, not report contents. Report presence does not mean criterion
satisfaction; UI must later label it as a retained result, not defense success.

## Required verification

TDD pure multiset/threshold/unknown/unsupported/parser-error/deadline cases and
closed codec boundaries; actual separate evaluator process against owned PG for
three reference outcomes plus replay/no rewrite, exact source/Run preservation,
selected/list/download behavior, malformed report/binding refusal, and explicit
helper wiring. Retain original339+1 storage case coverage; its old 'any report is
corrupt' probe must become 'invalid report is corrupt', preserving actual fault,
exact refusal and immutability checks. Only the deliberate temporary P2-01 report
placeholder semantics change, not generic assertions or warning filters.

Use normal owned PG fixture/networknone/privateUDS/cached image; no DB/worker
outage/restart/kill fault campaign. Parent does final API/Web/corpus refresh,
independent review and local commit. Final real Evidence UI/EN-KO export/open
acceptance is recorded separately in [PHASE2_ACCEPTANCE.md](PHASE2_ACCEPTANCE.md).
No shared skill edits; lessons stay project-local.

## P2-02 operator notes

The one-shot command emits canonical JSON with schema_version=1, status ANALYZED
or ALREADY_ANALYZED, and the exact retained Report. Exit 0 means the selected
operation and actual connection retirement completed, not that its criterion
was satisfied. Admission/configuration refusal exits 78; an admitted failure
exits 75. There is no HTTP Evaluate POST or automatic retry.

Use `make phase2-evaluate WORKSPACE=/absolute/owned-workspace EVIDENCE_ID=UUID`
while the original retained-workspace supervisor is RUNNING. The wrapper borrows
existing activity custody, checks the original PostgreSQL receipt and launches
`python -m ddospector.evidence.evaluate --evidence-id UUID`. It neither migrates
nor starts a stopped workspace. Ordinary explicit open retains its old semantics.

`make test-phase2-evaluation` includes the unchanged storage gate selections and
one new owned PostgreSQL evaluation case, with no deferred W2 collection. New
pure tests cover multiset conservation, codec closure and operation retirement.
Raw responses and process/DB receipts are retained by the existing test harness.

Project-local lesson: route the Runs fixture's output-only tmp_path override
before admission, use a fresh global basetemp per run, and set junit_family=legacy
when record_property is collected. A caller cancellation must await actual
Operation retirement before releasing the common socket-directory flock.

Browser, EN/KO export and retained TCP/open workflow passed P2-03 on 2026-10-17
(KST). Phase 2 is accepted only for its synthetic FILES ONLY scope; the evaluator
still evaluates only the frozen partial capture criterion, not DUT effectiveness.
