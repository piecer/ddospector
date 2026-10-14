# Phase-1 retained local OFFLINE workspace

This launcher is a **single-machine, human-supervised development environment**,
not a daemon, a traffic generator, or full S02 acceptance. It changes neither the
public API nor the committed selected-run worker. No DUT is contacted, no MCP/AI
service is invoked, and no test traffic is sent to a target. Local API/DB control
traffic still exists. The scenario's DUT/SINK entries
are inert metadata required by the existing scenario editor.

## Prerequisites

Use Linux with `/proc`, pidfds, Docker at `/var/run/docker.sock`, the project's
locked `.venv`, and installed `web/node_modules`. Dependencies must already be
available; the launcher does not install or download anything. Docker must have
`postgres:16.6-alpine3.21`, immutable image
`sha256:1d04b9ba1d4996401f2552b51beda8187f175c0645c091e4781134fc9c9a3eef`.
The cached image is checked, then created with `--pull=never`.

Choose a **new, absolute, durable, short workspace path** whose parent exists.
`<workspace>/d/s` must be at most 80 UTF-8 bytes. Symlink aliases, `/tmp`, `/var/tmp`,
the configured temporary directory and the Hermes auto-pruned cache are refused.
The workspace is mode 0700, the socket's immediate ancestor is 0700, and its leaf
is 0777. Never replace/move the socket directory or modify the workspace while in
use. This is a cooperating, same-user local workflow, not protection from another
process with the same UID deliberately editing receipts or Docker resources.

There must be at least 1 GiB free on both host and Docker storage. PostgreSQL gets
network `none`, no published ports, empty `listen_addresses`, 512 MiB, 128 PIDs,
2 CPUs, bounded 10m × 2 logs, exactly the private socket bind mount and one fresh
anonymous data volume. There is no ambient PostgreSQL connection or SQLite
fallback. An environment containing any `PG*` name is refused. Other ambient
proxy/loader/app settings are removed before startup; children get a fixed local
environment, explicit socket and draft path. Do not source `.env` for this tool.

## Operator workflow

From the checkout root, terminal A:

```sh
.venv/bin/python tools/phase1_local.py create --workspace "$HOME/p1-local" --web-port 5175
```

Wait for `"phase": "RUNNING"`, then open the printed loopback URL. Only 5175 or
5182 is accepted for the UI because those are already allowed by the unchanged
API origin boundary. An occupied port is a refusal, not permission to kill/adopt
its listener. API uses a freshly reserved loopback socket, passed directly to
Uvicorn; Vite's explicit proxy points only to that socket's port. Ports 5173/5180
are never used. The launcher does **not** launch a worker.

The Make aliases are `make phase1-local WORKSPACE=/absolute/path`,
`make phase1-open WORKSPACE=/absolute/path`, and
`make phase1-worker WORKSPACE=/absolute/path RUN_ID=<exact-run-id>`.
They use the default UI port 5175; use the direct CLI to select 5182 explicitly.

1. In **Targets / 시험 대상**, add one DUT and one SINK **draft**. For a local
   demonstration, use inert documentation addresses `192.0.2.71` and `192.0.2.72`;
   these are metadata only and are never contacted.
2. In **Profiles / 실행 프로필**, choose **New scenario / 새 시나리오**. Name it,
   select those draft references, and fill the required version/budget/criteria
   fields. For a small valid example: TCP, IPv4, ALLOW; 100 PPS, 1000 BPS, 1000
   packets, 10000 bytes, 10 connections, 10 seconds; delivery 95–100%, legitimate
   loss 1%, latency 100 ms; ingress/egress PCAP and service-probe evidence roles.
   Leave optional metrics/PCAP asset blank. These are preparation requirements,
   **not measurements or permission to transmit**. Save the immutable revision.
3. In **Runs / 실행 이력**, select that saved scenario and its version. Click
   **Start OFFLINE preparation / OFFLINE 준비 시작**, then **View submitted run**.
   Copy the complete lowercase Run UUID. A QUEUED run has not executed.
4. Terminal B, explicitly invoke the one-shot worker:

   ```sh
   .venv/bin/python tools/phase1_local.py worker --workspace "$HOME/p1-local" --run-id <exact-run-id>
   ```

   This validates original workspace custody and invokes exactly
   `.venv/bin/python -m ddospector.runs.worker --run-id <exact-run-id>` once.
   Its exit status is preserved. No queue drain, reconnect, retry, or legacy
   no-argument daemon is started. See `PHASE1_WORKER.md` for worker exits.
5. Inspect the actual terminal detail, events and manifest. Refresh the history
   list if it still shows its earlier empty snapshot. `SUCCEEDED` means OFFLINE
   preparation publication only: `NOT_EVALUATED`, measurements null, defense
   verdict null. No telemetry or defense result has been measured.

Do not queue another run merely to repair an unresolved one. The existing worker
refuses prior attempts, expired work and unresolved leased jobs. There is no HTTP
code-execution endpoint added by this launcher.

## Ordinary shutdown and explicit reopen

Press Ctrl-C in terminal A. New wrapper-worker admission is closed; already
admitted wrapper workers finish before PostgreSQL is stopped. Owned API/UI
children are retired using pidfds and their retirement receipts are kept.
PostgreSQL is stopped by its validated immutable ID. **The container, data
volume, drafts, scenarios, runs, logs and receipts are not deleted.** There is no
purge/reset command. Do not bypass the wrapper while shutting down.

To reopen a normally stopped workspace, explicitly run:

```sh
.venv/bin/python tools/phase1_local.py open --workspace "$HOME/p1-local" --web-port 5175
```

Reopen requires the original successful-create receipt/cidfile, one registration,
original helper hash and checkout path, unchanged socket directory identities,
exact immutable container ID/creation time/name/labels/image/isolation/mounts,
exact original volume metadata and its sole attachment. A name or label alone is
not authority. A stopped container is started; existing data is **not** bootstrapped
or migrated again, and no run is executed. Existing scenarios/results remain
available through the real API/UI.

If startup, worker execution, shutdown or receipt persistence is interrupted,
retain the workspace and inspect its receipts. `STARTING`, `STOPPING`, `BLOCKED`
or an orphaned `RUNNING` state is **not automatically adopted or repaired**.
A successful ordinary reopen does not repair unresolved database jobs. Do not
edit state files, delete locks, change counters, run the old daemon or remove the
volume to force progress. Manual reconciliation and moving a workspace between
checkouts/helper versions require a separate reviewed procedure. The launcher
never treats an unknown create outcome as cleanup authority.

## Verification (opt-in, no historical collection change)

```sh
make test-tooling
make lint
make build
```

`tests/tooling/test_phase1_local.py` tests admission, retained receipt refusal,
non-destructive lifecycle and exact worker forwarding. It creates no Docker
resources. The real-browser case is deliberately named `.case.ts`, and uses only
`web/playwright.phase1.config.ts`; it does not change the historical default E2E
collection or start/adopt servers.

For a **fresh verification workspace only**, start the launcher as above. Create
an empty owned evidence directory and supply it explicitly:

```sh
P1_WORKSPACE="$HOME/p1-local" P1_OUTPUT=/absolute/owned/evidence \
  node web/node_modules/playwright/cli.js test --config web/playwright.phase1.config.ts
```

Use installed Chromium (`PLAYWRIGHT_BROWSERS_PATH` may explicitly name the installed
cache). The case creates draft references/scenario/run through actual browser
controls and prints the selected Run ID. While it waits, invoke the worker in a
separate terminal using the exact command above. It captures real responses,
EN/KO screenshots, terminal detail and events; outbound browser URLs are denied.
It never launches the worker itself. Do not run this mutation case against an
operator's populated workspace. After ordinary stop/open, the same case with
`P1_RETAINED_RUN=<existing-id>` and a **new evidence directory** is GET-only and
checks the retained result without another scenario, run or worker invocation.

This proves one normal local preparation chain, not a fault/recovery campaign,
multiworker throughput, device operation, HA or a host-wide egress certificate.
