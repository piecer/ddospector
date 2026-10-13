.DEFAULT_GOAL := help
.PHONY: help setup api web test test-api test-web test-tooling test-runs lint build test-e2e
help:
	@printf '%s\n' 'DDoSpector · local UI workspace' '  make setup     Locked Python and web dependencies' '  make api       Local API on 127.0.0.1:5180' '  make web       UI on 127.0.0.1:5173 (separate terminal)' '  make test      API and UI unit/integration suites' '  make lint      Ruff, ESLint and TypeScript checks' '  make build     Production UI build' '  make test-e2e  Real Chromium + isolated API/browser state'
setup:
	uv sync --frozen
	npm --prefix web ci
runs-migrate:
	.venv/bin/python -m ddospector.runs.migrate
.PHONY: runs-migrate worker
worker:
	.venv/bin/python -m ddospector.runs.worker
api:
	.venv/bin/python -m uvicorn ddospector.api.app:app --host 127.0.0.1 --port 5180
web:
	npm --prefix web run dev
test: test-api test-web test-tooling test-runs
test-api:
	uv run --frozen pytest tests/api -q
test-web:
	npm --prefix web test
test-tooling:
	uv run --frozen python -m pytest tests/tooling -q
test-runs:
	@mkdir -p implementation-evidence
	@id=$$(.venv/bin/python -c 'import uuid; print(uuid.uuid4().hex)'); \
	uv run --frozen pytest tests/runs -q --junitxml=implementation-evidence/test-runs-$$id.xml
	@printf '%s\n' 'I0 + I1 admission tests. Worker/remaining API/Node parity/Runs UI/full S02 E2E: OPEN.'
lint:
	uv run --frozen ruff check src tests/api tests/runs tests/tooling tools
	npm --prefix web run lint
	npm --prefix web run typecheck
build:
	npm --prefix web run build
test-e2e:
	npm --prefix web run test:e2e
