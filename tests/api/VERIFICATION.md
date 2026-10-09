# Backend UI-01 verification receipt

Candidate: isolated `aiddos-ui-20261009-093204/backend` directory. All implementation
files were new; the initial candidate contained the shared docs/web scaffold only.
No Git repository existed in this candidate; no Git mutation, staging or commit
was performed, and the active repository was not edited.

## Observed vertical RED → GREEN cycles

These are actual assertion outcomes from tool executions, not proposed tests.
Every RED was followed by the implementation slice and a passing complete API
suite before the next feature was added. Environment/collection setup errors
listed below are explicitly **not** counted as RED evidence.

| Slice | Meaningful RED observed | Subsequent complete suite |
|---|---|---:|
| Health | expected 200, received 404 | 1 passed |
| Initial workspace/catalog | expected 200, received 404 | 2 passed |
| Durable target | expected 201, received 404 | 3 passed |
| MCP draft registration | expected 201, received 404 | 4 passed |
| Versioned custom Skill | expected 201, received 404 | 5 passed |
| Agent assignment/reference integrity | expected 200, received 404 | 6 passed |
| Deterministic preview | two expected-200/actual-404 assertions | 8 passed |
| Campaign/reference integrity | expected 201, received 404 | 9 passed |
| Unconditional execution denial | 8 expected-409/actual-404 assertions | 17 passed |
| Strict request validation | 106 failures, 8 positive controls passed | 131 passed |
| ASGI origin/framing/body admission | 41 failures, 5 controls passed | 177 passed |
| Atomic persistence/corruption/replay | 23 failures, 1 control passed; concurrent writes retained 12/24 | 201 passed |
| Entity caps/audit retention | 5 failures; 101st draft admitted and audit overflow broke reads | 206 passed |
| Persisted Skill/audit authority | 10 expected-503/actual-200 assertions | 216 passed |
| Frame flood/deadline | expected 413/408, received 422 | 218 passed |
| Post-replace directory fsync failure | wrong STATE_UNAVAILABLE vs STATE_COMMIT_UNCERTAIN | 219 passed |
| Sanitized fallback HTTP errors | text/plain instead of JSON; missing NOT_FOUND code | 221 passed |
| Safe integer audit counter | expected 409, received 200 | 222 passed |

Representative invocations:

```sh
uv --cache-dir .venv/uv-cache run pytest tests/api/test_workspace.py -q
uv --cache-dir .venv/uv-cache run pytest tests/api/test_drafts.py -q
uv --cache-dir .venv/uv-cache run pytest tests/api/test_agent.py -q
uv --cache-dir .venv/uv-cache run pytest tests/api/test_denials.py -q
uv --cache-dir .venv/uv-cache run pytest tests/api/test_validation.py -q --tb=short
uv --cache-dir .venv/uv-cache run pytest tests/api/test_boundary.py -q --tb=line
uv --cache-dir .venv/uv-cache run pytest tests/api/test_persistence.py -q --tb=line
uv --cache-dir .venv/uv-cache run pytest tests/api/test_capacity.py -q --tb=short
uv --cache-dir .venv/uv-cache run pytest tests/api/test_capacity.py -k overflow -q --tb=short
```

## Executed final-scope checks

- `uv --cache-dir .venv/uv-cache run pytest tests/api -q --tb=short`:
  222 passed, no skips or warnings (latest pre-receipt run: 11.34 seconds).
- `uv --cache-dir .venv/uv-cache run ruff check src/aiddos tests/api`:
  all checks passed after import/format repairs.
- `uv --cache-dir .venv/uv-cache run ruff format --check src/aiddos tests/api`:
  formatted source accepted.
- `uv --cache-dir .venv/uv-cache run python tests/api/smoke_loopback.py`:
  real Uvicorn health, draft creation/read-back, deterministic preview and both
  execution denials passed; the owned process/socket and temporary state cleaned.
- Runtime introspection resolved CPython 3.12.13 in this candidate's `.venv`, with
  `aiddos.__file__` in this candidate's `src/aiddos`. System `python3` remained
  3.10.12. `uv.lock` contains registry-resolved versions and hashes.

The parent should rerun these checks on the integrated exact manifest; the child
also reruns pytest, Ruff and smoke after this receipt is written.

## Setup/verification repairs, not product RED evidence

- A cache directory created inside `.venv` before venv creation caused uv's
  environment validation to fail. Repaired using `uv venv --allow-existing`
  with the already installed `/usr/bin/python3.12`; system Python was untouched.
- Resolved Starlette deprecated its old httpx TestClient backend. The warnings-as-
  errors collection check exposed this. Installed its supported `httpx2` backend;
  an initial unsatisfiable major-version range was corrected from resolver output.
  The lock resolves `httpx2==2.13.1`; no warning was suppressed.
- Initial Ruff import sorting/long-line issues were repaired and checks rerun.
- Initial fallback-error test JSON decoding failures were improved into explicit
  content-type/code assertions and rerun RED before implementing the fix.

## Integration notes / remaining limits

- Sole additive wire metadata: `meta.audit_retention = {limit, retained,
  total_recorded, dropped}`. Frozen TypeScript/shared scaffold was not edited.
- Traffic profiles are versioned by catalog version 1.0.0, not a new profile field.
- HTTP MCP endpoint query strings are intentionally rejected (no credential store).
- Plaintext single-process local drafts only; no production auth, multiprocess
  durability, credential detection/encryption, migrations, device access, MCP
  connection, LLM inference or LIVE execution. Instructions never grant authority.
- Directory fsync failure after replace is explicitly uncertain, not a rollback.
- Browser/frontend integration and independent review are parent-owned gates.
- Generated `.venv` and `__pycache__` contents are not source handoff artifacts.
  The accompanying manifest lists the exact owned deliverable files and SHA-256.
