# AI-02: model configuration drafts

Status: configuration implementation and independent acceptance complete. Fresh active-tree integration evidence is recorded separately in `.hermes/artifacts/ai-02/final/verification.json`; see `AI_SETTINGS_VERIFICATION.md` for scope. This extends UI-01 configuration only. Model/device execution remains outside this scope.

## Configuration scope

This document governs the legacy configuration/preview endpoints, not the separate
CHAT-01 text-chat runtime. See `CHAT_CONTRACT.md` for explicit chat-session consent,
supported local providers, durable conversations and runtime capability/status.
The stored `execution_enabled=false` and `connection_status=not_tested` fields
describe configuration drafts; they are not a measurement of an active chat.
Saving a profile still performs no inference, and all legacy denial endpoints below
remain denied. CHAT-01 does not resolve credential environment references.

Included: multiple named profiles; protocol is distinct from vendor; manual model ID and Base URL; explicit default; independent streaming/context/output/thinking/effort controls; profile-level connect/empty/stream retry overrides.

Unavailable: plaintext API-key storage, arbitrary proxy/session headers, runtime provider activation, health claims, model discovery, connection/completion tests, automatic failover, global retry/pool machinery, or autonomous task execution. Connection tests and model discovery are disabled in the UI and denied by the server.

## User surface

- New `/ai-settings` route, under AI & governance; English `AI settings`, Korean `AI 설정`. Existing 14 routes remain, total 15.
- Profile cards show name, protocol, complete model/endpoint text (wrap rather than clip), credential-reference presence, explicit `Draft / Not tested`, default/binding badges.
- Native accessible dialog for create/edit; delete requires an explicit confirmation dialog. The default or agent-bound profile cannot be removed until the binding is cleared/changed.
- Basic fields: name, protocol, model ID, optional Base URL, optional API-key environment-variable reference. There is no API-key-value input and no browser persistence of profile values.
- Expandable advanced settings distinguish total context capacity from output-token limit, and thinking toggle from reasoning effort. Numeric 0 retains its documented unset/default meaning; do not silently turn invalid input into zero.
- Explicit controls choose the default draft and the model draft associated with the existing review agent; an empty agent binding follows the default draft. Both can remain unset; creating the first profile must not implicitly select it.
- Saving/binding does not activate a provider. Connection test/model discovery remain disabled with adjacent reason. No fabricated health, replies or latency.
- Links from existing agent and system settings pages make the new screen discoverable.
- Responsive at 1440/1024/390px; keyboard dialog focus; all error/recovery controls remain reachable.

## Closed wire contract

All field names below are exact. All request fields are required, including explicit empty strings/nulls/default values. Unknown fields (especially api_key, headers, enabled) are rejected. Existing strict JSON, Origin, host, UTF-8 and 256 KiB body boundaries apply.

`GET /api/v1/ai-settings` -> `AISettingsSnapshot`

`PUT /api/v1/ai-settings` accepts `{revision, profiles, default_profile_id, agent_profile_id}` and returns the complete authoritative `AISettingsSnapshot` on 200. One atomic replacement is the sole mutation primitive for profile create/edit/delete/default/binding changes.

`AISettingsSnapshot`:
- `revision`: safe integer 0..9007199254740991, initially 0; increment once per accepted PUT.
- `profiles`: AIModelProfile[], at most 20, initially [].
- `default_profile_id`: profile ID or null, initially null.
- `agent_profile_id`: profile ID or null, initially null (follow default).
- `updated_at`: timezone-aware ISO timestamp or null initially.
- `execution_enabled`: literal false.
- `connection_status`: literal `not_tested`.

`AIModelProfile` (all fields required):
- `id`: ASCII identifier `[a-z][a-z0-9_-]{0,63}`; stable across edits. UI generates `llm-` plus a UUID when opening a new profile draft.
- `name`: 1..120 characters, nonblank, no surrounding whitespace or control characters; unique using casefold comparison.
- `format`: `anthropic` | `openai` | `openai-responses`. `openai` means Chat Completions, not a vendor restriction.
- `model`: 1..200 characters, nonblank, no surrounding whitespace or control characters. Preserve the literal identifier.
- `base_url`: empty or an absolute HTTP(S) URL, <=512 characters; valid hostname/port; no userinfo (including empty userinfo), query, fragment, backslash, whitespace/control characters or percent-encoded authority. It is draft metadata only: no DNS or connection during validation.
- `credential_env`: empty or `[A-Z][A-Z0-9_]{0,63}`. This is a future server environment-variable reference, not a key. Do not look up, return, log or test any environment value.
- `rate_per_second`: integer 0..1000000; 0 = no profile-specific rate limit specified.
- `rate_per_minute`: integer 0..1000000; 0 = no profile-specific rate limit specified.
- `context_window_k`: integer 0..1000; 0 = reference default 200K, nonzero must be >=32. Total context capacity for a future local compression policy, not an output budget.
- `streaming`: boolean, new-profile default true.
- `max_tokens`: integer 0..1000000; 0 = omit output cap in a future request.
- `max_tokens_field`: empty | `max_completion_tokens`; nonempty is valid only with `format=openai`; empty means protocol default (`max_tokens` for Chat Completions).
- `thinking_type`: empty | `disabled` | `enabled`.
- `reasoning_effort`: empty | `low` | `medium` | `high` | `xhigh` | `max`.
- `retry`: `{connect: RetryRule, empty: RetryRule, stream: RetryRule}`.
- `RetryRule`: `{attempts: integer -1..20, interval_ms: integer 0..3600000}`. Attempts -1 = disable that retry layer, 0 = inherit default, positive = count; interval 0 = inherit/default strategy. New-profile rules are all zero. Stored policy only, not an implemented retry engine.

The PUT revision is the previously read revision, maximum 9007199254740990. Reject mismatch with 409 `AI_SETTINGS_CONFLICT`; it performs no write or audit mutation. Both selected IDs must exist in profiles; duplicates, dangling references or contradictory protocol options return sanitized 422. Identity/name uniqueness is checked over the entire submitted snapshot. IDs and names are not silently normalized by the API.

`POST /api/v1/ai-settings/test` and `POST /api/v1/ai-settings/models` -> 409 `AI_CONNECTION_NOT_AVAILABLE`, without storage reads, secret/environment lookups, DNS, network, jobs or inference. Existing `/runs` and `/agent/execute` denials remain unchanged and unconditional.

## Persistence and compatibility

Use the existing single-process DraftStore lock/atomic replace mechanism, not a second unaudited store. Add `ai_settings` to a version-2 persisted DraftState. UI-01 version-1 state is accepted ONLY through explicit exact-schema migration: validate every original required field and invariant, reject unknown or missing old fields, add the empty AI settings state in memory, advance format_version to 2. GET must not rewrite old bytes. The next authorized draft mutation publishes version 2 while preserving all prior data and audit.

Version-2 persisted state must include the complete AI settings image; missing fields are corruption, not legacy defaults. Preserve corrupt files unchanged. Add one `ai_settings.updated` audit event with entity_id `ai-settings` per accepted PUT under the same lock. Reuse the existing audit cap, safe counter, sanitized errors and uncertain-post-replace outcome. Do not change the existing `/workspace` shape or execution capabilities; new settings are retrieved through their dedicated endpoint.

GET must return a fresh projection; modifying a prior response cannot mutate storage. Same-process app instances targeting one file share the existing path lock. No new multiprocess, authentication, encryption or production-readiness claim.

## Client lifecycle

- AI settings requests have a 10-second timeout; cleanup timers/listeners and fence unmounted/stale responses. Read failure is not an empty profile list.
- PUT uses the revision of the displayed snapshot. Never automatically rebase a user's old edits onto a newly read revision or automatically repeat a mutation after a timeout/503/conflict.
- On success adopt the authoritative PUT response; an extra GET is not a prerequisite for acknowledging that success.
- On an uncertain save/conflict, preserve the local form for inspection but lock new mutations until explicit reload. Make close and read-only recovery accessible. Recovery must warn when it discards the local edit; it cannot silently overwrite newly saved settings.
- Close during a pending mutation remains possible; late settlement must not reopen a dialog or move focus into newer work. Do not relax the App's existing stale-workspace fieldset boundary or portal unsaved forms around it.
- Clear form state between profiles; no stale advanced values from another profile. Changing away from Chat Completions explicitly resets the incompatible max_tokens_field control, with visible protocol guidance.
- Existing workspace audit refresh may happen after acknowledged save, but must not turn a successful settings save into a claimed failed mutation or permit a duplicate PUT.

## Verification/ownership

Backend candidate owns `src/aiddos/api/{ai_settings.py,models.py,store.py,app.py,errors.py}` and `tests/api/test_ai_settings.py`; narrowly extend existing API tests only for explicit format-version compatibility, without weakening assertions. No dependency changes.

Frontend candidate owns `web/src/pages/ai-settings/**` (types, API client, page/editor/styles and tests). Export named `AISettingsPage` taking existing PageProps from `web/src/pages/ai-settings/index.ts`. Do not edit global routing, App, shared Dialog, existing pages, manifests or dependencies.

Parent owns navigation/registry/link integration, docs, browser E2E, independent review and promotion. Candidates use isolated owned checkouts; no source changes in the active repo, no stage/commit/reset/push, no unrelated process or artifact cleanup.

Required gates: strict RED->GREEN slices; full existing API/UI regression; explicit legacy read/no-write and next-write migration; corruption preservation; CAS race/conflict with zero duplicate writes; bounds/credential-field rejection; deep projection; actual execution denial with corrupt storage; full browser create/edit/default/agent-binding/reload/delete; held/failed saves and late responses; en/ko; responsive/keyboard/automated accessibility; no external requests or browser profile persistence. Canonical `make test`, `make lint`, `make build`, `make test-e2e` after integration; read-only independent acceptance before completion. Original user PLAN.md and historical UI-01 plans remain intact.
