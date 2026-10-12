# S02 I1 — durable OFFLINE admission

This is the initial author implementation of the admission slice, not independent
acceptance of S02. `S02_RUNS.md` remains unchanged and normative; the current I1
work order selects the three-route subset below. The accepted uncommitted I0 seed,
not Git HEAD alone, is the patch preimage. No stage commit is made here.

## Implemented path

- `POST /api/v1/offline-runs`: bounded strict five-key request, validated LIVE
  refusal, process-wide admission, PostgreSQL readiness and same-key lookup,
  actual read-only S01 history capture, then one atomic input/QUEUED/event/quota
  transaction. Returns 202 for new admission and 200 for an exact retained replay.
- `GET /api/v1/offline-runs/by-request/{request_id}` and
  `GET /api/v1/offline-runs/{run_id}`: PostgreSQL-only consistent validated reads.
  GET does not execute or terminalize queued work. No worker means real QUEUED
  records remain QUEUED, including after their deadline and process restart.
- The S01 peer is constructed after the existing router with explicit
  `ticket=None`. The source thread owns its entire RLock/history/finalizer
  lifetime; captured canonical bytes survive later source edits or unavailability.
- Immutable bytea inputs/events/results, identity/terminal guards, bounded quota,
  role/durability/schema checks and a separate atomic migration CLI support this
  path. The stored event validator can read valid retained terminal DB fixtures;
  it is not a worker or a state-transition executor.

## Operation and configuration

Configure only `AIDDOS_RUN_DB_SOCKET` with an existing absolute private Unix socket
directory of at most 80 UTF-8 bytes, without comma, whitespace or NUL. Database,
port and runtime/owner roles are fixed by normative section 5. Ambient `PG*`
variables are refused; there is no DSN, password, service, credential-file,
SQLite or memory fallback. No configuration value or driver error is exposed in
HTTP errors. Existing health/draft/LIVE-denial behavior is unchanged.

Run `.venv/bin/python -m aiddos.runs.migrate` (or `make runs-migrate`) explicitly
against an operator-owned, separately provisioned permitted database. The CLI
installs the schema atomically, validates identical repeats without DML, and
refuses foreign/incompatible state. The API never imports the migration module,
migrates, creates a database, or starts a worker. This candidate's tests use only
fresh invocation-owned PostgreSQL fixtures; this document grants no authority
over an existing service or active database.

One API process is supported. Concurrent requests share one process-rooted
manager: four charged operations and a dedicated four-thread source executor.
A response decision has its original five-second authority; connection and SQL
waits are at most two seconds and capped by the remaining authority. Expiry,
request cancellation, disconnect and shutdown revoke future business work.
Already issued COMMIT without timely selected acknowledgement is uncertain:
reconcile using the original request ID, never automatically mint a replacement.

Response completion does not release a slot. Source futures, pending acquisition,
exact connections and cleanup remain strongly retained until real retirement.
Close is attempted once; a close error with a confirmed closed handle differs
from unconfirmed disposal. No hidden reconnect, replacement manager or default
executor spill is used. Shutdown closes admission permanently and observes one
shared one-second grace. Its bounded diagnostic is CLEAN only with no residual
custody; otherwise lifespan raises `S02_DRAIN_INCOMPLETE`. Observer/rescue cleanup
of an owned test process is not a clean-drain result. Operator process recovery
is necessary for irrecoverable disposal; requests do not kill the API.

## Verification and evidence boundaries

`make test` keeps API, Web and all 267 inherited runs cases and collects the new
`tests/runs/test_offline_*.py` tests. New real-PG helpers are isolated from the
unchanged I0 borrower protocol and guards. They bind candidate source, venv,
endpoint, process identities and output, and reject an unowned endpoint before
connection. Fault barriers are labeled synthetic; HTTP, S01, migrations, SQL,
process restarts and same-volume PostgreSQL restart are real.

The I1 matrix and exact execution results are frozen separately in
`i1-evidence/report.json`, `report.md`, `matrix-final.json`, command receipts,
JUnit/phase reports, the seed-relative patch and literal manifests. TDD failures,
intermediate failed GREEN attempts, observer corrections and prior runs remain
preserved. Canonical setup/test/lint/build results must be newer than this file;
this note itself does not assert that any command passed. Recorded I0 predecessor
passes are not counted as this author's fresh I1 execution.

Retained-128, terminal replay and bytea boundary fixtures are explicitly DB
fixtures, not full-stage worker-reachable end-to-end witnesses. Producer response
bytes are retained for later Node/browser parity, not accepted across runtimes.
Process/server restart tests establish restart persistence, not power-loss or
hostile-DBA guarantees. Installed read-only toolchains/browser binaries are reused;
all writable state/caches and owned endpoints are isolated.

## Still OPEN

Worker claim/fencing/heartbeat/recovery/task execution; cancel/list/events routes;
producer-to-Node/Chromium parity; Runs UI; full S02 end-to-end; active integration;
fresh independent I1 review and parent adoption; stage commit/exact-commit;
physical/live-device acceptance. No S03 advance, fabricated worker completion,
model/MCP/device invocation or packet generator is included.
