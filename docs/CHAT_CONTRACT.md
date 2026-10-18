# CHAT-01: explicit local-model text chat

Acceptance is recorded per exact source revision and requires feature tests, independent implementation review and real-model browser verification before promotion. This contract is distinct from historical AI-02 draft/preview acceptance and from later configuration-tool/device stages; the contract itself is not an acceptance receipt.

## Supported behavior and authority

The Agent screen supports a conversation with an explicitly selected local model, durable history, streamed text, Stop and truthful errors/restart interruption. Model text is not an action receipt: CHAT-01 cannot read/change project settings through tools, connect MCP, operate devices or generate test traffic. The legacy preview is deterministic and its `GUIDANCE_ONLY` instruction does not become an executor.

The selected model is the AI settings `agent_profile_id`, or `default_profile_id` when the agent binding is null. No first-profile fallback. The operator sees and confirms the literal model and complete completion endpoint when creating a conversation. Saving configuration does not activate a session. A supported configuration is not proof that its model server is healthy or that its model ID exists.

The first adapter is local, unauthenticated OpenAI-compatible Chat Completions: `format=openai`, `http`, host `localhost`, `127.0.0.1` or `::1`, path `/v1` or `/v1/`, optional valid port. The completion path appends `/chat/completions`. `localhost` dials `127.0.0.1` directly while preserving Host. There is no DNS fallback, proxy/environment inheritance, redirect, alternate endpoint, retry, credential lookup or automatic model discovery. Other schemes/hosts/paths/formats and nonempty credential references fail before dispatch; remote HTTPS/authentication support is not claimed.

`streaming` is honored; false is one response, not fake token streaming. `max_tokens=0` omits the field; positive values through4096 use the configured `max_tokens`/`max_completion_tokens` field. Empty thinking/effort, unspecified zero rate and retry attempts -1/0 are supported; positive rate/retry overrides or nonempty thinking/effort are rejected, not ignored. Context capacity remains configuration metadata, not automatic compression. Provider reasoning fields are not persisted/displayed; tool/function calls are never executed.

Legacy workspace OFFLINE mode refers to test execution. Existing workspace/AI-settings false/not_tested flags describe the legacy draft surface; `/api/v1/chat/runtime` is the separate chat capability authority. Existing `/runs`, `/agent/execute`, `/ai-settings/test` and `/ai-settings/models` denials remain unconditional. This remains a single-operator loopback application, not production authentication/RBAC or remote deployment.

## Limits and persistence

One active turn per exclusively owned chat database, no queue. Limits:32 sessions,64 turns/session,8MiB retained decoded text,8192 UTF-8 input bytes,65536 assistant bytes,128KiB provider context JSON,120s total turn including preparation, connect3s/write5s/idle30s. No implicit eviction, truncation, summarization or automatic replay. A limit produces explicit refusal/failure with retained valid partial content.

Conversation storage is a separate `<draft stem>.chat.sqlite3` beside the effective draft file, not a new DraftState field or PostgreSQL schema. Import/create_app/legacy routes do not open or create it. Missing-database reads create neither database nor ownership lock. First session admission creates0600 storage; supported schema/application identity, regular non-symlink paths and owner/non-group/world-writable parent are required. Existing corrupt/unsupported data is preserved. SQLite FULL synchronization/DELETE journal and max-page enforcement cap the database at16MiB; logical text quota is independent. There is no encryption or automatic retention deletion.

An exclusive path owner prevents two runtimes from driving the same history. Existing-database history/turn/event reads can acquire ownership and recover nonterminal turns once; runtime metadata GET never does. Recovery sets interrupted/CHAT_INTERRUPTED, advances revision, timestamps completion, clears active_turn_id and preserves committed text. Never-dispatched work stays not_started/not_dispatched; otherwise transport/provider_stop are unknown. Existing terminal rows are unchanged. Missing and competing-owner states do not create fabricated histories.

Each published partial response is committed before publication. Success requires a complete valid nonblank provider response ending with finish_reason=stop and durable terminal save. EOF, length/filter/tool-call termination, timeout, malformed input, storage failure and cancellation are not success. Failed/partial exchanges remain visible but only prior succeeded pairs enter later model context; a context limit requests a new conversation rather than silently dropping history.

Cancel means request local work/transport retirement. It may not stop remote generation or charges. `cancel_requested` is not `cancelled`; the latter requires local cleanup. Terminal persistence uncertainty closes observation and fences admission; it never creates an in-memory success receipt. No automatic retry after unknown mutation/provider outcomes.

## Closed API v1

All listed keys are required; unknown keys, duplicate JSON and invalid Unicode are rejected. UUID4 applies only to chat-owned IDs/request IDs; profile IDs retain the existing AIIdentifier verbatim. Timestamps are UTC ISO; counters are safe integers. Errors are the existing fixed `{code,message}` envelope without exception/upstream reflection.

Runtime = `{schema_version:1,mode:"chat_only",supported,reason,settings_revision,profile,limits,history:"persistent",configuration_tools:false,live_execution:false,mcp_execution:false}`.
Profile = `{id,name,model,format:"openai",endpoint,streaming}` or null when unsupported/unconfigured.
Limits = `{input_bytes:8192,output_bytes:65536,sessions:32,session_turns:64,history_bytes:8388608,turn_seconds:120}`.

Session = `{schema_version:1,id,request_id,settings_revision,profile_id,model,endpoint,streaming,locale,created_at,sequence,active_turn_id}`. Sequence begins0 and counts admitted turns; it is not the event revision. The full selected profile snapshot is pinned internally.

Turn = `{schema_version:1,id,request_id,session_id,sequence,revision,status,user_text,assistant_text,error_code,transport,provider_stop,created_at,finished_at}`.
Status: accepted/running/cancel_requested/succeeded/failed/cancelled/interrupted. Transport: not_started/open/closed/unknown. Provider stop: not_dispatched/unknown, never confirmed remote cancellation. Nullable fields use explicit null. Revision begins1 and advances on each committed published update.

- GET `/api/v1/chat/runtime`: Runtime, metadata only.
- POST `/api/v1/chat/sessions`: `{request_id,settings_revision,profile_id,approved_endpoint,locale}` ->201 Session; identical replay200. Approval binds exact current selection/endpoint/revision. No provider call at session creation.
- GET `/api/v1/chat/sessions`: `{schema_version:1,sessions}` ordered newest creation first, ID ascending ties, at most32.
- GET `/api/v1/chat/sessions/{id}` with optional exclusive positive `before_sequence`: `{schema_version:1,session,turns,next_before_sequence}`. Latest up to2 eligible turns returned in ascending sequence. Next cursor is smallest returned sequence if older records remain, otherwise null. All older pages stay reachable.
- POST `/api/v1/chat/sessions/{id}/turns`: `{request_id,expected_sequence,text}` ->202 Turn; identical replay200. Request identity includes route session_id plus exact body, so cross-session reuse409. Recheck profile/settings binding before a new dispatch; ongoing work keeps its pinned snapshot. Deduplication precedes busy/stale refusal.
- GET `/api/v1/chat/turns/by-request/{request_id}` and GET `/api/v1/chat/turns/{id}`: authoritative Turn, including uncertain-submit recovery without resending.
- POST `/api/v1/chat/turns/{id}/cancel` with `{}`:200 latest Turn. Idempotent, terminal winner preserved.
- GET `/api/v1/chat/turns/{id}/events?after=N`: SSE below. Unknown/repeated/invalid query parameters are rejected.

## Streaming and browser recovery

SSE uses `event: chat` and one JSON data record:
`{schema_version:1,turn_id,revision,type,turn,text}`.
Snapshot: type=snapshot, full Turn, text=null. Delta: type=delta, turn=null, nonempty text <=4096 UTF-8 bytes. Every published revision has exactly one event. A delta changes only assistant_text and revision; other changes emit a full snapshot. Larger batches split into separate committed revisions. Nonstreaming profiles emit no deltas.

Capture the initial snapshot and register its subscriber under the same publication lock; then emit only revisions greater than that snapshot. Initial snapshot repairs old cursors; future cursors are rejected. Clients replace on snapshots, append each contiguous delta exactly once and reject mismatched turn/order/schema. Terminal snapshot closes the stream. EOF alone is never completion.

Decoded text caps differ from serialization caps: compact ensure_ascii=false JSON responses and downstream SSE data records allow1MiB, including escape-heavy controls. Incomplete downstream frame buffer adds only128 framing bytes. Upstream frame cap remains64KiB; cumulative upstream/downstream data is2MiB each. Downstream budget exhaustion detaches observation, not provider work, and requires GET readback. Event ring<=1024 records/512KiB; at most2 subscribers, each queue<=16 records and1MiB; slow/overflow observers close without blocking Stop/provider cleanup. Stream lifetime<=125s.

Resource byte caps precede UTF-8/JSON interpretation: an oversized upstream raw
frame, cumulative upstream bytes or decoded assistant output produces
`CHAT_OUTPUT_LIMIT`. Within those caps, malformed framing/UTF-8/JSON and missing
or unsupported finish markers produce `CHAT_PROVIDER_PROTOCOL`. A raw frame
excludes its delimiter; receiving a legal boundary-sized frame and its LF/CRLF
delimiter in different network chunks must not change the outcome.

The browser uses two-turn history page replacement, bounded current output, fatal UTF-8 parsing and generation fencing. It preserves unsent text/history on errors and clears input only on accepted receipt. No provider calls or authoritative transcripts in browser storage, no unsafe HTML/Markdown execution. Navigating away detaches observation; the server continues within deadline and history recovers the turn. Explicit Stop uses a separate finite request. Existing assignment edits remain under their original mutation guard; only chat read/history/Stop remain reachable during workspace-refresh failure.

## Verification and delivery

`make test-chat` is the owned local-provider/API protocol suite, included in aggregate test, default pytest collection and lint. Fixture responses are not real-model evidence. Full API/Web/tooling/evidence/lab regressions, lint/build, existing browser flows and source-bound genuine normal Run wire refresh remain required; old W2/HA acceptance is not implied.

Real-model acceptance uses an explicitly selected provider and invocation-owned settings, with actual UI→API→model requests and no Playwright response fulfillment. It covers conversation/context, stored history/reload, local cancellation/remote uncertainty, restart interruption and EN/KO900/390 rendering. Controlled error cases use owned protocol fixtures. Candidate implementations, fixture passes, real-model passes, deployment reconciliation and remaining tool/device stages are reported separately. A provider-only connectivity probe is not this acceptance.
