# Evidence frontend fixture provenance

The `.body` files are copied **byte-for-byte**, including original canonical JSON
and literal filenames, from the P2-02 producer's retained actual API responses.
They were not synthesized from expected outcomes. `origins.json` records exact
origin, byte length and SHA256; `producer-receipts.json` retains the matching HTTP
status/body hash and deduplicated producer-source commitments from its wire
manifest. P2-02 independent acceptance is still pending; copying these fixtures
is not integration or acceptance of that backend candidate.

- `complete`, `violation`, `unknown` details and registrations, `run-before` and
  `analyzed-list`: actual evaluation-author final owned-PG/API execution.
- `full-list` and `not-found`: actual registration-author execution within the
  same final artifact tree. The full-list fixture contains all 16 retained rows.
- Source locations are historical provenance, never runtime input or export paths.

`web/src/pages/evidence/corpus.test.ts` verifies retained bytes and tests explicit
mutations (shape/scalars/counts/provenance/policy/digest). Its 90% threshold case
is a declared **semantic consistency mutation**, not a producer positive witness
or actual evaluation. Metadata-only XSS tests likewise do not claim a new measured
outcome. No existing Run normal-wire fixture or freshness guard is modified.

The controlled browser fixture uses the exact selected Detail/Report/Run bytes
above and the exact 16-row list. Its empty/one-row repository envelopes and Run
selection envelope are explicitly scheduled **test projections of actual rows**,
not additional retained producer API witnesses. A fixed request UUID permits a
byte-bound fixture POST acknowledgement; no real database is contacted. Its
positive outcomes always come from actual producer Report bytes, never a sample
manifest answer or invented measurement.

## Generated static samples

`web/public/evidence-samples-v1/` contains the exact six PCAPs and manifest emitted
by the unchanged `python -m ddospector.evidence.samples --output <fresh-dir>` CLI.
The frontend catalog is a projection of that manifest's identifiers, sizes,
digests and provenance, deliberately excluding `fixture_expectation`. Tests
compare shipped assets to the actual Python generator, and the browser verifies
the manifest commitment and original file hashes before use. No external sample
URL, packet-format reimplementation, traffic generation or automatic POST exists.

## Scope of proof

Node/Vitest contract and lifecycle tests plus controlled-transport Chromium QA
are frontend evidence, not live backend or P2-03 acceptance. Real browser → API →
PostgreSQL → explicit evaluator → retained export → ordinary workspace reopen,
independent review and integration remain the parent's later gate.
