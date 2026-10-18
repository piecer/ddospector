# DDoSpector

AI-Powered DDoS Defense Validation Framework

Find the gaps before attackers do.

AI-powered open-source framework for automated DDoS defense testing, mitigation gap discovery, and security validation.

UI-first implementation of the project in `PLAN.md`. The historical plan is preserved. The initial delivery focuses on the complete layout/menu and real local draft workflows, **not the live test platform**. The description above states the project direction, not completed LIVE capabilities. Naming and compatibility are documented in `docs/NAMING.md`.

## Phase 1: supervised OFFLINE trial

The approved first milestone is implemented and verified: a human-supervised
local workspace, one explicitly selected OFFLINE worker invocation, and actual
stored results in the English/Korean UI. Normal shutdown retains data; reopening
is explicit. This is preparation, not traffic generation or a defense verdict.

After the prerequisites in `docs/PHASE1_LOCAL.md`, use a new durable directory:

```sh
make phase1-local WORKSPACE="$HOME/p1-local"
# Separate terminal: replace the placeholder with the UUID copied from the UI:
make phase1-worker WORKSPACE="$HOME/p1-local" RUN_ID='<exact-run-id>'
# After normal Ctrl-C shutdown, reopen retained data:
make phase1-open WORKSPACE="$HOME/p1-local"
```

Scope and evidence: `docs/PHASE1_ACCEPTANCE.md` and
`docs/PHASE1_SUPERVISED_OFFLINE.md`. Automatic recovery, multiworker operation and
the original full S02 acceptance remain deferred. Existing workspaces use `open`,
not `create`; never delete data or use the legacy daemon to force progress.

## Historical S02 manual-review checkpoint

The immediate delivery goal has changed to a **human-supervised, single-worker,
single-scenario OFFLINE run in a project-owned local environment**. Automatic
recovery and multiworker operation are deferred, not accepted. The current scope
and implementation checklist are in `docs/PHASE1_SUPERVISED_OFFLINE.md`; the
checkpoint description below is historical and does not certify this new goal.

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

The separate CHAT-01 text-chat contract is documented in `docs/CHAT_CONTRACT.md`.
It uses explicit session consent and a supported local, unauthenticated
Chat Completions model; saving configuration or previewing instructions still
does not activate inference. Runtime readiness and conversation results come
from `/api/v1/chat`, not the legacy draft capability flags. Text-only chat remains
the default. The separately consented CHAT-02A companion path is specified in
`docs/CHAT_TOOLS_CONTRACT.md`: native Agent/Skill reads and one exactly approved
Agent name/Skill-assignment write, with conflict checks, audit and stored readback.
Provider settings, MCP assignments and execution are not writable by these tools.
Target/Skill creation and scenario saves remain CHAT-02B; multi-step planning is
CHAT-03. None of these permissions can be inferred from model or Skill text.

LIVE run admission, MCP connection/handshake, traffic generation, instrument control, operational approvals, full defense verdicts and live evidence capture remain unavailable. The legacy LIVE execution endpoint remains denied. The OFFLINE Runs route reads actual run storage; it shows an unavailable state when storage is absent, not fabricated empty history. The supervised Phase-1 path is accepted; full original S02 integration remains unaccepted.

The ordinary API stores drafts in `.local/ui-drafts.json` (override `DDOSPECTOR_UI_STATE_PATH`; legacy `AIDDOS_UI_STATE_PATH` remains supported). This single-process JSON store is separate from PostgreSQL OFFLINE run storage. Ordinary API startup does not provision a database or migrate drafts. Explicit Phase-1 `create` provisions its own database and keeps drafts inside the new private workspace; it does not copy existing drafts. Keep drafts private and back them up before experimenting. Never put credentials into target addresses, MCP URLs or Skill instructions; no secrets workflow is implemented. Corrupt existing state must be surfaced, not reset silently.

S01 scenario histories use a separate file beside the effective draft path, with `.scenarios.json` appended to its filename. The registry holds at most 100 scenario identities and 10 immutable versions per identity. Target/profile snapshots and SHA256 bind each definition; the hash is consistency checking, not authenticated provenance. PCAP fields are declared metadata only. Stale or unacknowledged saves preserve a read-only draft with explicit GET retry, close and discard/reopen controls; no write is automatically replayed.

Scenario storage failures retain at most one 16 MiB managed candidate plus a fixed 4 KiB recovery receipt and deny further saves. Valid history stays readable; GET retry and closing/discarding an editor do not clear storage quarantine. A fresh process may resume a fully verified CLEAN registry with an empty holding directory without a ticket. Other failures require explicit offline inspection and bounded no-overwrite archival, with `--accept-current` available for reviewed incomplete material. See `docs/SCENARIO_STORAGE_RECOVERY.md` for English/Korean commands, one-use startup handoff, interruption handling and the separate per-invocation archive bound. This is not automatic replay, deletion or a power-loss guarantee.

This build is for loopback development. It has no production login, RBAC or approved shared/remote deployment. The draft registry supports one API process; Phase 1 supports one explicitly selected worker. Do not bind it to a public interface or expose it through a tunnel. MCP endpoints are metadata only and are never fetched by draft registration/context preview.

## Verification

For the current Phase-1 scope, run `make test-phase1`, `make test-web`,
`make lint` and `make build`. The dedicated real-browser/operator procedure is
documented in `docs/PHASE1_LOCAL.md`; the full old S02/W2 targets are not replaced
or silently marked passed. The checkpoint description below is historical.

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
