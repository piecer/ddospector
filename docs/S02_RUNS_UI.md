# S02 Runs UI — manual-review checkpoint, integration HOLD

The F1/F2/F3 client corrections and E1 Node evidence received scoped acceptance
after independent source review and successful Web tests/lint/typecheck/build.
Backend and real-browser integration are deferred for this user-requested
checkpoint, not marked passed. See `S02_REVIEW_CHECKPOINT.md`.

This is the production `/runs` route, not a demo. `operations/RunsPage.tsx`
exports the new Runs workspace. Existing components, scenario validators,
styles and dependencies remain the foundation. No backend, dependency or
shared configuration change belongs to this delta.

## Operator behavior

- Select a saved historical scenario/version and `offline_manifest_v1`.
  Start requires a verified source and healthy independent Runs read.
- LIVE stays disabled. Preparation creates no traffic, device connection,
  evidence ingestion or defense verdict. A successful manifest is explicitly
  `NOT_EVALUATED`; measurements and verdict remain null.
- Run history is bounded keyset pagination. Detail and ordered events expose
  captured IDs/digests, source revision, timestamps, attempts and generations.
  Full verified JSON and captured scenario details remain inspectable.
- A single app-lifetime pending request survives route navigation. Only
  `aiddos.s02.pending.v1` is used, with a canonical 2048-byte receipt.
  Initial POST acknowledgement cannot clear it; one exact-identity GET follows.
  Reload is GET-only. Explicit identical-key replay is separate from storage
  recheck. Storage failures never permit replacement of an unresolved identity.
- Ordinary history observation does not manufacture original submission intent.
  It retains one full Detail, immutable identity and terminal checkpoint.
  Unrelated pending A cannot be adopted/cleared by viewed B. Cancel requires
  verified non-stale nonterminal Detail; failure requires a fresh explicit GET.
- Polls have one outstanding request, at least one second between completions
  and subsequent polls, and a 300-second view budget. Each HTTP operation has
  its own 10-second deadline. Navigation does not cancel server work.
- Errors mean unavailable/stale, never empty success. Source failures and run
  store failures are separate. Failed/SNAPSHOT_INVALID summaries remain usable
  without weakening Detail integrity validation.

## Strict boundaries

`raw.ts`, `object.ts`, `wire.ts`, `pages.ts`, `grammar.ts` and `client.ts` enforce
raw UTF-8/token ceilings, recursively closed shapes, UUID/time/numeric bounds,
finite reachable state/counter transitions and deterministic Snapshot/Result
integrity. Direct objects reject getters, hidden/symbol properties, prototypes
and sparse arrays before copying. Byte accounting rejects cumulative excess
before canonical-copy allocation. `receipt.ts`, `storage.ts`, `checkpoint.ts`,
`observer.ts` and `controller.ts` keep recovery intent separate from observation.

## Verification material and invocation

Frozen H1 input `tests/fixtures/runs/h1/selected-index.json` has 1096 entries including
legacy, repeated and seeded responses: it is NOT 1096 independent acceptance
cases or a worker proof. New tests hash-check original files. The differential
manifest under `tests/fixtures/runs/parity/` preserves real source/provenance and labels
mutation negatives. These exact-byte fixtures are now committed with the source,
so ordinary Web tests do not require the private campaign directories. Historical
Node/Chromium evidence remains separately scoped; current checkpoint verification
does not run Chromium or generate new backend responses.

Canonical Web commands are `npm test`, `npm run lint`, `npm run typecheck` and
`npm run build`, always invoked with the assigned absolute prefix and distinct
owned npm user/global config plus owned cache. `next-evidence/native/` records
argv, literal environment, source snapshots, actual exit, timeout latch,
descendant ownership and reaped/closed/absent receipts for each invocation.

`tools/s02_web_probe.py CONFIG [full|scoped]` is an owned-resource verifier:
- CONFIG supplies this repository root, assigned runtime and literal environment.
- default `full` selects actual browser-create/recovery/cancel/worker plus parity.
- explicit `scoped` selects actual ephemeral-Origin denial, unrelated ordinary
  B observation, native-API-created B processed by a separate worker, and parity.
  It is NOT replacement acceptance for the full browser-create scenario.
- API and UI normally bind free loopback ports. The immutable Vite proxy uses
  `VITE_API_PROXY_TARGET`, asserted before launch, with own endpoint preflight.
- A parent-authorized `authorized_web_port` may be supplied only after resource
  permission/ownership adjudication; it is not permission to use an existing
  service. 5173 and 5180 are always refused by this verifier.
- PG uses only the protected I0 harness, exact cached image, fresh anonymous
  volume and private Unix socket. Children retire before PG disposal. Final
  independent PG readback compares this run's captured input/result with HTTP.

## Open acceptance and preserved incidents

**Browser POST admission is HOLD:** the protected development boundary accepts
only Origin ports 5173/5175/5180/5182, not a randomly assigned test UI port.
The real full browser-create test failed honestly with ORIGIN_NOT_ALLOWED.
No boundary patch or Origin spoof was used. Parent disposition is needed for an
owned allowed test port or separately authorized configuration change.

An earlier verifier typo used `AEGIS_API_PROXY_TARGET` instead of the existing
`VITE_API_PROXY_TARGET`; that browser attempt made forbidden GET-only contact
with default 5180 and failed before its first POST. It is retained as a verifier
scope violation, not a clean execution or zero-foreign-access proof. See
`next-evidence/active-port-read-incident.json`. Subsequent invocations use the
correct explicit proxy and recorded environment.

Final W2 corrected-source producer parity, combined corruption/lost-ACK/large-
source/outage cases, complete A16–A19 adjudication, full integrated I3 review and
parent full/exact/active gates remain open. W2's interruption must not be worked
around by this role. The scoped browser/worker proof does not close these gates.
See `next-evidence/report.json`, case matrix, original failures and final receipts.
Historical `next-evidence/` paths above refer to retained local campaign evidence,
not files shipped as a runnable browser harness. This checkpoint is committed for
manual review only; no naming change, active deployment or full S02 acceptance is claimed.
