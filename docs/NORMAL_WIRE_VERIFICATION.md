# Historical P0-A normal-wire provenance and verification

## Scope

This is the first follow-up to `PLAN_PROGRESS2.md`, based on product revision
`0530b0729403edd8985b3d1f4fa322d066356668`. In that slice, runtime `src/` was unchanged.
The change repairs a stale verification input, not a demonstrated DUT or Runs
runtime failure. The original progress report remains a historical audit.

The subsequent P0-B1 local-authority change has its own source and acceptance gates
in `P0B1_EXECUTION_AUTHORITY.md`. The P0-A accepted corpus is retained exactly as
`tests/fixtures/runs/normal-wire-p0a.json`; it is not a fallback for the latest
`normal-wire-current.json` source gate. The observations below belong to P0-A.

Implementation, actual normal capture and Node/Chromium replay are recorded below.
The independent R1/R2 correction review accepted the implementation and saved
capture bindings. Final scoped canonical results and integration are separate
closeout gates; this document does not infer them from a generated file alone.

## Corpora at the P0-A checkpoint

- Preserve `tests/fixtures/runs/normal-wire.json` byte-for-byte. Its SHA256 is
  `e3ee5b76d6a180d3a6d61462174c695989c444adc2f4bdb9c11a94d0aca47922`.
- The P0-A accepted corpus, now `tests/fixtures/runs/normal-wire-p0a.json`, has SHA256
  `04fa85bd80ea052efb35c1fea781fe8dac01095da36addbc95fc1bca947877d2`.
- The P0-A corpus contains 12 newly captured positive ASGI responses and all
  39 unchanged historical synthetic consumer-negative rows. It is not 51 real
  experiments, a network TCP capture, or a UI-to-worker browser workflow.
- Schema 2 retains the exact raw capture/report strings and hashes, completed
  probe/process report, four worker starts/exits, actual module origins, native
  process retirement, and PostgreSQL creation/cleanup journal.
  Its exact 93-path inventory covered all `src` Python/SQL files at that checkpoint,
  `pyproject.toml`, `uv.lock`, the input producer, probe and capture/ownership helpers.
- Ordinary consumers independently enumerate source paths, verify hashes and
  the linked completion/origin/cleanup graph, preserve all row identities and
  bytes, and reject incomplete or stale input. Both corpus files have pinned hashes.
  Adding, deleting or changing a covered source requires genuine new capture;
  tests neither regenerate fixtures nor fall back to historical success rows.
- Hashes and local receipts prove consistency and recorded provenance, not
  authentication against a malicious writer able to replace code and evidence.

## Actual normal-only capture

On 2026-11-10 (KST), the corrected P0-A capture invocation used the cached
PostgreSQL image through the existing ownership harness: network none, no published
ports, private Unix socket, separate roles/database and no ambient PG credentials.
The original normal probe actions, assertions and deadlines were preserved; its
only change binds imports to the checkout and opts into nonsecret origin receipts.

Observed Run: `fe960e59-59ad-4a99-8570-4f523bdbec7f`.

The preceding capture-01 completed, but independent review found a supervisor
late-zero deadline bypass and incomplete promotion validation. Both were reproduced
before correction. Its source, raw bytes and review HOLD remain historical evidence.
The corrected source consumed one separate capture-02 allocation; cumulative P0-A
captures are 2, not a retry/reset of an older W2 or model allowance.

| Boundary | Observation |
| --- | --- |
| Probe | Natural exit 0; complete final report |
| Selected separate worker | Exit 0; SUCCEEDED, attempt 1 |
| Repeated completed Run | Exit 69; no repeated execution |
| Previous-attempt fixture | Exit 69; explicitly SQL-seeded requeued state, not a crash test |
| Unresolved lease | Exit 69; real claim without computation, not concurrent-worker acceptance |
| PostgreSQL readback | Stored result equals actual HTTP result |
| Native ownership | Probe and new-session worker descendants tracked by the existing subreaper/pidfd owner; no remaining identities |
| PG ownership | Existing immutable-ID/labels/mount/volume checks; container and volume removed and exact absence read back |
| Promotion | Current fixture emitted only after full report, source equality and native/PG cleanup checks |

The original OFFLINE result remains preparation-only: `NOT_EVALUATED`, null
measurements and null defense verdict. No application model, DUT or traffic engine
was called. The normal capture does not resume full S02/W2 or reset prior limits.

## Reproduction

Explicit capture, from the repository root with the installed project environment:

```sh
.venv/bin/python tools/normal_wire.py --output /absolute/new-private-directory
```

The destination must be new and absolute. The helper refuses existing output,
does not pull images or use a caller database, does not overwrite repository
fixtures, and does not retry failed captures. Retain failed output and ownership
records; never adopt/delete unknown resources. An operator must review and promote
an actually completed artifact together with its new hash and parity evidence.

Effect-free proof checks and exact-byte Node replay:

```sh
.venv/bin/python -m pytest tests/tooling/test_normal_wire_capture.py tests/tooling/test_normal_wire_provenance.py -q
npm --prefix web test -- src/pages/runs/normal-wire.test.ts src/pages/runs/normal-wire-proof.test.ts
```

The dedicated browser case uses `web/playwright.runs-parity.config.ts`, explicit
`I3_WEB_ORIGIN`, `I3_WEB_OUTPUT`, and `FOCUS_CHROMIUM`. Its launcher must own a new
loopback strict-port Vite process with a dedicated proxy-free config, deny `/api/`,
use a short private TMPDIR and retire its browser/Vite subtree. The default Vite
config proxies `/api` and must not be used for this isolated replay. The ordinary
API/UI E2E launcher is not a replacement for this gate.

## Verified controls and preserved failure

- The original normal-wire test reproduced `Producer source changed` at collection,
  before test bodies. The old corpus and that failure remain preserved.
- Python provenance fault controls first reproduced two missing identity checks;
  after correction, the capture/assembly controls and existing NativeChildren
  controls passed (42 tests in the combined preflight).
- Web mutation controls first failed 19 cases covering incomplete/foreign proof,
  omitted/added sources and reordered rows. They then passed 23 cases alongside
  all 51 ordinary decoder cases (74 total). These are guard tests, not new PG runs.
- The first browser replay failed the network allowlist because borrowed
  `node_modules` resolved Vite's `env.mjs` outside the copied checkout. Its trace,
  failure and clean retirement are retained. No product/test assertion was relaxed.
- A byte-matched source copy with private dependency files corrected that setup.
  The unchanged browser case passed all 51 Node/Chromium hash/outcome comparisons,
  with zero denied requests, native retirement and exact listener absence/rebind.
  This is corrected-environment replay, not a retroactive pass of the first run.
- R1 now checks the original probe deadline after completion observation as well
  as during waiting; deterministic on-time/late-zero schedules preserve cleanup.
- R2 checks native launch argv against the selected Run and recorded worker starts,
  module names against their source paths, exact raw capture/report hashes and
  decoded agreement, and contradictory cleanup/errors/daemon-unavailable records.
  The reviewer reproductions are persistent Python/Web regressions with a valid
  current-corpus control before each mutation. Corrected focused checks passed
  58 Python cases (including retained ownership controls) and 80 Web cases.
- A relocated verification checkout exposed a test-only archival-path assumption.
  Archive replay now maps only the already-hashed current source inventory and
  immutable legacy bytes into the independently recorded capture root. It changes
  no proof bytes, cwd/argv checks, mutation or assertion, and never opens the old
  private checkout. The added unchanged-input/drift controls and all focused Python
  cases passed in the relocated environment (48 tests). Capture code and the actual
  corpus were not changed or recaptured for this test adaptation.
- The first full Web run in the copied environment had four setup failures: missing
  Git history and a symlinked virtualenv that violated the existing interpreter
  prefix assertion. A private Python 3.12 virtualenv reusing installed dependencies
  and read-only access to the real Git base corrected those bindings without
  changing tests. The unchanged full Web command then passed 3,151 tests. Initial
  failures and the intermediate interpreter-version preflight remain diagnostic
  setup history, not product regressions or erased failures.

## Evidence and open gates

Local task evidence is under
`.hermes/artifacts/progress2-p0a/attempt-7cbp1b8k/`:

- `baseline-normal-wire-red.log`, `capture-cli-red.log`, `provenance-red.log`,
  `consumer-proof-red.log`: preserved predecessor failures.
- `capture-01/`, `pre-correction/`, `independent-review.md`: predecessor capture,
  source and preserved review HOLD; not the corrected helper revision.
- `capture-02/`: corrected completed probe, raw captured bytes, source manifest, process
  receipts, ownership journal and parent exact-resource-absence readback.
- `consumer-green.log`: predecessor 74-case Node proof/decoder result.
- `corrected-current-python.log`, `corrected-current-web.log`: corrected 58/80-case checks.
- `browser-parity/`: failed borrowed-dependency replay, trace and retirement.
- `browser-parity-private/result.json`: corrected private-dependency replay.
- `browser-parity-corrected/result.json`: fresh corrected-corpus replay, all 51
  Node/Chromium comparisons, zero denied requests and verified native/listener retirement.
- `independent-review-correction.md` and final gate receipts: corrected-source
  adjudication and closeout evidence, separate from actual capture execution.
- `independent-portability-review.md`: narrowly scoped archival test adaptation.
- `final-gates/`: separate scoped canonical command logs and final `closeout.json`.
  The closeout record, not file existence or a partial log, records each actual
  exit, evidence source and integration/preservation result.

Final scoped canonical commands are `make test-api`, `make test-chat`,
`make test-tooling`, `make test-evidence`, `make test-phase3-config`, `make test-web`,
`make lint` and `make build`. Disposable cache/basetemp/report paths are owned by
the verifier. The broad `make test`/`test-runs` and full S02/W2 remain outside this
slice; they must not be reported as passed merely because the scoped gates pass.

The repository corpus carries its proof graph so ordinary tests do not depend on
private evidence paths. Local artifacts contain additional diagnostic detail and
are not a new runtime API.

A-FINAL, actual selected-model Target/Skill/Scenario acceptance, broad fault/recovery
and multiworker acceptance, live Safety Gate/Watchdog, actual DUT measurement,
and caller deployment remain open. This change must not enable LIVE, MCP execution
or automatic model calls. The next product implementation priority is P0-B's
execution-authority and independent safety contract, not an unapproved traffic test.
