# UI-01: control workspace contract

Status: implementation authorized by the user on 2026-10-09; UI/layout/menu-first slice, not the entire v2 live platform. Preserve PLAN.md and both historical plans. No device access, traffic emission, automatic MCP connection, package execution from a Skill, or operational approval in this slice. No commit/push was explicitly requested; leave verified changes unstaged.

## Product clarification

AI control includes assigning versioned Skills (instructions, procedures, prerequisites, evidence requirements, safety guidance) and MCP server usage instructions to an agent profile. A Skill is guidance, not execution authority. MCP bindings and the future Safety Gate remain authoritative. This slice implements the Skill/MCP assignment UI, durable local draft configuration, and deterministic context preview. It must NOT simulate model responses or claim an MCP handshake/device test.

## Layout and menu

Brand: Aegis Lab / AI defense validation. Dark technical workspace, restrained mint/cyan accent, legible hierarchy, 248px collapsible left navigation, 64px topbar, responsive content, keyboard-visible focus. System font stack with Korean fallback; no runtime CDN dependency.

Topbar: breadcrumb/page title, OFFLINE badge, backend connectivity, English/한국어 selector, context action. Sidebar bottom: LOCAL DEVELOPMENT, LIVE locked, version.

14 routes, grouped:
- Workspace: /overview, /campaigns, /runs, /findings, /evidence
- Lab configuration: /targets, /instruments, /mcp-servers, /profiles
- AI & governance: /agent, /skills, /approvals
- System: /audit, /settings

The exact root path / is an overview alias; genuine unknown paths remain not-found. Direct links, browser history and locale persistence retain the same behavior.

Primary workspace: current readiness and setup steps, real counts, a visible static topology of intended components clearly labelled not live telemetry, recent actual draft activity. No invented campaigns, packet counts, findings, connected equipment or passed tests.

Each menu has a distinct page, bilingual copy, useful empty/loading/error states, relevant contextual action and honest implementation-state labels. Future controls are disabled with an adjacent reason, not silent/no-op clickable buttons. Tables are keyboard-scrollable labelled regions; no clipped operational columns. 1440px, 1024px and 390px layouts are verified in a real browser.

## Technology and local serving

React + TypeScript + Vite; lucide-react icons; Vitest + Testing Library; Playwright. Python 3.12 project environment, FastAPI/Pydantic, pytest/Ruff. Dependency versions locked from package registry resolution. Parent owns root Makefile, web package/config/lockfiles, shared components and main app.

Default local processes: web 127.0.0.1:5173, API 127.0.0.1:5180. Never stop unrelated services (9001, 8000, 8090, 3000 etc were occupied). Vite proxies /api to API. Production build can be served later through the same origin. Stage is loopback-only, no production authentication claim.

The API stores ONLY UI drafts in an owned JSON file (default .local/ui-drafts.json, configurable AIDDOS_UI_STATE_PATH). This is not the future PostgreSQL execution store and must be clearly documented. Existing corrupt state must not be overwritten. Atomic replace + lock for this single-process development service; no multiprocess durability claim. Never persist secrets or run arbitrary commands.

## Shared TypeScript contract

Canonical shared types will be in web/src/lib/contracts.ts. All pages export named React components and accept PageProps { data: WorkspaceSnapshot; locale: 'en'|'ko'; navigate: (route: RouteId) => void; refresh: () => Promise<void> }.

LocalizedText = { en:string; ko:string }; display via text(value, locale). User-authored names/instructions retain original text in both locale slots; no fabricated translations.

WorkspaceSnapshot:
- meta: { version:string; mode:'OFFLINE'; live_enabled:false; live_limit:1; storage:'local_drafts'; deployment:'loopback_development' }
- targets: Target[] { id, name, address, kind:'DUT'|'SINK', status:'draft', created_at }
- instruments: Instrument[] { id, name, role, status } (initially empty, no create in this slice)
- mcp_servers: McpServer[] { id, name, endpoint, transport:'streamable_http'|'stdio', usage_instructions, status:'draft', tools_count:0, created_at }
- profiles: TrafficProfile[] { id, name:LocalizedText, description:LocalizedText, engine:'tcpreplay'|'tcpdump'|'k6', layer:string, status:'template' }
- skills: Skill[] { id, name:LocalizedText, description:LocalizedText, instructions:LocalizedText, version:string, category:'planning'|'measurement'|'analysis', status:'template'|'draft', allowed_operations:string[], required_capabilities:string[], safety_rules:LocalizedText[] }
- agent_profile: { name:string, skill_ids:string[], mcp_server_ids:string[], autonomy:'REVIEW_ONLY', execution_enabled:false }
- campaigns: Campaign[] { id, name, objective, target_id, profile_id, status:'draft', created_at }
- runs: []; findings: []; evidence: []; approvals: []
- audit: AuditEvent[] { id, action:string, entity_id:string, created_at:string, origin:'local_operator' }
- capabilities: { draft_editing:true, context_preview:true, live_execution:false, mcp_connect:false, llm_inference:false }

Built-in catalog: three real instruction templates policy-validation, mcp-measurement, evidence-analysis; three profile templates tcpreplay-policy, tcpdump-observer, k6-http. Templates are not executed/approved assets. Do not seed fake history or connections.

## API (same-origin /api/v1)

GET /health -> {status:'ok',version:'0.1.0-ui',mode:'OFFLINE'}
GET /workspace -> WorkspaceSnapshot, deep fresh projection
POST /targets {name,address,kind} -> 201 Target
POST /mcp-servers {name,endpoint,transport,usage_instructions} -> 201 McpServer
POST /skills {name,description,instructions,category} -> 201 Skill
PUT /agent-profile {name,skill_ids,mcp_server_ids} -> 200 AgentProfile
POST /campaigns {name,objective,target_id,profile_id} -> 201 Campaign
POST /agent/preview {goal,locale:'en'|'ko'} -> {origin:'deterministic_context_preview',execution_enabled:false,prompt:string,skill_ids:string[],mcp_server_ids:string[]}
POST /runs -> 409 {code:'LIVE_NOT_AVAILABLE',message:string}; never admits work
POST /agent/execute -> 409 {code:'AGENT_EXECUTION_NOT_AVAILABLE',message:string}; no inference/network

Closed schemas extra=forbid, strings bounded (name <=120, address <=255, endpoint <=512, description <=1000, objective/goal <=2000, instructions <=8000), no blank required strings, finite enums. targets are draft data only; reject control characters/invalid address, accept valid IP or hostname. MCP draft: only http/https endpoint for streamable_http with no userinfo, query string or fragment; stdio endpoint is a local registered identifier (not a command) matching [a-z][a-z0-9-]{0,63}. No network call at registration or preview. Instructions stay data and never grant authority. Body <=256 KiB; unknown fields rejected. At most 100 drafts of each entity; audit bounded to 500 most recent. The API also returns meta.audit_retention {limit, retained, total_recorded, dropped}; the shared UI type lists its consumed metadata subset. Lists themselves have hard admission caps rather than claimed pagination this slice.

All mutations require application/json and reject untrusted Origin (allow only exact loopback development origins on ports 5173 and test 5175 and API 5180/5182). No CORS wildcard. API binds loopback. Dev defaults must not present production-ready auth. Errors are stable and sanitized, not paths/exception text. Same-origin browser fetch must surface non-2xx errors. Read-only GET must never initialize fake execution state.

## UI primitives (parent-owned)

web/src/components/ui.tsx exports:
- PageHeader({eyebrow?,title,description?,actions?})
- Panel({title?,description?,actions?,children,className?})
- Badge({tone?:'neutral'|'success'|'warning'|'danger'|'info',children})
- EmptyState({icon?:ReactNode,title,description,action?:ReactNode})
- Button({variant?:'primary'|'secondary'|'ghost'|'danger',...native button props})
- Field({label,hint?,children})
- Notice({tone?:'info'|'warning'|'danger'|'success',children})
- Dialog({open,title,onClose,children,recoveryOnly?}) native dialog/focus restore/escape; recoveryOnly is restricted to already-committed read-only recovery
- DataTable({label,children}) labelled keyboard-scrollable wrapper around caller-supplied table

Utilities: web/src/lib/i18n.ts exports text(value,locale), choose(locale,en,ko), formatDate(value,locale).

Loading or stale workspace snapshots disable page mutations. After a committed target/MCP save, only its read-only retry/dismissal dialog may escape that disabled fieldset. Failed GET recovery never repeats the POST. The original dialog invoker survives the recovery portal transition; successful readback restores focus to it when available. Dismissal consumes that focus obligation, so later settlement cannot steal focus from newer work. Unsaved and sibling dialogs retain the mutation boundary.
web/src/lib/api.ts exports api.getWorkspace(), createTarget(input), createMcpServer(input), createSkill(input), saveAgentProfile(input), createCampaign(input), previewContext(input). All methods return typed promises and throw a sanitized Error. Do not add new global dependencies without parent agreement.

CSS shared classes: .page-stack, .grid-two, .grid-three, .metric-grid, .metric-card, .metric-value, .muted, .mono, .button-row, .form-stack, .form-grid, .section-label, .table, .table-actions, .text-link, .detail-list, .item-card, .chips, .split-layout. Page-specific CSS files allowed only in owned directories and imported by those pages. Use var(--bg), --panel, --panel-raised, --border, --text, --muted, --accent, --danger, --warning.

## Parallel ownership

No authorized Git commits and no HEAD yet: parent creates isolated owned source copies from one exact manifest, not shared-checkout child edits. Child dirs contain contract/shared scaffold + own node_modules link and local Vite cacheDir. Never edit the active repository from a child.

A backend owner: src/aiddos/**, tests/api/**, pyproject.toml, uv.lock, .python-version. Own tests and real API/store; no frontend/Makefile edits.
B operations owner: web/src/pages/operations/** and web/src/pages/operations/operations.test.tsx. Exports CampaignsPage, RunsPage, FindingsPage, EvidencePage, ApprovalsPage, AuditPage. Campaign draft creation functional; other execution data honestly empty.
C lab owner: web/src/pages/lab/** and its tests. Exports TargetsPage, InstrumentsPage, McpServersPage, ProfilesPage, SettingsPage. Target/MCP draft creation functional; server connects/instrument controls disabled; profiles template detail functional.
D AI owner: web/src/pages/ai/** and its tests. Exports AgentPage, SkillsPage. Create/inspect Skill, assign Skills/MCP, save profile, preview compiled instructions through real API; no simulated LLM reply.
Parent: shared types/api/primitives/styles, App/sidebar/navigation/Overview, configs/Makefile/docs, integration, browser E2E and final review.

Every child: strict behavior RED before GREEN, own focused tests, no Git mutations, no external device calls, final changed-path manifest + source hashes + tests and limitations. Return complete source files in own allowed paths, no abandoned stubs. Parent validates absent/preimage hashes then integrates only owned paths and runs fresh canonical verification.

## Acceptance of UI-01

All 14 routes reachable; coherent responsive layout; complete en/ko controls and warnings; direct deep links/back behavior; working draft creation/persistence; working Skill and MCP assignment/context preview; actual API outage/error display with retry; no fake executions and LIVE remains server-side denied. Real-browser tests against real API at desktop/narrow widths, keyboard/dialog behavior, no console errors or document overflow. Independent review before final completion. Remaining v2 backend/MCP/device/LLM gates stay explicitly unimplemented.
