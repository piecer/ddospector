# UI-01 local draft API

This is a loopback development workspace, **not** the future execution backend,
Safety Gate, authentication system, PostgreSQL store, MCP client or LLM client.

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
The pytest fixture uses `http://localhost` and rejects socket connection, DNS
lookup and subprocess calls; the separate smoke script starts only an owned,
ephemeral `127.0.0.1` Uvicorn listener and cleans up its process and draft file.

## Implemented contract

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
- A single-process, per-path shared lock covers read/validate/mutate/replace.
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

Single local process only: no multiprocess lock/durability promise, shared-network
filesystem claim, authenticated audit, encryption, automatic migrations, updates
or deletes. Local state is plaintext operator-owned draft data. Do not paste
secrets into names or instructions; there is no general-purpose secret detector.
Keep the containing directory trusted and private. No device, packet emission,
MCP handshake, AI inference, operational approval or production deployment was
implemented. Browser/frontend integration and independent review remain the
parent workstream's gates.
