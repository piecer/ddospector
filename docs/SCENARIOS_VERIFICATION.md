# S01 implementation verification

## Implemented scope

S01 adds versioned scenario definitions, not an execution engine. The API and English/Korean Traffic profiles UI create definitions, append immutable versions, inspect history, bind acknowledgements to the submitted revision/definition and retain uncertain drafts without replaying writes. Declared PCAP identity is metadata; no upload, inference, MCP connection, device action or packet transmission is enabled.

The scenario registry is independent of the legacy draft store. Storage uses bounded failed-candidate retention, write quarantine and explicit offline recovery, including verified fresh CLEAN restart and explicitly reviewed acceptance of the current valid registry. Operational commands and limits are in `SCENARIO_STORAGE_RECOVERY.md`; normative behavior is in `stages/S01_SCENARIOS.md` and `stages/S01_RETENTION_RECOVERY.md`.

## Source-bound implementation acceptance — 2026-10-10

The reviewed implementation is based on `80f7da4c9a3d09702f165e40c824de46823b1e76`. The final peer-fence source SHA256 is `00ac210f4459e0c6d5c6f17584d2f835242e45a75884368110af24bb79bf62cc` (`src/aiddos/api/scenario_store.py`); the canonical peer regression source SHA256 is `e972e525a2234558310c6ab12a9bdced86fe46cf58e57512d1ed727f6e592704`.

| Gate | Observed result | Provenance |
|---|---|---|
| `make test` | 1160 API and 319 UI tests passed | Fresh parent integrated execution; actual command and supervisor exit 0 |
| `make lint` | Ruff, ESLint and TypeScript passed | Fresh parent integrated execution |
| `make build` | Production UI build passed | Fresh parent integrated execution; existing large-chunk advisory remains non-blocking |
| `make test-e2e` | 86 Chromium cases passed; no failed, skipped or flaky cases | Fresh parent execution after independent review |
| Original backend reviewer probes | 43 passed | Fresh independent execution, unchanged probes |
| Focused storage/ownership/retention/recovery/peer suite | 309 passed, including 16 persistent peer regressions | Fresh independent execution |
| Additional independent coordinator probes | 6 passed | Fresh independent execution |
| Correction matrix | 6/6 rows passed | Independent review `deleg_f50e0d17` |
| Complete retention/recovery matrix | 22/22 rows passed | Same independent review, with explicit current-parent inheritance for full-suite cases |
| Browser failure → quarantine → offline CLI → fresh API | 8 cases passed | Fresh parent Chromium/HTTP/CLI; POST/PUT × both storage error codes × EN/KO |
| Explicit accept-current | 3 cases passed | Real CLI/API with owned torn/missing material and explicit empty-state confirmation |

The 358 independently executed cases overlap the canonical suites; they are not added to the API total. Receipt/hash reconciliation is not another execution. The final documentation-only release snapshot must run fresh canonical gates before committing; exact-commit and active-service checks are recorded separately in the campaign receipt.

## Failure and ownership coverage

- Exposed publication-source unlink/recreate and replacement after the last observation preserve caller material. Initial metadata failure retains the bounded candidate without losing the original exception or retrying a reused descriptor close.
- Storage errors preserve valid history, deny additional writes and keep browser drafts read-only across close, GET retry, discard/reopen and pagination. Reloading the page does not bypass the server's quarantine.
- The recovery CLI checks exact current state, receipt, entry types/counts/bytes and archive decisions. It does not delete caller replacements, replay candidates, roll back the current registry or overwrite an existing archive.
- Interrupted recovery resumes only its matching intact plan. Missing or damaged material requires the explicit accept-current decision; absence of the registry additionally requires empty-state confirmation.
- One-use handoff is consumed only by a fully validated mutation. Invalid and genuinely consumed startup-ticket peers are rejected both sequentially and during an in-flight save. Constructor fencing and save completion share the path lock; the global registry guard is released before waiting for that lock.
- Compatible peers retain CAS and one-use behavior, unrelated paths make progress, an errored live owner stays fenced and a fresh process can resume only fully verified CLEAN state.
- Real syscall faults are synthetic test injection. Browser navigation, HTTP serialization, filesystem state, CLI subprocesses, archive checks and fresh-process handoff are actual execution against isolated test data.

## Evidence integrity and historical failures

Original S01-B01/B02 failures, correction-1 REDs and the correction-2 peer-ticket race remain retained. Three correction cycles were consumed: the default two plus one explicitly approved for S01-RET-REVIEW-01. The final independent report closes the blocker on the corrected source; it does not erase earlier failures or grant another repair cycle.

Two parent observer defects were retained separately from successful product commands: ANSI-colored UI summary parsing and a TCP TIME_WAIT socket misclassified as a live listener. Harness-only controls proved the corrected observations, including rejection of an actual listener. The original nonzero supervisor receipts remain available; product tests are not relabeled as new executions.

The final browser run retained eight EN/KO desktop/narrow screenshots, DOM language/geometry, request counts and process identities. It observed no JavaScript page errors, no automatic POST/PUT replay, preserved history/drafts and retirement of owned API/browser processes. Screenshots alone are not screen-reader or physical-device acceptance.

Local evidence is indexed under `.hermes/artifacts/campaign-01/S01/`: `peer-fence-review-result.json`, `isolated-acceptance.json`, final release/active receipts and the committed-tree receipt. These local artifacts and raw scratch fixtures are intentionally excluded from the product commit. `state.json` records the actual commit SHA after creation; this document cannot contain its own final SHA.

## Reproduce canonical coverage

From the repository root with the locked dependencies installed:

```sh
make test
make lint
make build
make test-e2e
```

Browser tests require Chromium and free loopback ports 5175/5182. They create isolated state rather than writing the active development workspace. Do not reuse or terminate a foreign listener to satisfy the gate.

## Explicit limits

This is a single cooperating local Linux API process. There is no multiprocess writer/recovery transaction, network-filesystem or power-loss guarantee. Persistent I/O failures can prevent recovery. Hashes bind consistency, not authenticated provenance. There is no production authentication, real model/device acceptance or execution-stage completion. Active development promotion must preserve existing data and be verified read-only; storage-fault injection and recovery are restricted to owned isolated state.
