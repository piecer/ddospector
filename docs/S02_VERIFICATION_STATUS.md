# S02 verification status

## Current checkpoint

Snapshot/request error normalization, compiler result-limit classification and
`make worker` have been applied while preserving the DDoSpector startup aliases.
At the user's request, these latest product changes have **not been retested**.
The preceding source passed all 1215 API tests within the approved 600-second
outer limit (448.4 seconds), and separately passed 79 pre-DB/query tests. Those
results do not verify the latest product changes. UI/geometry work remains
deferred and full S02 is **not accepted**.

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

## Acceptance rows

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
owned-process retirement records are preserved. No full API retry is authorized
by this result, and the full API gate remains open.

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
focus behavior and the observer need bounded correction before UI acceptance.

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
and full UI admissions require an explicit bounded continuation decision.

| ID | Current status | Remaining scope / evidence qualification |
|---|---|---|
| A01 | PARTIAL | Legacy/S01 preservation and isolated naming checks retained; full current canonical API/combined validation is not closed. |
| A02 | PARTIAL | Normal real browser create/PG readback exists; fresh normal-path continuation pending, complete restart witness not accepted. |
| A03 | OPEN | Capture timing/source lifetime/late admission and final source-bound integration obligations remain. |
| A04 | PARTIAL | Confirmed POST HTTP-response loss and GET-only reload verified earlier; all404/COMMIT and8192-byte unavailable-source combinations remain. |
| A05 | BLOCKED_W2 | Actual concurrent worker claims and pre-claim SQL abort/ambiguous-claim obligations are within blocked backend work. |
| A06 | BLOCKED_W2 | Live successor-generation fencing not accepted; old terminal-only stale-owner witness insufficient. |
| A07 | PARTIAL_BLOCKED_W2 | Queued cancel verified; running/terminal/deadline arbitration matrix not accepted. |
| A08 | BLOCKED_W2 | Terminal restart immutability and complete atomic failure matrix not accepted. |
| A09 | BLOCKED_W2 | DB outage and SQLSTATE abort/disposal/reconnect obligations not accepted. |
| A10 | BLOCKED_W2 | Retry exhaustion/watchdog/real300s expiry/exact connection-disposal evidence not fully accepted. |
| A11 | PARTIAL | Prior admission/quota/custody evidence retained, no full latest-source integrated acceptance. |
| A12 | PARTIAL | Strict producer/consumer negative coverage retained; full latest-source stage gate remains. |
| A13 | PARTIAL_BLOCKED_W2 | Pagination source evidence retained; outage/readback no-cache combinations still open. |
| A14 | PARTIAL_BLOCKED_W2 | Ordinary manifest success verified; malformed snapshot classification IR-01 remains unaccepted. |
| A15 | BLOCKED_W2 | Complete driver/cleanup/DDL/integrity outcome matrix not accepted. |
| A16 | PARTIAL_FINAL_PRODUCER_OPEN | 5259 frozen Node/Chromium entries checked, not a newly regenerated final-source producer corpus. |
| A17 | PARTIAL | Client corrections and unit matrices retained; every required real-browser storage/receipt/selection combination not closed. |
| A18 | PARTIAL_BLOCKED_W2 | Normal unmocked UI→HTTP→PG→worker path verified; combined faults/outage/recovery matrix not accepted. |
| A19 | HOLD_CONFIRMED_FOCUS_AND_ORACLE | Independent review confirms focus RED and a separate static scroll-reachability oracle flaw.0 rows passed,1 failed,5 not reached; Agent/Campaign/final PG comparison not reached. No correction/retry yet admitted. |
| A20 | OPEN | Five verification-only files independently accepted/integrated; scoped combined construction13/tooling31/make lint/build passed. Full API timed out at180s with1097/1215 complete. Full four-make, final exactcommit and active deployment remain. |

## Non-waived limits

The previously provider-blocked W2 workload is not retried, rephrased or reassigned by this continuation. Generic API-test/lint repairs and the bounded normal UI checks are separate work, not backend fault acceptance. No service restart, foreign-resource access, automatic source-data recovery or deployment is performed.

The original full API attempt reached its 180-second outer deadline without a final pytest result. Its separate route-count failure and JUnit observer incompatibility were reproduced on the pre-rename baseline; neither explains the entire timeout. The new bounded canonical API attempt retains the same 180-second ceiling and does not weaken or skip the quota test.

No final S02 completion commit or S03 advancement is justified until every required row, independent acceptance and active/exact gates pass. Local source-bound reports, original failures and current assignments are recorded in `.hermes/artifacts/campaign-01/S02/verification-resume/`.
