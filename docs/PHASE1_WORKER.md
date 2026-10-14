# Supervised OFFLINE worker

This is the Phase-1 worker component, not full S02 acceptance or a persistent
local-environment launcher. Use only a project-owned local PostgreSQL instance
and the matching API/UI workspace. Never point the command at an unrelated socket.
See `PHASE1_SUPERVISED_OFFLINE.md` for the complete first-milestone checklist.

## One explicit execution

After the matching API has created a new OFFLINE Run, copy its complete lowercase
UUIDv4 ID and run from the repository root:

```sh
DDOSPECTOR_RUN_DB_SOCKET=/absolute/owned/socket make worker RUN_ID=<exact-run-id>
```

`make worker-once` is the same entrypoint. The shell forwards the value as one
argument; missing, uppercased or otherwise malformed IDs are rejected, not fixed.
The low-level equivalent is:

```sh
DDOSPECTOR_RUN_DB_SOCKET=/absolute/owned/socket \
  .venv/bin/python -m ddospector.runs.worker --run-id <exact-run-id>
```

Do not use the no-argument Python daemon for Phase 1: it is the retained,
unaccepted historical automatic-recovery path. The ordinary `make worker` target
now always requests the supervised mode and refuses a missing Run ID.

The selected run must be QUEUED, have no prior attempt and remain within its
original deadline. Other queued runs are untouched. Any unresolved leased job
prevents a new supervised claim, including an expired lease: this worker does not
reclaim it. An exclusive lock on the local socket-directory inode prevents other
current-version workers from overlapping this supervised invocation. The lock
uses an owned descriptor, not a new/removable lock file, and is held through
computation and connection cleanup. The directory must not be replaced while the
workspace is in use; this is a single-machine cooperating-entrypoint guarantee,
not distributed exclusion or protection against an unrelated database writer.

## Outcomes

| Exit | Meaning |
|---|---|
| 0 | Selected run completed its OFFLINE preparation publication and worker cleanup |
| 1 | Selected run reached a non-success outcome during processing; inspect the stored run |
| 2 | Invalid command-line arguments; no worker execution |
| 69 | No eligible first claim, or an unresolved lease blocks admission; no automatic retry |
| 75 | Execution/repository/cleanup could not complete safely; outcome may require inspection |
| 78 | Configuration, schema readiness or local worker-lock admission refused |
| 130 | Supervised invocation interrupted; this does not mark its stored run successful |

The startup `ready` line is not a completion receipt. Inspect the actual Run,
events and manifest in the UI/API. Success is preparation only: there are no sent
packets, measured telemetry or defense verdicts.

If a worker stops without a confirmed terminal result, preserve the existing Run
and investigate before any new invocation. A RUNNING/CANCEL_REQUESTED record may
remain unresolved and block entry. Repeating the command does not repair it.
Do not delete the database, edit counters or launch the legacy daemon to force
progress. Automatic recovery and a general manual-reconciliation utility are not
part of this component.

## Scoped verification

```sh
make setup
make test-phase1
make lint
make build
```

`test-phase1` collects the new coordinator/CLI/locking tests, one real private-PG
normal execution with a separate one-shot process, retained pure compiler tests,
and tooling tests. Docker and the already-cached PostgreSQL image required by the
owned test harness must be available. It does not execute the deferred W2 outage,
restart, failover or retry-exhaustion campaign. The original full targets remain.

The database proof uses real in-process ASGI HTTP responses, not a network API or
browser. It checks selected-run completion, untouched queued work, repeat refusal,
raw stored-result/HTTP agreement, a disclosed SQL-seeded prior-attempt refusal,
and refusal while a real unexecuted claim exists. The last two are admission
fixtures, not crash/recovery or competing-worker acceptance.

The current normal-wire corpus is freshly captured from that ASGI/PG/worker path;
its 39 synthetic consumer negatives are retained unchanged. Producer-source and
response-byte checks remain enforced. Historical TCP/browser capture evidence is
preserved in Git and campaign artifacts, not relabeled as fresh Phase-1 browser
verification. The owned network API/UI operator workflow is a separate milestone.
