.DEFAULT_GOAL := help
.PHONY: help setup api web test test-api test-web test-tooling test-runs test-evidence lint build test-e2e
help:
	@printf '%s\n' 'DDoSpector · local UI workspace' '  make setup     Locked Python and web dependencies' '  make api       Local API on 127.0.0.1:5180' '  make web       UI on 127.0.0.1:5173 (separate terminal)' '  make test      API and UI unit/integration suites' '  make lint      Ruff, ESLint and TypeScript checks' '  make build     Production UI build' '  make test-e2e  Real Chromium + isolated API/browser state'
setup:
	uv sync --frozen
	npm --prefix web ci
runs-migrate:
	.venv/bin/python -m ddospector.runs.migrate
.PHONY: runs-migrate worker worker-once test-phase1
worker: worker-once
worker-once: export RUN_ID := $(RUN_ID)
worker-once:
	.venv/bin/python -m ddospector.runs.worker --run-id "$$RUN_ID"
test-phase1:
	uv run --frozen pytest tests/runs/test_supervised_worker.py tests/runs/test_phase1_postgres.py tests/runs/test_offline_failures.py tests/runs/test_offline_manifest.py tests/tooling -q
api:
	.venv/bin/python -m uvicorn ddospector.api.app:app --host 127.0.0.1 --port 5180
web:
	npm --prefix web run dev
test: test-api test-web test-tooling test-runs test-evidence
test-api:
	uv run --frozen pytest tests/api -q
test-web:
	npm --prefix web test
test-tooling:
	uv run --frozen python -m pytest tests/tooling -q
test-evidence:
	uv run --frozen pytest tests/evidence -q
test-runs:
	@mkdir -p implementation-evidence
	@id=$$(.venv/bin/python -c 'import uuid; print(uuid.uuid4().hex)'); \
	uv run --frozen pytest tests/runs -q --junitxml=implementation-evidence/test-runs-$$id.xml
	@printf '%s\n' 'I0 + I1 admission tests. Worker/remaining API/Node parity/Runs UI/full S02 E2E: OPEN.'
lint:
	uv run --frozen ruff check src tests/api tests/runs tests/tooling tests/evidence tools
	npm --prefix web run lint
	npm --prefix web run typecheck
build:
	npm --prefix web run build
test-e2e:
	npm --prefix web run test:e2e

.PHONY: phase1-local phase1-open phase1-worker
phase1-local phase1-open phase1-worker: export PHASE1_WORKSPACE := $(WORKSPACE)
phase1-worker: export PHASE1_RUN_ID := $(RUN_ID)
phase1-local:
	.venv/bin/python tools/phase1_local.py create --workspace "$$PHASE1_WORKSPACE"
phase1-open:
	.venv/bin/python tools/phase1_local.py open --workspace "$$PHASE1_WORKSPACE"
phase1-worker:
	.venv/bin/python tools/phase1_local.py worker --workspace "$$PHASE1_WORKSPACE" --run-id "$$PHASE1_RUN_ID"

.PHONY: phase2-local test-phase2-storage
phase2-local: export PHASE1_WORKSPACE := $(WORKSPACE)
phase2-local:
	.venv/bin/python tools/phase1_local.py create --workspace "$$PHASE1_WORKSPACE" --evidence
test-phase2-storage:
	uv run --frozen pytest tests/evidence tests/api/test_evidence_transport.py tests/api/test_evidence_admission.py tests/api/test_boundary.py tests/tooling/test_evidence_fresh_setup.py tests/tooling/test_phase1_local.py tests/tooling/test_phase2_storage_targets.py tests/runs/test_evidence_postgres.py -q -o junit_family=legacy
