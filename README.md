# Aegis Lab · AI defense validation workspace

UI-first implementation of the project in `PLAN.md`. The historical plan is preserved. The initial delivery focuses on the complete layout/menu and real local draft workflows, **not the live test platform**.

## S02 manual-review checkpoint

This checkout includes the OFFLINE Runs UI and its candidate API/worker implementation
for manual review. It is **not a completed S02 release**. At the user's request,
backend and real-browser integration acceptance are deferred for this checkpoint.
See `docs/S02_REVIEW_CHECKPOINT.md` for the verified scope, known gaps and review steps.
No LIVE traffic, device control or defense evaluation is enabled.

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
8. In Traffic profiles, create a scenario using registered DUT/SINK targets, explicit expected policy, observation criteria, traffic budgets and required evidence. Open Scenario history to inspect a frozen revision or edit its latest version. Every save appends a new immutable version and verifies the returned record against its history; it never authorizes or starts execution.

A Skill explains how an agent should work. It cannot grant approval, override safety policy or enable execution. User-authored content retains its original language; the UI does not invent translations.

AI settings manage multiple model configuration drafts without activating a provider. Profiles remain `not_tested`; API-key values, model discovery, connection tests and failover execution are unavailable. Existing version-1 draft files are validated and migrated in memory on read, then persisted as version 2 on the next authorized mutation. The previous drafts and audit history are preserved; corrupt files are not repaired silently.

## Deliberate boundaries

LIVE run admission, model inference, MCP connection/handshake, traffic generation, instrument control, approvals, verdicts and evidence capture are unavailable. The legacy LIVE execution endpoint remains denied. The new OFFLINE Runs route reads actual run storage; it shows an unavailable state when storage is absent, not fabricated empty history. Its candidate backend integration remains unaccepted.

Local drafts are stored in `.local/ui-drafts.json` (override `AIDDOS_UI_STATE_PATH`). This single-process JSON store is separate from the candidate PostgreSQL OFFLINE run store. No automatic database provisioning or draft migration is performed. Keep drafts private and back them up before experimenting. Never put credentials into target addresses, MCP URLs or Skill instructions; no secrets workflow is implemented. Corrupt existing state must be surfaced, not reset silently.

S01 scenario histories use a separate file beside the effective draft path, with `.scenarios.json` appended to its filename. The registry holds at most 100 scenario identities and 10 immutable versions per identity. Target/profile snapshots and SHA256 bind each definition; the hash is consistency checking, not authenticated provenance. PCAP fields are declared metadata only. Stale or unacknowledged saves preserve a read-only draft with explicit GET retry, close and discard/reopen controls; no write is automatically replayed.

Scenario storage failures retain at most one 16 MiB managed candidate plus a fixed 4 KiB recovery receipt and deny further saves. Valid history stays readable; GET retry and closing/discarding an editor do not clear storage quarantine. A fresh process may resume a fully verified CLEAN registry with an empty holding directory without a ticket. Other failures require explicit offline inspection and bounded no-overwrite archival, with `--accept-current` available for reviewed incomplete material. See `docs/SCENARIO_STORAGE_RECOVERY.md` for English/Korean commands, one-use startup handoff, interruption handling and the separate per-invocation archive bound. This is not automatic replay, deletion or a power-loss guarantee.

This build is for loopback development. It has no production login, RBAC, shared/multiprocess store or approved remote deployment. Do not bind it to a public interface or expose it through a tunnel. MCP endpoints are metadata only and are never fetched by draft registration/context preview.

## Verification

For this S02 checkpoint, Web unit tests, lint, type checking and build are the
included verification scope. Run `make setup`, `make test-web`, then the Web lint,
typecheck and build scripts. The historical full-stage commands below include
backend/browser gates that are **not accepted or executed for this checkpoint**;
some retained backend/browser probes still require campaign-specific inputs.

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

The current sequential development and per-stage commit contract is `docs/IMPLEMENTATION_CAMPAIGN.md`. S01 behavior and acceptance criteria are in `docs/stages/S01_SCENARIOS.md`; Korean scenario instructions are in `docs/SCENARIOS_GUIDE_KO.md`. Stage verification records distinguish isolated browser acceptance from active-service, real-model and physical-device tests.

S01 implementation, independent review, failure/recovery coverage and verification limitations are recorded in `docs/SCENARIOS_VERIFICATION.md`.
