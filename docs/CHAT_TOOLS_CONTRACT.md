# Approved internal configuration tools (CHAT-02A and CHAT-02B1)

This companion contract extends the text-only chat documented in [CHAT_CONTRACT.md](CHAT_CONTRACT.md). Text-only chat remains the default. Model-endpoint consent is not permission to change project configuration. The legacy workspace's OFFLINE/REVIEW_ONLY flags still describe test execution and deterministic preview; they are not a general-purpose agent execution switch.

## What this slice permits

An operator can permit the exact next message in one of two separate scopes: the existing Agent assignment/Skill reads and one Agent name/Skill-list proposal, or target reads and one target-creation proposal. Agent scope remains the default. Each scope grants read/propose authority only; a separate approval is required for the exact proposed change before publication. Existing MCP assignments, autonomy/execution flags, provider settings and unrelated configuration are preserved.

The only provider tool names are:

- `configuration_read`: Agent assignment, a page of at most ten Skills, or one Skill detail under Agent scope; a page of at most ten targets or one target under target scope.
- `agent_profile_update`: the complete desired Agent name and Skill-ID list, bound to the observed draft revision.
- `target_create`: the desired target name, literal address and DUT/SINK kind, bound to the observed draft revision. Generated ID, timestamp and status cannot be supplied by the model.

These are native provider calls routed to validated internal services, not instructions extracted from assistant prose. Skill instructions and model text are untrusted data and cannot grant authority. Per-grant schemas expose only that scope's two tools, and stored authority is also checked before Call allocation or dispatch; schema omission is not the permission boundary. There are no target update/delete, shell/file, secret, provider endpoint/credential, MCP, network/device, campaign/run or LIVE execution tools. Target creation uses existing syntax validators without DNS resolution, probing or traffic. Traffic profiles remain a read-only catalog. Skill creation and scenario/version saves remain CHAT-02B2/B3; B1 does not complete that broader stage or the original DUT-validation MVP.

## Operator workflow

1. Start a conversation using the existing explicit model/endpoint confirmation.
2. For target creation, first use the existing explicit tool-availability/fence read, then select the enabled target scope. Verify the target-specific consent label and check the separate next-message consent. Agent scope remains available by default. Changing scope clears unused consent. Consent grants no write and is bound to the chosen scope, session, exact message, request identity and sequence.
3. Inspect actual tool activity separately from assistant prose. A valid Agent update displays the current and desired name/Skill list; target creation displays no prior target and the exact proposed name/address/kind. Both show expiry and require their own exact approval.
4. Approve or deny that exact proposal. Approval acknowledges authority; it is not proof that storage succeeded. Any changed proposal needs a new decision.
5. A successful tool result contains the saved configuration, before/after revisions and domain audit. Inspect an Agent update in the existing assignment form or a saved target in the existing Targets inventory. Dirty forms are not silently overwritten. Failed workspace refresh means the save may be verified while that view is stale; retry reads, not the mutation.
6. Reloaded conversations read retained tool facts. A cancelled or failed conversation may still contain a succeeded configuration operation. No UI or model sentence can undo that operation.

This is a single-operator loopback boundary, not authentication or multi-user RBAC. Caller services/settings are not changed merely by opening the interface. A model may lack compatible native-tool behavior despite a syntactically supported provider profile; ordinary text output is never substituted for an executed tool.

## Closed companion API

Existing v1 Session, Turn, ordinary Runtime and text SSE keys remain unchanged. Tool runtime metadata is version2 and lists the three recognized tool names; target grants are a closed version2 variant. Existing Agent grants and other version1 companions remain valid, including their retained records and digests. Companions reject unknown/duplicate keys, invalid UTF-8 and inconsistent identities/states. Session/turn/grant/call/request IDs are canonical UUID4; profile IDs and domain references retain their existing literal validators.

| Method/path below `/api/v1/chat` | Purpose |
| --- | --- |
| GET `/tools/runtime` | Supported profile metadata and fixed tool capability; no provider probe |
| POST `/tool-grants` | Create exact next-message read/propose consent |
| GET `/tool-grants/by-request/{request_id}` | Read back an uncertain grant submission |
| POST `/tool-grants/{id}/revoke` | Revoke unused authority/request cancellation; not rollback |
| POST `/sessions/{id}/tool-turns` | Admit one turn with its bound grant |
| GET `/turns/{id}/tools` | Authoritative bounded tool transcript, including old empty transcripts |
| POST `/tool-calls/{id}/decision` | Approve/deny the exact immutable proposal once |
| GET `/tools/fence` | Current persistent write-fence generation and domain revision observation |
| GET `/tools/targets` | Complete current target inventory and draft revision; operator inspection only, no query parameters or model authority |
| POST `/tools/reconcile` | Explicit operator acknowledgement of uncertainty; never a model tool |

Grant creation requires request_id, session_id, turn_request_id, expected_sequence and text. Text is subject to the existing 8KiB limit; retained authority uses its digest, not another message copy. A grant lasts at most300 seconds and never extends the turn's original deadline. There is at most one pending grant per session and2048 retained grants. Restart expires unused authority rather than renewing it.

The legacy Agent request body is unchanged. Target requests additionally require schema_version=2 and scope=`target_create`; their retained grant has read_scope=`["targets","target"]` and proposal_tools=`["target_create"]`. Reusing a request identity across authority variants conflicts in both directions. The client captures requested authority before POST and binds the returned grant, GET-only recovery and final turn submission to it; a later selector value cannot change a pending submission's authority.

Tool-turn input is the existing request_id/expected_sequence/text plus grant_id. Exact replay returns the original turn without another provider request; ordinary/tool route or grant mismatch conflicts. Approval input is request_id/proposal_digest/decision. Existing decision identity is checked before expiry/terminal checks: exact replay returns its original acknowledgement, changed reuse conflicts. Once a call has any decision, every different decision request ID conflicts, even if it repeats approve. Approval, executing intent and the one-write slot are committed together before the sole producer may dispatch.

A ToolTranscript contains schema_version, turn_id, revision and up to three ordered calls. A Call contains id, index, provider_call_id, tool, arguments, args_digest, grant_id, actor, status, error_code, proposal, decision, result, started_at and finished_at. Actor is operator_authorized_model. Status is requested, awaiting_approval, executing, succeeded, denied, conflict, failed, uncertain or cancelled. Nonterminal states have no result/error/finish time. Terminal states are immutable; only succeeded has a success result. Reads have no proposal/decision. An executing write is an armed durable intent, not proof that publication has occurred.

AgentConfig contains resource_id=`agent-profile`, name and skill_ids; no stored Agent UUID is invented. Read results are discriminated by kind. A successful update includes before_revision, after_revision, the saved AgentConfig and the exact existing AuditEvent. The audit's local_operator origin identifies the authorizing operator; the companion supplies model-call/grant/proposal linkage. Model follow-up receives a bounded success/error tool envelope, never a fabricated success string.

Target proposals additionally bind operation=`target_create` into the canonical digest, with before=null and an exact TargetInput after-value. A target_created result includes before_revision, after_revision, the full six-field Target and the exact target.created/local_operator audit; ID, timestamp, approved input and revision increment must agree. Duplicate names or addresses remain legal and never prove that a particular operation succeeded. Target list reads preserve order with offsets0..100 and limits1..10; detail reads require the actual stored ID.

New failures use fixed nonreflecting CHAT_TOOL_* codes: GRANT_CONFLICT, GRANT_INVALID, APPROVAL_CONFLICT, CONFLICT, WRITE_FENCED, DENIED, LIMIT, PROTOCOL and UNCERTAIN. Existing chat input, busy, timeout, cancellation, storage and retention failures still apply. Invalid native syntax fails before dispatch; oversized valid Skill details produce a bounded failure rather than truncation.

## Actual publication, conflict and recovery

DraftState.audit_total is a conservative single-process CAS token. All existing manual draft writes advance it, including unrelated saves. A mismatch refuses the proposed operation; it does not silently rebase. The worker preserves MCP fields and validates references under the same draft lock used for publication and authoritative disk readback. The final stop/deadline guard runs after temporary serialization/file fsync and immediately before replacement, not merely when the request starts.

Target preparation is effect-free. Both preparation and execution use the session-bound settings revision: draft/settings CAS precedes typed input/quota validation, then audit headroom. The target quota is100. At the safe-integer audit ceiling, creation is refused before a proposal, decision or domain UUID/timestamp allocation; ceiling-minus-one can succeed. The same checks run under the mutation lock. No wire counter range is reduced to conceal overflow.

Draft JSON and chat SQLite are separate commits. An intent must be durable before domain execution. Normal domain acknowledgement, exact lock-held disk readback/new audit, and a durable final tool receipt are all required to report success. A postpublication failure, failed readback or failed receipt commit can leave an uncertain write. Current value equality does not prove that this call owned the write or that earlier durability succeeded. There is no automatic retry or invented distributed transaction.

The chat database migrates validated v1 storage transactionally to v2, beginning the transaction before DDL. Existing messages and idempotency commitments remain intact. Unsupported/corrupt databases and caller sidecars are not replaced. On restart, outstanding write intents become uncertain, unfinished unadmitted work is cancelled, completed results remain, and no model/domain operation is replayed.

An uncertain write fences new tool writes across restart. Inspection does not clear it. Reconciliation requires no active turn/worker, an exact current fence generation and draft revision, and an explicit acknowledgement that prior outcomes remain uncertain. It neither changes domain state nor promotes the old result to success. Fence generation increases on installation and clear and never resets. An old reconciliation receipt's write_fenced=false is historical: UI must obtain a fresh generation-monotone fence GET before enabling writes. An old acknowledgement cannot hide a newer fence.

## Bounds and ownership

- One active ordinary/tool turn, one owned domain worker, no replacement queue.
- At most three tool calls, one proposed/attempted write and four provider requests per turn; no automatic retries.
- One original120-second turn clock covers provider rounds, reads and approval wait. Grants/proposals/reconnect never renew it.
- Existing8KiB input,64KiB assistant text,128KiB encoded request context,64KiB raw upstream frame and32KiB per-response headers; aggregate upstream body2MiB across all rounds.
- Native argument JSON at most16KiB, serialized result32KiB, retained ordered provider exchanges96KiB, companion response1MiB. Count UTF-8 and nested JSON escaping, not characters. Full history is not silently trimmed.
- The operator target inventory is a closed version1 `{schema_version,draft_revision,targets}` response with at most100 unique IDs and a hard128KiB encoded cap. This is not a model read: native reads remain bounded pages/details. The full future provider payload and retained receipt reservations are checked before proposal and again before new approval, including nested escaping and generated-field bounds.
- Tool records share a2MiB logical retention pool, separate from existing8MiB text and16MiB physical database caps. Admission reserves1MiB conservatively for the bounded future record envelope; this can refuse new tool work before actual retained bytes fill the pool. All persisted copies are charged. An uncertain write retains8KiB for later reconciliation. Logical reservation cannot guarantee disk commit success.

Provider client ownership spans all rounds; each response closes before tool execution/approval wait. For a tool turn, transport=open describes that owned local client, not an actively connected socket. Tool-only updates have their own revisions; text events remain contiguous. After observing a terminal Turn, the UI performs a fresh companion read before ending live observation; an earlier in-flight response is not sufficient.

Blocking filesystem work cannot be forcibly interrupted safely. Stop sets a thread-safe signal immediately; after the publication gate it cannot undo the operation. Ownership remains until native work, readback and receipt settlement complete, so the UI may show cancellation pending. Chat metadata requiring the busy worker refuses CHAT_BUSY rather than blocking the event loop; transcript inspection and Stop remain available. Remote provider generation termination remains unconfirmed after local closure.

## Evidence boundaries

Saved-target navigation retains an Application-owned, cloned and validated expectation `{target,after_revision}` of at most4096 UTF-8 bytes, bound to the selected ID. URL/history carry only the ID. The Targets page performs a fresh inventory GET and confirms a receipt only when every returned target field matches and the observed revision meets its floor. It never injects expected bytes into the inventory. Reload/history or other ID-only entry reports current-record-only observation, not historical receipt confirmation. A stale workspace or superseded selection invalidates confirmation and cannot replace independently inspected selected bytes. Target uncertainty inspection uses fence → inventory → fence; current equality never resolves ownership uncertainty.

Startup metadata GETs alone may recover a definite CHAT_BUSY response with at most three attempts, spaced at least 500ms after response completion. Tool runtime and fence reads are serialized. Cancellation, unmount or a newer read cancels this recovery; other failures remain explicit. This does not retry grants, decisions, turns, reconciliation writes or model requests, and never provisionally enables authority.

New decision admission rechecks live owner/Stop and the original monotonic deadlines after preparation, then samples UTC again before recording the decision and write intent. Expired new approval is refused without consuming the write slot; exact historical replay remains first. The browser acceptance harness owns port5175 to match the existing Origin allowlist, refuses collisions, and never expands the backend's Origin policy.

Controlled protocol/fault/approval tests, a genuine selected-model mutation, independent storage/UI readback, and caller deployment are distinct gates. A native-tool capability probe is not evidence of a configuration write. A simulated provider is not real-model acceptance. Source-UI tests do not imply that a caller's stopped service was restarted or its model configuration rewritten.

The CHAT-02A core checkpoint has a separate open final-model-explanation acceptance item: successful storage does not imply a successful final model reply. B1 preserves those saved facts and does not change that model budget or claim selected-model target-creation acceptance. The acceptance harness's explicit `--fixture-case agent|target` selector is fixture-only and is rejected outside fixture mode; its default remains Agent. Fixture responses are synthetic even when the API, JSON/SQLite persistence, browser and raw producer captures are real executions.
