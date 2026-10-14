# Phase 1 — supervised single OFFLINE run

## Authority and current priority

The user replaced the immediate full-S02 objective with a human-supervised,
single-worker, single-scenario first milestone. The subsequent explicit choices
were **OFFLINE execution without external transmission** and **a project-owned
local test environment**. This document governs that new milestone; the original
S02 contract, failures, evidence and deferred acceptance remain preserved.

This is a substantive operating-mode change, not permission to rename or reroute
the interrupted W2 workload. No old execution/correction allowance is reset.
Full S02 is not declared accepted, and completing this milestone does not
implicitly start S03–S12.

## User workflow and scope

1. Start an isolated, project-owned PostgreSQL/API/UI environment; never adopt an
   existing listener, database, container, volume or draft store.
2. Through the existing UI, register/select one immutable scenario revision and
   create its OFFLINE Run. The revision, digest and request identity remain bound.
3. The operator explicitly invokes a one-shot worker for that exact Run ID.
4. That worker attempts only the selected, never-attempted QUEUED run, publishes
   its existing bounded OFFLINE preparation result and exits. It never drains
   unrelated queued work, resumes an earlier attempt or automatically recovers
   expired work. A conflicting worker or unresolved leased job prevents entry.
5. Inspect the actual persisted status, events and manifest in the existing UI.
   Preserve the run/result and verification evidence; do not fabricate telemetry.

The result is an OFFLINE preparation manifest, not sent traffic, measured DUT
behavior or a defense verdict. LIVE, external target access, AI inference, MCP,
traffic generators and device control remain disabled.

## Runtime guarantees retained

- One supervised worker at a time for the same local database socket directory;
  legacy workers must not overlap the supervised owner either. Admission must
  precede database activity, and ownership lasts through actual worker cleanup.
- One selected Run ID, first attempt only, with no automatic reconnect, requeue,
  failover, retry or continuation after a repository error. A new command is an
  operator decision, not authority to replay an unresolved attempt.
- Existing transaction/publication guards, immutable input/result validation,
  cancellation checks, deadlines, bounded computation and bounded cleanup stay
  intact. A process exit is not proof that its stored Run is successful.
- Non-success or uncertain execution must be visible through a nonzero worker
  outcome and the real stored state. An interrupted RUNNING/CANCEL_REQUESTED run
  may remain unresolved and block new work; this milestone must document that
  limitation rather than automatically repair or delete the record.
- No inherited PG settings, DSN/password files, foreign services or public binds.
  Use the existing fixed local-socket configuration and owned test-resource rules.
- Preserve caller data, existing temporary artifacts and historical evidence.
  Do not restart the development services on 5173/5180 as part of isolated proof.

## Deferred, not passed

Automatic crash recovery/reclaim, multiworker throughput/failover, automatic
reconnect and uncertain-COMMIT recovery, exhaustive cancellation/completion races,
retry exhaustion, the original W2 fault matrix and full original S02 acceptance
are deferred. Their code/evidence remains historical or experimental; it is not
the supported Phase-1 operator entrypoint. The new normal-flow proof cannot be
reported as full S02 or as a production/HA deployment certification.

## Small implementation and acceptance slices

| ID | Deliverable | Required evidence | Status |
|---|---|---|---|
| P1-01 | Scope and roadmap priority | Exact approved choices; historical contract preserved | Accepted — 124c6df |
| P1-02 | Explicit one-shot selected-run worker | RED→GREEN tests for ID admission, exclusive local ownership, one selected first attempt, no queue draining/recovery/reconnect; existing pure regressions | Accepted — 6e2959c |
| P1-03 | Owned local environment and one scenario | Actual PostgreSQL, separate API and one-shot worker; UI creation/readback; independent stored-result comparison; no external target transmission | Accepted — 662ee18 and final integrated normal gate |
| P1-04 | Operator handoff | Repeatable commands, honest interruption limitation, independent scoped review, final relevant lint/build/tests and local commits | Accepted — PHASE1_ACCEPTANCE.md / PHASE1_LOCAL.md |

The approved Phase-1 milestone is complete. Exact scope, executed evidence and
remaining limitations are recorded in `PHASE1_ACCEPTANCE.md`. The original full
S02 contract remains unaccepted and deferred; this status does not replace it.

Develop and commit each finished small slice after its necessary checks. A
standalone documentation change requires consistency/link/diff checks, not a
replay of the deferred W2 workload. Product changes require focused regression
and the applicable canonical gates; never hide failures with skip/xfail, weaken
assertions or relabel old receipts as fresh execution. New scoped tests must be
collected by an explicit canonical target without deleting the original gates.

## Initial operator limitations

This is loopback-only, single-machine, supervised use. Do not mix legacy daemon
commands with the Phase-1 entrypoint or expose the unauthenticated UI/API remotely.
If a worker exits without a confirmed terminal result, inspect the existing Run;
do not blindly resubmit, reset storage or delete locks/data. Manual reconciliation
of a genuinely interrupted run is separate work, not an automatic recovery claim.
