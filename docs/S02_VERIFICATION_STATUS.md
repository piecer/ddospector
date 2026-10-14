# S02 verification status

The original full S02 remains **unaccepted/deferred**. The separately approved
supervised single-run OFFLINE Phase 1 is complete; see `PHASE1_ACCEPTANCE.md` and
`PHASE1_LOCAL.md`. The checkpoint evidence below predates that scope change and
is preserved as historical S02 evidence, not the current Phase-1 acceptance list.

## Current checkpoint

Full S02 is **not accepted**, but the known error-classification, retry-focus,
scroll-oracle and dedicated-test-discovery corrections are committed:

- `672cc8c`: snapshot/request error normalization, distinct compiler result-limit
  failure and `make worker`, preserving DDoSpector startup compatibility.
- `5f54508`: focus-preserving read retry, bounded keyboard/clip verification,
  dedicated browser-test routing and pure offline-failure regression tests.
- `9d71adc`: 720 validated synthetic manifest variants covering legal categorical
  policy, profile/asset, resource-stop and evidence-subset combinations.

Scoped verification passed: API1215 (446.79 seconds within600), Web2025/55 files,
tooling31, pure/boundary98, Python/Web lint, typecheck and production UI build.
The real private-PG/API/separate-worker/browser normal path and independent
PG/HTTP snapshot/result comparison passed, including EN/KO at1440/1024/390px
and Agent/Campaign execution locks. The dedicated browser suite passed21 cases;
the default E2E collection retains89 cases (collection is not full execution).
After the test-routing-only correction, earlier API/PG evidence was reused with
explicit user approval and unchanged product bytes.

The later manifest-only slice passed720 new cases plus19 existing cases and
canonical Python Ruff; it did not rerun API/UI or DB suites. Expected manifest
bytes/digests use a standard-library test oracle. This verifies repeat pure
calls, not real worker retries, actual asset ingestion or fresh producer parity.
Both code/test slices received scoped independent source review. The existing
500kB bundle warning remains; no active product-service rollout was performed.

Remaining work is the blocked W2 worker/DB fault-and-recovery obligations,
expanded state/source/maximum-content combinations, final producer matrices,
complete canonical gates and active/exact stage acceptance. Incremental commits
do not close those obligations or authorize exhausted execution allowances.

The sections below retain the earlier verification snapshots and their original
limitations; they are not current execution permissions or final-source passes.
Their baseline is `7e2549e99f2c59f064f720920d4feec8d4e973d4`, with the frozen
acceptance matrix in `stages/S02_RUNS.md` (§10). The original contract and
historical receipts remain unchanged. Namespace compatibility is documented in
`NAMING.md`.

## Historical verification work

- Correct the stale API construction-route assertion using the exact frozen method/path inventory, preserving the native reentrancy checks.
- Correct the two existing Ruff-failing probe files without changing their function behavior or executing the blocked backend probes.
- Include `tests/tooling` in `make test` and `make lint`; `make test-tooling` runs it independently. Keep `tests/runs` mandatory in the complete `make test` target; no gate was dropped to obtain green.
- Verify both locales at 1440/1024/390px through the existing normal Runs browser path. Naming-only overview screenshots do not satisfy Runs acceptance.

The first tooling target used the console pytest entry point and failed collection because the root `tools` namespace was not on its import path. The target now uses `uv run --frozen python -m pytest tests/tooling -q`; the actual target passed 31 cases. Original missing-target/coverage failures and the collection error are retained, not relabeled as product passes.

## Historical adjudication

### Received API/Ruff candidate

The isolated candidate now passes all 13 construction tests and the Python Ruff
selection, including `tests/tooling`. Its three-file delta replaces the stale
route count with exact ordered method/path inventories and fixes only helper
formatting/imports. The independent read-only review accepted these changes and
the two canonical-tooling files. The three candidate changes are now integrated;
fresh combined checks remain separate from that source/evidence acceptance.

The single permitted full API run collected 1215 cases and completed 1097 with
passed setup/call/teardown before the 180-second outer deadline. One case was in
flight and 117 had not started. The quota/pagination case began at observer
elapsed time 174.415 seconds; this is not evidence that it hung for 180 seconds
or caused the whole-suite delay. The uv exit was 143 and the supervisor rejected
the run; pytest's individual exit was not observed. The original receipts and
owned-process retirement records are preserved. That result did not authorize a
retry. Later separately approved600-second runs passed; the old timeout is not
a current full-API failure.

### Received normal-path UI result

The one permitted real UI/API/PG/worker invocation failed the new EN/1440px
keyboard check: `Retry run read` issued the expected GET, received the exact
terminal response, and became enabled again, but was no longer focused. The
saved matcher repeatedly resolved the actual button. Disabling that button while
reading is a source-backed cause hypothesis, not an independently reproduced
root-cause fix. Independent review accepted the actual focus failure as
`UI-FOCUS-01`, rather than a selector-only or invented-contract failure.

The same review found `UI-ORACLE-02`: the new geometry observer can confuse
offscreen text inside a keyboard-scrollable container with inaccessible clipping.
That observer was not reached in the failed run; this is not a demonstrated
product clipping defect and does not justify changing product CSS. Both the
focus behavior and the observer required correction at that checkpoint. The
corrections and subsequent scoped passes are summarized above.

The A19 matrix is 0 passed / 1 failed / 5 not reached. Agent/Campaign lock checks
and the helper's final independent PostgreSQL byte comparison were not reached.
The separate frozen Chromium parity case passed all 5259 entries in that same
invocation; it does not replace the failed UI case or final-producer acceptance.
The test-only candidate is retained, not integrated. No runtime retry or product
correction has been admitted. Parent readback confirms the recorded processes and
exact owned PG container/volume are absent; this is cleanup evidence, not a
behavioral pass.

The accepted API/tooling corrections were checked together in an exact private
snapshot: construction13, tooling31, canonical `make lint` and `make build`
passed. The build's existing 500kB chunk warning remains. These receipts precede
this documentation-only adjudication update; application/test code is unchanged.
They do not replace the incomplete full API or failed UI gates. Further full API
and full UI admissions required an explicit bounded continuation decision at
that historical checkpoint. These paragraphs preserve the original failures,
not the current permission or acceptance state.

## Current acceptance rows

| ID | Current status | Remaining scope / evidence qualification |
|---|---|---|
| A01 | PARTIAL | API1215 and scoped legacy/S01 checks passed; whole-stage preservation/combined acceptance remains separate. |
| A02 | PARTIAL | Fresh normal browser/private-PG/worker and exact PG/HTTP readback passed; complete restart witness not accepted. |
| A03 | OPEN | Capture timing/source lifetime/late admission and final source-bound integration obligations remain. |
| A04 | PARTIAL | Confirmed POST HTTP-response loss and GET-only reload verified earlier; all404/COMMIT and8192-byte unavailable-source combinations remain. |
| A05 | BLOCKED_W2 | Actual concurrent worker claims and pre-claim SQL abort/ambiguous-claim obligations are within blocked backend work. |
| A06 | BLOCKED_W2 | The original terminal-only witness gap was resolved for the saved source version; current complete restart/fencing acceptance remains open. |
| A07 | PARTIAL_BLOCKED_W2 | Queued cancel verified; running/terminal/deadline arbitration matrix not accepted. |
| A08 | BLOCKED_W2 | Terminal restart immutability and complete atomic failure matrix not accepted. |
| A09 | BLOCKED_W2 | DB outage and SQLSTATE abort/disposal/reconnect obligations not accepted. |
| A10 | BLOCKED_W2 | Retry exhaustion/watchdog/real300s expiry/exact connection-disposal evidence not fully accepted. |
| A11 | PARTIAL | Prior admission/quota/custody evidence retained, no full latest-source integrated acceptance. |
| A12 | PARTIAL | Pre-DB/query79 and pure offline-failure19 passed; DB-backed and whole-stage obligations remain. |
| A13 | PARTIAL_BLOCKED_W2 | Pagination source evidence retained; outage/readback no-cache combinations still open. |
| A14 | PARTIAL_BLOCKED_W2 | IR-01 correction and720 pure categorical manifest cases committed; real worker repeat attempts/final producer acceptance remain open. |
| A15 | BLOCKED_W2 | Complete driver/cleanup/DDL/integrity outcome matrix not accepted. |
| A16 | PARTIAL_FINAL_PRODUCER_OPEN | 5259 frozen Node/Chromium entries checked, not a newly regenerated final-source producer corpus. |
| A17 | PARTIAL | Client corrections and unit matrices retained; every required real-browser storage/receipt/selection combination not closed. |
| A18 | PARTIAL_BLOCKED_W2 | Normal unmocked UI→HTTP→PG→worker path verified; combined faults/outage/recovery matrix not accepted. |
| A19 | PARTIAL_NORMAL_UI_PASS | Known focus/oracle defects corrected. Six locale/viewport rows, Agent/Campaign locks and final normal PG comparison passed; complete cross-state/maximum-content coverage is not claimed. |
| A20 | OPEN | Scoped reviews, component gates and normal PG/browser acceptance passed. Full canonical/final-producer/active stage gates remain; checkpoint commits are not stage completion. |

## Non-waived limits

The previously provider-blocked W2 workload is not retried, rephrased or reassigned by this continuation. Generic API-test/lint repairs and the bounded normal UI checks are separate work, not backend fault acceptance. No service restart, foreign-resource access, automatic source-data recovery or deployment is performed.

The original180-second API failure and its distinct route-count/JUnit issues are preserved. Later approved600-second runs retained the test selection, assertions and internal deadlines; no quota test was skipped or weakened. Their success does not retrospectively explain the original timeout.

No final S02 completion commit or S03 advancement is justified until every required row, independent acceptance and active/exact gates pass. Source-bound reports and original failures are retained under `.hermes/artifacts/campaign-01/S02/verification-resume/`, `post-commit-completion/` and `manifest-variants/`. The frozen acceptance contract is unchanged.
