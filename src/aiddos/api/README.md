# Local draft API: UI-01, AI-02 and S01

This is a loopback development workspace, **not** the future execution backend,
Safety Gate, authentication system, PostgreSQL store, MCP client or LLM client.

AI-02 adds configuration-only model profiles through GET/PUT
`/api/v1/ai-settings`: closed snapshots, revision compare-and-set, atomic audit,
explicit default/review-agent bindings and a maximum of 20 profiles. Credential
fields hold environment-variable names, never values; no lookup or connection
occurs. POST `/api/v1/ai-settings/test` and `/api/v1/ai-settings/models` are denied
after transport admission, including malformed bounded JSON bodies.

The complete AI-02 configuration contract and execution boundaries are in
[`docs/AI_SETTINGS_CONTRACT.md`](../../../docs/AI_SETTINGS_CONTRACT.md).
The dedicated endpoint leaves the existing workspace response shape unchanged.
The pinned Python 3.12 Unicode/IDNA metadata grammar and reproducible browser
tables are described in
[`AI_SETTINGS_COMPATIBILITY.md`](../../../docs/AI_SETTINGS_COMPATIBILITY.md).

## Run / verify

Use Python 3.12 in a project-local `.venv`; do not replace system Python.

```sh
uv venv --python 3.12 .venv
uv sync --locked
uv run uvicorn aiddos.api.app:app --host 127.0.0.1 --port 5180 --workers 1 --no-proxy-headers
uv run pytest tests/api -q
uv run ruff check src/aiddos tests/api
uv run ruff format --check src/aiddos tests/api
uv run python tests/api/smoke_loopback.py
```

The factory is `aiddos.api.app.create_app(state_path=...)`. Otherwise the path is
`AIDDOS_UI_STATE_PATH`, falling back to `.local/ui-drafts.json` relative to the
launch directory. Import, health, initial workspace reads and preview do not
create a state file. Health is process liveness, not a storage health assertion.
The default pytest fixture uses `http://localhost` and rejects socket connection,
DNS lookup and subprocess calls. S01 recovery tests narrowly permit source-bound,
finite local CLI/API child processes; they do not contact external services.
The separate smoke script starts only an owned,
ephemeral `127.0.0.1` Uvicorn listener and cleans up its process and draft file.

## Implemented contract

- GET/POST `/api/v1/scenarios` and GET/PUT `/api/v1/scenarios/{id}`: bounded,
  revision-checked scenario definitions with immutable versions and frozen
  DUT/SINK/profile snapshots. Saving does not mutate the existing draft store.
  Complete schema, pagination, digest and error precedence are specified in
  [`S01_SCENARIOS.md`](../../../docs/stages/S01_SCENARIOS.md).
- GET `/api/v1/health`, `/api/v1/workspace`.
- POST `/api/v1/targets`, `/mcp-servers`, `/skills`, `/campaigns`: validated,
  atomically persisted drafts with actual local audit records.
- PUT `/api/v1/agent-profile`: existing Skill/MCP references only, with immutable
  `REVIEW_ONLY` autonomy and disabled execution.
- POST `/api/v1/agent/preview`: deterministic, localized JSON context wrapped in
  an explicit untrusted-guidance warning. No inference, simulated assistant
  answer, tool discovery, endpoint probing, stdio command or network operation.
- POST `/api/v1/runs` and `/api/v1/agent/execute`: unconditional 409 denial after
  transport admission, regardless of purported approval or body contents. These
  routes do not read or write storage. Invalid transport can fail earlier with
  400/403/408/413/415, but never admits execution.

`catalog.py` contains instruction and traffic-profile catalog **1.0.0**. Skill
versions are on the wire; the frozen TrafficProfile shape has no version field,
so its version is attached to the catalog and persisted state envelope instead.
No execution records or fake connections are seeded. Custom Skill text is
preserved identically in `en` and `ko`; it is not translated or given permissions.

### Compatible additive metadata

The existing TypeScript files are untouched. The only additional response field
is `workspace.meta.audit_retention`:

```ts
{ limit: 500, retained: number, total_recorded: number, dropped: number }
```

This describes actual retention of the most recent 500 local changes; it does not
claim pagination. Consumers of the frozen shared fields remain compatible.

## Admission and persistence

- Closed, strict schemas; bounded nonblank strings, fixed enums, duplicate-free
  assignments, literal IP/ASCII DNS validation without resolution. Multiline
  guidance is allowed; controls, bidi controls and invalid surrogates are not.
- MCP HTTP endpoints must have a valid HTTP(S) host/port and no userinfo, fragment,
  whitespace or query string. Query strings are deliberately excluded because
  this store has no credential facility. Stdio values are identifiers matching
  `[a-z][a-z0-9-]{0,63}`, never commands. No credentials fields are accepted.
- Maximum 100 drafts per collection, 103 assigned Skills (including 3 built-ins),
  100 assigned MCP drafts and 500 retained audit records. Arrays are admitted or
  rejected whole. Preview includes all assigned guidance without silent truncation.
- The ASGI boundary checks Host, exact Origin and content type before parsing.
  Allowed Origins are `http://localhost`, `http://127.0.0.1` or `http://[::1]` with
  explicit port 5173, 5175, 5180 or 5182. No wildcard CORS or credentials CORS.
  Origin-less non-browser local requests are allowed; cross-site Fetch Metadata
  without Origin is rejected. **These checks are not authentication.**
- Bodies require UTF-8 `application/json`, at most 256 KiB, at most 4096 ASGI frames
  and a 5-second receive budget. Invalid/ambiguous framing, compressed bodies,
  duplicate JSON keys, non-finite constants and nesting beyond 32 are rejected.
- For the legacy draft store, a single-process, per-path shared lock covers read/validate/mutate/replace.
  Writes use a same-directory 0600 temporary file, file fsync, atomic replace and
  directory fsync. State is freshly read and validated on each operation; there
  is no stale in-memory success cache. Reading is capped at 16 MiB and rejects
  final-path symlinks/non-regular files. All prior state is kept on pre-publication
  write failure. Existing malformed or incompatible state is never auto-reset.
- `STATE_CORRUPT` requires operator restoration of a compatible backup while the
  service is stopped. `STATE_UNAVAILABLE` reports storage failure without paths.
  A directory-sync failure **after** atomic replacement returns
  `STATE_COMMIT_UNCERTAIN`: reload before retrying; the file may already contain
  the draft. Never describe this case as a rollback.

## Limits

S01 uses a separate single-process registry at the effective draft filename plus
`.scenarios.json`. The registry has 100 identity / 10 version limits, an 8192-byte
complete-record cap and a 16 MiB state read cap. List/history/mutation responses
have serialized limits of 1 MiB / 256 KiB / 256 KiB. Reads never repair state or
rebind historical targets against today's draft store. Writes acquire scenario
then draft locks; source failures retain `STATE_CORRUPT`/`STATE_UNAVAILABLE` while
registry failures use `SCENARIO_STATE_*`. A failure after replacement returns
`SCENARIO_COMMIT_UNCERTAIN`, never a rollback claim. The digest is not a signature.
The browser has its own strict integer-token decoder, literal-preserving text
validation, raw-byte budgets and a 10-second body-plus-validation deadline.

S01 persistence additionally uses a fixed `R.s01-pending` holding directory and
4,096-byte `R.s01-recovery` receipt, where R is the scenario registry path. Its
private candidate and exposed publication alias normally share one inode bounded
to 16 MiB. Failed operations retain material without pathname cleanup and fence
the shared live owner. A fresh verified CLEAN registry/empty slot can resume
without operator recovery. Incomplete state never silently becomes an empty store.

The offline executable is `python -m aiddos.api.scenario_recovery`, with `inspect`
and `recover` commands. All cooperating writers must be stopped first. Explicit
`--accept-current` preserves the valid current registry and observable remnants
when an incomplete attempt is abandoned; absent current state additionally needs
`--confirm-empty-registry`. No candidate replay, rollback or force deletion exists.
Recovery returns one ticket for `AIDDOS_SCENARIO_RECOVERY_TICKET` on a single API
launch. Only a fully validated save consumes it; GET does not. Never retain this
input in `.env`, logs or automatic restart configuration. See
[`SCENARIO_STORAGE_RECOVERY.md`](../../../docs/SCENARIO_STORAGE_RECOVERY.md) for
exact commands, per-invocation archive bounds and same-archive resume behavior,
and [`S01_RETENTION_RECOVERY.md`](../../../docs/stages/S01_RETENTION_RECOVERY.md)
for the closed frame/decision contract and failure ordering.

Single local process only: no multiprocess lock/durability promise, shared-network
filesystem claim, authenticated audit or encryption. AI-02 has an explicit,
exact-schema v1-to-v2 migration: GET changes memory only, and the next authorized
draft mutation persists v2 while preserving prior data/audit. Profile edits and
deletion use revision-checked AI snapshot replacement; generic UI-01 entity
update/delete APIs remain unavailable. Local state is plaintext operator-owned
draft data. Do not paste
secrets into names or instructions; there is no general-purpose secret detector.
Keep the containing directory trusted and private. No device, packet emission,
MCP handshake, AI inference, operational approval or production deployment was
implemented. Browser/frontend integration and independent review remain the
parent workstream's gates.
