# UI-01 verification scope

UI-01 is a local draft workspace, not a completed LIVE validation platform. The original `PLAN.md` and historical implementation plans remain unchanged.

## Reproduce the active-tree gates

From the project root after `make setup`:

```sh
make test
make lint
make build
make test-e2e
```

`make test` runs API and frontend unit/integration tests. `make lint` runs Ruff, ESLint and TypeScript. `make build` creates the production frontend bundle. Browser tests use Chromium, their own API/UI on 5182/5175, and a unique draft state under `TMPDIR`; they must not reuse or populate the development API on 5180.

## Accepted independent review coverage

- Backend: 222 API cases, lint/format, real loopback smoke and additional storage/boundary/context/execution-denial probes. Single-process, loopback-only scope; no production authentication or multiprocess guarantee.
- Frontend final candidate: 181 unit/integration cases across 18 files, lint/typecheck/build and 50 browser cases. Browser collection identities match execution identities, with no skips, retries or flaky outcomes.
- The 50 browser cases comprise 22 retained cases and 28 modal-lifecycle regressions. Counts describe the accepted candidate; fresh active-tree results are recorded separately below.

Independent reviews are archived under `.hermes/artifacts/ui-01/reviews/`. The final frontend report is `frontend-cycle2-deleg_3bf89384/evidence/frontend-final-review.json`; backend evidence is in `backend-deleg_2da28953/`.

## Repaired findings

- UI01-FE-001: a successful POST followed by failed workspace GET disabled the modal's own Retry and Close controls. Committed read-only recovery now stays reachable without unlocking stale or unrelated writes.
- UI01-FE-002: the documented root address rendered not-found. Exact `/` now opens overview; unknown paths still render not-found.
- UI01-FE-003: the first repair remounted a native dialog and lost invoker focus after successful saves. Logical-session focus is retained across relocation and consumed on dismissal; later readback does not steal focus from newer work.

The final reviewer accepted all three findings as closed. RED evidence and rejected candidates are retained rather than replaced by the final passing report.

## Browser acceptance

The real API-backed suite covers all 14 routes, English/Korean persistence, desktop and narrow reflow, keyboard navigation, native dialogs, root/deep links/history/unknown paths, actual target/MCP/Skill/campaign draft creation, agent assignment, deterministic context preview, persistent readback, inert user-authored HTML, API outage/recovery, automated accessibility checks and server-side execution denial.

Fault schedules use real POSTs with held or failed GET delivery. They assert one mutation and one durable record, recovery through repeated failures, both Close controls using pointer and keyboard, focus restoration and local Tab order after success, and no late reopening or focus theft. Loading/stale unsaved and sibling target/MCP/campaign/agent mutations remain blocked.

## Active integration evidence

The final review's source hashes are reconciled before integration. The runtime/test files must match those accepted bytes; README/contract/usage-document closeout is recorded as a documentation-only delta.

Fresh active-tree command logs, source manifest and final result are retained under `.hermes/artifacts/ui-01/final/`. The final verdict is read from `verification.json`, not inferred from the candidate's passing report. Runtime read-only screenshots and API health/state checks are separate from isolated write/E2E tests.

## Explicit limitations

No model inference, MCP handshake, external instrument/DUT access, traffic emission, operational approval, evidence capture or LIVE verdict is accepted in this slice. Such controls remain unavailable and execution endpoints reject requests. No production deployment, physical-device or human screen-reader validation is implied.

The backend review noted that unexpected fallback errors omit some headers relevant to direct cross-origin clients. This is a nonblocking advisory for the contracted same-origin proxy, not an authorization to expose the API remotely. Additional reviewer probes remain evidence, not added canonical test counts.

No Git commit or push is part of this delivery.
