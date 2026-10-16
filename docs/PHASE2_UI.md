# Phase 2 Evidence UI — accepted implementation / acceptance matrix

Historical isolated candidate base: `f8a8a9b1d263299260092e9905ce447c81db84ab`.
That worktree did not integrate the then-pending P2-02 backend. P2-02 is now
committed at `546b82ca1285b5fd5d644f730ff9b90f51626c7c`; the independently accepted
Evidence UI is integrated onto that backend without importing the old Python or
normal-wire fixtures. The existing current producer guard remains unchanged.

## Feature and acceptance matrix (recorded before implementation)

| Slice | Contract / required verification |
| --- | --- |
| Producer codec | Exact retained producer API bytes, closed shapes, lexical integers/duplicate rejection, digest, provenance, counters, threshold outcome, snapshot binding; mutated negatives explicitly identified |
| File admission | Two explicit roles; 1..65536 bytes before reads; exact codepoint/UTF-8/control/bidi name rules; no normalization |
| Transport | Streaming bounds before decode, deadlines/abort, no redirects, single flight; list/detail/raw 65536; distinguish empty/unavailable/corrupt |
| Submission | One UUID and captured binding; double-click/stale read/unmount refusal; uncertain acknowledgement retains identity; GET-only resolution, 404 not final absence |
| Runs/repository | Existing strict Run API; only completed OFFLINE Runs; no worker launch; all 16 bundles reachable; selected full IDs/names/hashes |
| Polling | Selected REGISTERED: non-overlapping GET after completion, 2 seconds, at most 60 seconds; terminal/hidden/unmount/selection-change/stop retirement; manual refresh; visible errors/stale labeling |
| Samples | Actual unchanged generator produces six PCAPs and manifest; static versioned assets, pinned SHA/size, bounded local loads; explicit populate/download, never auto-POST; expectations are not results |
| Reports | One criterion SATISFIED/VIOLATED/UNKNOWN; observed counts and snapshot thresholds; always provenance/coverage/NOT_EVALUATED/no DUT/session/service claims; producer-start time and unassessed requirements |
| Exports | Client-only validated Detail: canonical JSON <=65536; escaped script-free CSP HTML EN/KO <=131072; same facts, bounded rows/cells, URL retirement |
| UX | Existing DDoSpector theme/components; EN/KO actions/form/errors/status/report; keyboard accessible full identifiers; 900px and narrow reflow |
| Gates | Focused RED/GREEN slices; complete Web unit tests, ESLint, TypeScript/build, whitespace including new files; fixture-browser checks labeled controlled transport |

## Trust and presentation

The entire Run remains OFFLINE preparation. Capture recordset correspondence is
not defense PASS, replay-asset identity, traffic-budget, endpoint/session/service
compliance or AI interpretation. UNKNOWN is inconclusive, never block success.
`Report.created_at` is producer start time, not capture or completion time.
A registered bundle without a validated report is unassessed.

Evaluation is deliberately manual outside the UI:

```sh
make phase2-evaluate WORKSPACE=/your/workspace EVIDENCE_ID=<id>
```

`/your/workspace` is a placeholder for the operator's explicitly owned workspace.
There is no HTTP evaluate route/button, automatic worker, POST retry or progress
simulation. GET polling observes retained publication only.

## Verification status

The production Evidence page, closed codec, bounded client, controller, generated
assets and client-side EN/KO exports have independent frontend acceptance. The
original implementation receipts remain under `.hermes/artifacts/phase2/ui-author/`.
The frozen 43-path candidate is `ui-repair/round2-20261015-69c38dcf82/repaired-candidate.json`;
independent closure is `ui-repair-review/review-47b45a0bcb/{report.md,verdict.json}`
under `.hermes/artifacts/phase2/`, adopted in `ui-closure-parent-adoption.json`.
B1 publication coherence and B2 acquired-response retirement are CLOSED. Round-2
corrected an impossible cross-repository mock binding, preserving original
assertions and producer bytes; it is a legitimate fixture correction, not a
weakened product guard. Independent Web verification passed 2157 tests. The
automatic UI repair allowance remains exhausted at 2/2; integration adds no repair.
Fresh combined integration receipts are under `.hermes/artifacts/phase2/ui-integration/`;
their actual results, not this status note, determine commit readiness.

The JSON export is canonical `{schema_version:1,detail,offline_run}`: both nested
records are revalidated, including exact source snapshot binding, before export.
It is locale-neutral so EN/KO JSON bytes agree. HTML localizes labels/warnings and
includes full original descriptors, retained Report, and source declared limits;
all dynamic text is escaped. Both exports retain unassessed/null facts and never
include raw PCAP payloads or operational workspace paths.

Pending submission receipts are bounded to 4096 bytes of tab session storage;
only request/Run/snapshot IDs and original names/sizes/hashes are stored. No raw
capture/base64 is persisted. Storage errors lock admission. For safety, a failed
POST remains GET-only unresolved, including when a later lookup returns 404;
there is no UI action that silently replaces this identity. Explicit successful
binding and source validation are required before receipt retirement.

Controlled Chromium QA runs the shipped shell, page, controller and transports
against declared HTTP fixtures on an invocation-owned ephemeral Vite listener
with no API proxy. It checks automatic terminal publication on the same route,
900px/390px EN/KO geometry, all 16 choices, keyboard focus, exports and URL cleanup.
Its exact producer response decoder corpus is shared with Node where feasible.
API selection/list scheduling projections are disclosed in the fixture README.
No controlled-route result claims a live backend integration.

Independent frontend review is complete. Actual P2-03 browser → API → PostgreSQL →
explicit CLI evaluator → exports → ordinary-open acceptance passed on 2026-10-17
(KST), using the integrated `e7335f4` product revision. Three retained outcomes,
EN/KO exports, original-byte downloads and normal stop/open/stop were verified.
See [PHASE2_ACCEPTANCE.md](PHASE2_ACCEPTANCE.md) for source-bound receipts and limits.
The ten positive Evidence corpus responses remain historical actual-producer
fixtures with their original provenance, not fresh current-backend executions.
N1 conservative failed-POST pending behavior is unchanged and nonblocking: no
automatic POST retry, implicit receipt clearing, or final-absence claim from 404.
No claim here waives existing source-bound normal-wire guards or old campaign
correction limits.

## Local implementation lessons

- Bind an uncertain submission to independently captured descriptors before POST,
  and persist only that bounded receipt; a later 404 cannot prove final absence.
- Keep producer start time distinct from registration, capture and completion.
- Repeat no-defense/no-service/no-session warnings next to the selected outcome,
  not only above a long repository page.
- Use a short invocation-owned scratch TMPDIR for Chromium's Unix-domain singleton
  socket. A long artifact path can prevent launch before any product assertion;
  retain that setup failure and verify owned process retirement before retrying.
