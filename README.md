# Aegis Lab · AI defense validation workspace

UI-first implementation of the project in `PLAN.md`. The historical plan is preserved. The initial delivery focuses on the complete layout/menu and real local draft workflows, **not the live test platform**.

## Run locally

Requirements: Node.js compatible with the locked Vite version (Node 24 was used), npm, and uv. The project Python environment uses Python 3.12; do not change system Python.

```sh
make setup
make api       # terminal 1: 127.0.0.1:5180
make web       # terminal 2: 127.0.0.1:5173
```

Open `http://127.0.0.1:5173`. From Windows with WSL localhost forwarding enabled, use the same address. The processes bind loopback only. An occupied port is an error; never stop another application's process to make room.

## Layout

- Workspace: Overview, Campaigns, Runs, Findings, Evidence
- Lab configuration: Targets, Instruments, MCP servers, Traffic profiles
- AI & governance: AI agent, AI settings, Skill library, Approvals
- System: Audit log, Settings

The persistent shell has local API status, OFFLINE mode, a saved English/한국어 preference, responsive navigation, and a Ctrl/Cmd+K page search. The overview is a setup workspace; its component diagram is a planned topology, not live telemetry.

## Draft workflows in this slice

1. Add a target draft (DUT or SINK). Registration does not authorize any traffic.
2. Add an MCP server draft with transport, endpoint/registered ID and usage instructions. Registration does not connect a server or run a command.
3. Inspect versioned built-in Skills or create a custom draft Skill.
4. Assign Skills and MCP guidance to the review-only agent profile, then save the selection.
5. Preview the assembled instruction context. This is deterministic text assembly, not an LLM response, model inference, tool call or executed test.
6. Create a campaign draft from a real registered target and a profile template. Inspect actual changes in the audit log.
7. Manage model configuration drafts in AI settings: protocol, model ID, endpoint, credential environment-variable reference, advanced options, an explicit default and a review-agent binding. Saving does not call or activate a model.

A Skill explains how an agent should work. It cannot grant approval, override safety policy or enable execution. User-authored content retains its original language; the UI does not invent translations.

AI settings manage multiple model configuration drafts without activating a provider. Profiles remain `not_tested`; API-key values, model discovery, connection tests and failover execution are unavailable. Existing version-1 draft files are validated and migrated in memory on read, then persisted as version 2 on the next authorized mutation. The previous drafts and audit history are preserved; corrupt files are not repaired silently.

## Deliberate boundaries

LIVE run admission, model inference, MCP connection/handshake, traffic generation, instrument control, approvals, verdicts and evidence capture are unavailable. They remain separate implementation/acceptance work from the v2 plan. The server denies the execution endpoints as well as disabling the UI controls. Empty execution/history panels are intentional, not populated with sample telemetry.

Local drafts are stored in `.local/ui-drafts.json` (override `AIDDOS_UI_STATE_PATH`). This single-process JSON store is not the planned PostgreSQL execution store. Keep it private and back it up before experimenting. Never put credentials into target addresses, MCP URLs or Skill instructions; no secrets workflow is implemented. Corrupt existing state must be surfaced, not reset silently.

This build is for loopback development. It has no production login, RBAC, shared/multiprocess store or approved remote deployment. Do not bind it to a public interface or expose it through a tunnel. MCP endpoints are metadata only and are never fetched by draft registration/context preview.

## Verification

```sh
make test
make lint
make build
# First use if Chromium is not installed:
cd web && npx playwright install chromium && cd ..
make test-e2e
```

Browser tests start their own API/UI on loopback ports 5182/5175, use unique state under the configured `TMPDIR` (or project-owned cache), and never seed the development workspace. They do not reuse existing services. Source unit fixtures are test-only. Browser receipts and screenshots are retained under `.hermes/artifacts/ui-01/browser/`; deployment/device/physical-screen-reader acceptance is not implied by those tests.

See `docs/UI_IMPLEMENTATION_CONTRACT.md` for the historical UI-01 contract and `docs/AI_SETTINGS_CONTRACT.md` for the AI-02 extension, exact API and acceptance criteria. Korean usage instructions are in `docs/UI_GUIDE_KO.md` and `docs/AI_SETTINGS_GUIDE_KO.md`; historical UI-01 verification scope and evidence locations are in `docs/UI_VERIFICATION.md`. No commit or push is performed without an explicit request.

AI-02 configuration validation and review coverage are documented in `docs/AI_SETTINGS_VERIFICATION.md`; pinned cross-runtime text semantics and generated-data maintenance are in `docs/AI_SETTINGS_COMPATIBILITY.md`.
