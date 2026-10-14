# Phase 2 — one evidence-backed OFFLINE criterion

## Approved objective and exclusions

The user approved the next goal and requested that PCAP inputs be generated.
Deliver one supervised path: generate synthetic paired captures → register and
retain evidence against a completed Phase-1 Run → explicitly evaluate one TCP
forwarding criterion → show facts, criterion outcome and an EN/KO report.

Generate FILES ONLY. Do not transmit/replay packets, connect a DUT, run a capture
interface, enable LIVE/MCP/AI, resume W2, or add automatic recovery/multiworkers.
Preserve Phase-1 workspaces, original Run snapshots/results and historical evidence.
A new evidence/evaluation object must not overwrite a Run's preparation result.

## Meaning of a result

The first criterion concerns matching TCP packet records between ingress/egress,
not TCP session success, application availability, attack detection or overall DUT
security. Scope is unfragmented Ethernet/IPv4/TCP without NAT or reassembly.

Three deterministic generated pairs exercise the SAME criterion:

- `complete`: all ingress records have matching egress records; complete synthetic
  recordset, criterion satisfied at 95–100%.
- `violation`: a known complete synthetic egress recordset deliberately omits some
  records; criterion violated at 95–100%. This is generated ground truth, not a
  measured DUT failure.
- `unknown`: matching gaps with explicitly unknown capture coverage; UNKNOWN,
  never a successful block/defense result.

Synthetic identity is recognized from BOTH original byte digests against the
built-in generator, not from filenames or a caller-supplied label. Other uploads
are UNVERIFIED and cannot establish complete capture coverage. Observed matching
counts remain useful, but uncertain coverage, unsupported data or no ingress
records yields UNKNOWN. `defense_verdict` stays null. No latency is inferred from
unsynchronized capture timestamps. Never use fixture expected outcomes as the
analyzer's answer: parse actual bytes and compute multiset correspondence.

## P2-00 frozen generator/parser interface

New package `src/aiddos/evidence/`, public CLI wrapper under
`src/ddospector/evidence/`; no existing application integration in this slice.

`pcap.py`:

- `MAX_CAPTURE_BYTES = 1_048_576`, `MAX_PACKETS = 4096`,
  `MAX_FRAME_BYTES = 65535`; exact limits inclusive, excess is a hard error.
- `PcapError(ValueError)` exposes a stable `code` from
  `PCAP_TOO_LARGE`, `PCAP_TOO_MANY_PACKETS`, `PCAP_MALFORMED`,
  `PCAP_UNSUPPORTED`, `PCAP_TRUNCATED`, `PCAP_CHECKSUM_UNVERIFIED`.
- `parse_capture(stream, *, check=None)` borrows a forward-only binary reader;
  never closes it, never seeks, handles short reads, and only issues positive
  bounded reads. Optional `check()` is called during work; its exceptions propagate
  unchanged rather than becoming a data-quality result.
- Return an immutable `Capture` with `size_bytes`, `sha256`, `packet_count`,
  `wire_bytes`, `payload_bytes`, `first_timestamp_ns`, `last_timestamp_ns`,
  `timestamps_ordered`, and sorted immutable `fingerprints` tuples `(hex_digest,count)`.
  Timestamp integers are internal; later public JSON uses decimal strings.
- Support classic PCAP 2.4, both byte orders and micro/nanosecond timestamps,
  link-layer field exactly Ethernet without additional flags. Ignore the two
  historical unused global fields. PCAPNG/other link types are unsupported.
- Require complete packet framing; captured length must not exceed snaplen or
  original length. A complete snaplen-truncated record is PCAP_TRUNCATED; an
  incomplete record body is PCAP_MALFORMED. Validate finite timestamp fractions.
- Support Ethernet IPv4/TCP only, IPv4 IHL 5, TCP data offset 5, no IP fragments,
  complete IP total length within the captured frame and verified IP/TCP checksums.
  Unsupported records never disappear silently into a partial success.
- Packet identity is SHA256 of IPv4 source+destination and the exact TCP segment
  bounded by IP total length. Exclude Ethernet headers/padding and IPv4 fields
  that legitimately change during forwarding (e.g. TTL/header checksum).
  Preserve duplicate multiplicity; this is not unique-set matching.
- No payload bytes in public projections. Raw original bytes are separately retained.

`samples.py`:

- `SAMPLE_IDS = ("complete", "violation", "unknown")`.
- Immutable `SamplePair` fields: `sample_id`, `coverage`, `ingress`, `egress`.
  Coverage is `COMPLETE_SYNTHETIC` or `UNKNOWN`; source is always synthetic.
- `make_sample(sample_id)` returns deterministic original bytes. Use documentation
  IPs, fixed explicitly synthetic timestamps, valid checksum-bearing TCP data
  segments and differing ingress/egress MAC/TTL. No real socket/session is created.
- `recognize_pair(ingress_sha256, egress_sha256)` returns the matching SamplePair
  or None by exact digest pair; do not trust caller declarations or cache mutable
  objects that callers can poison.
- CLI: `python -m ddospector.evidence.samples --output /absolute/new-directory`.
  Create six PCAPs plus manifest.json, refuse an existing destination before any
  writes, use private permissions, never overwrite/delete caller files.
  Manifest includes filenames, exact bytes/digests/packet counts, synthetic source,
  coverage and clearly labeled fixture expectations at 9500–10000 basis points.
- No runtime dependency addition. Tests may use already-installed tcpdump/tshark
  ONLY with name resolution disabled and `-r` on owned generated files.

Independent format references (facts, not copied implementation):
`https://raw.githubusercontent.com/the-tcpdump-group/libpcap/master/pcap-savefile.manfile.in`,
`https://www.rfc-editor.org/rfc/rfc791`,
`https://www.rfc-editor.org/rfc/rfc9293.html`.

## Remaining slices — detailed transport schema before integration

| Slice | Deliverable | Status |
|---|---|---|
| P2-00 | Real synthetic PCAP files, bounded parser and independent offline-reader checks | In progress |
| P2-01 | Immutable paired evidence registration, original download, bounded metadata and Run linkage | Pending |
| P2-02 | Explicit single evaluator, deterministic criterion, immutable derived report | Pending |
| P2-03 | Existing Evidence UI integration, EN/KO JSON/HTML report, real browser workflow | Pending |

Use the existing private PostgreSQL, not a SQLite fallback. Plan a separate
`ddospector_evidence_v1` namespace with explicit versioned migration so original
`aiddos_runs_v1` readiness and Run data remain unchanged. Cap retained pairs at 16,
one MiB per side, metadata/report sizes and list cardinality explicitly. Raw
PCAPs and metadata must commit atomically; failed admission must not consume a
bundle. Replays of an identical request identity must not create another bundle.
No silent migration of existing operator workspaces on ordinary open.

Before P2-01, freeze the exact HTTP/body/error/DB/CLI contracts against actual
existing boundaries. Before P2-02, freeze the closed report schema and cross-
multiplication threshold comparison (do not decide from rounded percentages).
Bound all binary parsing, acquisition, retention, publication and UI/export work.
Refuse or surface corruption/unavailability; never fabricate an empty history.

## Working discipline

Small TDD → relevant verification → independent scoped review → local commit
slices. Canonical phase-specific tests must collect new tests without replaying
deferred W2. Preserve RED/setup failures separately; no skip/xfail, weaker
assertions or silent allowance resets. Do not change shared skills; record task
lessons locally. Final acceptance needs the real owned PostgreSQL/API/explicit
worker/Chromium path with generated samples, raw-byte retention, immutable Run
proof, all three outcome controls, export and ordinary reopen. Synthetic workflow
acceptance is not real DUT acceptance.
