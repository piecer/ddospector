# Approved internal configuration tools (CHAT-02A, CHAT-02B1 and CHAT-02B2)

The B2 and stage 1–3 sections below retain their checkpoint boundaries. The
current B3 candidate extends public dispatch as described in **Public scenario
workflow (stage 4 candidate)**; earlier public-v4-closed statements describe
those predecessor checkpoints, not this candidate. Implementation, offline
qualification, selected-model acceptance and deployment remain distinct.

This companion contract extends the text-only chat documented in [CHAT_CONTRACT.md](CHAT_CONTRACT.md). Text-only chat remains the default. Model-endpoint consent is not permission to change project configuration. The legacy workspace's OFFLINE/REVIEW_ONLY flags still describe test execution and deterministic preview; they are not a general-purpose agent execution switch.

## What this slice permits

An operator can permit the exact next message in one of three closed scopes: the existing Agent assignment/Skill reads and one Agent name/Skill-list proposal (Agent v1), target reads and one target-creation proposal (Target v2), or Skill reads and one custom draft Skill-creation proposal (Skill-only v3). Agent scope remains the default. Each scope grants read/propose authority only; a separate approval is required for the exact proposed change before publication. Existing MCP assignments, autonomy/execution flags, provider settings and unrelated configuration are preserved.

The only provider tool names are:

- `configuration_read`: Agent assignment, a page of at most ten Skills, or one Skill detail under Agent scope; a page of at most ten targets or one target under Target scope; only the existing Skill page/detail reads under Skill scope. Model Skill reads remain localized summaries/details, not full bilingual operator records.
- `agent_profile_update`: the complete desired Agent name and Skill-ID list, bound to the observed draft revision.
- `target_create`: the desired target name, literal address and DUT/SINK kind, bound to the observed draft revision. Generated ID, timestamp and status cannot be supplied by the model.
- `skill_create`: the exact name, description, instructions and category of a custom draft Skill, bound to the observed draft revision. Generated ID, version, locales, policy, status and assignment cannot be supplied by the model.

These are native provider calls routed to validated internal services, not instructions extracted from assistant prose. Skill instructions and model text are untrusted data and cannot grant authority. Per-grant schemas expose only that scope's two tools, and stored authority is also checked before Call/exchange allocation or dispatch; schema omission is not the permission boundary. There are no target or Skill update/delete, Skill version-append, shell/file, secret, provider endpoint/credential, MCP, network/device, campaign/run or LIVE execution tools. Target creation uses existing syntax validators without DNS resolution, probing or traffic. Skill creation neither assigns nor executes the new draft. Traffic profiles remain a read-only catalog for these tools. Chat-driven scenario creation/version saves remain CHAT-02B3 and multi-step planning remains CHAT-03; B2 does not complete the broader stage or the original DUT-validation MVP.

## Operator workflow

1. Start a conversation using the existing explicit model/endpoint confirmation.
2. For Target or Skill creation, first use the existing explicit tool-availability/fence read, then select the enabled scope (Create Skill / 스킬 생성 for B2). Verify the scope-specific consent label and check the separate, initially unchecked next-message consent. Agent scope remains available by default. Changing scope clears unused consent; unresolved grant/send/turn/decision work disables switching. Consent grants no write and is bound to the chosen scope, session, exact message, request identity and sequence. An unchecked send remains text-only.
3. Inspect actual tool activity separately from assistant prose. A valid Agent update displays the current and desired name/Skill list; target creation displays no prior target and the exact proposed name/address/kind. Skill creation shows the entire literal name/description/instructions/category, draft revision, expiry and digest as inert text, not executable markup or instruction-derived links. Creation has no prior record. Each proposal requires its own exact approval; shortened text is not complete approval.
4. Approve or deny that exact proposal. Approval acknowledges authority; it is not proof that storage succeeded. Any changed proposal needs a new decision.
5. A successful tool result contains the saved configuration, before/after revisions and domain audit. Inspect an Agent update in the existing assignment form, a saved target in the existing Targets inventory, or a saved Skill in existing Skills details. Saved labels/links require a validated receipt, not prose or approval acknowledgement alone. Dirty forms are not silently overwritten. Failed workspace refresh means the save may be verified while that view is stale; retry reads, not the mutation.
6. Reloaded conversations read retained tool facts. A cancelled or failed conversation may still contain a succeeded configuration operation. No UI or model sentence can undo that operation.

This is a single-operator loopback boundary, not authentication or multi-user RBAC. Caller services/settings are not changed merely by opening the interface. A model may lack compatible native-tool behavior despite a syntactically supported provider profile; ordinary text output is never substituted for an executed tool.

## Closed companion API

Existing v1 Session, Turn, ordinary Runtime and text SSE keys remain unchanged. Tool runtime metadata is version3 with ordered tools `[configuration_read,agent_profile_update,target_create,skill_create]` and unchanged other fields/limits. Target and Skill grants are distinct closed version2/version3 variants. The client still accepts exact runtime v1/v2, but Skill mode requires v3; older clients may fail closed on v3 without changing plain chat. Existing Agent grants and other version1 companions remain valid, including their retained records and digests. Companions reject unknown/duplicate keys, invalid UTF-8 and inconsistent identities/states. Session/turn/grant/call/request IDs are canonical UUID4; profile IDs and domain references retain their existing literal validators.

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
| GET `/tools/skills` | Current localized-name summaries and draft revision; operator inspection only, no query parameters or model authority |
| GET `/tools/skills/{skill_id}` | One full actual Skill and draft revision; operator inspection only, no query parameters or audit |
| GET `/tools/scenarios/state` | Read-only scenario registry revision and quarantine observation; no query parameters, recovery or model authority |
| POST `/tools/reconcile` | Explicit operator acknowledgement of uncertainty; never a model tool |

Grant creation requires request_id, session_id, turn_request_id, expected_sequence and text. Text is subject to the existing 8KiB limit; retained authority uses its digest, not another message copy. A grant lasts at most300 seconds and never extends the turn's original deadline. There is at most one pending grant per session and2048 retained grants. Restart expires unused authority rather than renewing it.

The legacy Agent request body is unchanged and unversioned; explicitly adding schema_version=1 remains invalid. Target requests additionally require schema_version=2 and scope=`target_create`; their retained grant has read_scope=`["targets","target"]` and proposal_tools=`["target_create"]`. Skill requests require schema_version=3 and scope=`skill_create`, with read_scope=`["skills","skill"]` and proposal_tools=`["skill_create"]`; v3 has no proposal_fields. All six ordered substitutions between the three authorities conflict with CHAT_TOOL_GRANT_CONFLICT before a new grant is allocated. Exact replay never renews expiry or widens authority. The client captures requestedAuthority=`agent_v1|target_create_v2|skill_create_v3` before POST and binds the exact variant, scope and request/session/turn/text/profile/settings/sequence commitments on the returned grant, GET-only recovery and final turn submission; mismatch sends no tool turn. A later selector value cannot change a pending submission's authority. Default Agent schemas and Target-only schemas retain their legacy behavior; wrong-scope calls fail CHAT_TOOL_DENIED before dispatch.

Tool-turn input is the existing request_id/expected_sequence/text plus grant_id. Exact replay returns the original turn without another provider request; ordinary/tool route or grant mismatch conflicts. Approval input is request_id/proposal_digest/decision. Existing decision identity is checked before expiry/terminal checks: exact replay returns its original acknowledgement, changed reuse conflicts. Once a call has any decision, every different decision request ID conflicts, even if it repeats approve. Approval, executing intent and the one-write slot are committed together before the sole producer may dispatch.

A ToolTranscript contains schema_version, turn_id, revision and up to three ordered calls. A Call contains id, index, provider_call_id, tool, arguments, args_digest, grant_id, actor, status, error_code, proposal, decision, result, started_at and finished_at. Actor is operator_authorized_model. Status is requested, awaiting_approval, executing, succeeded, denied, conflict, failed, uncertain or cancelled. Nonterminal states have no result/error/finish time. Terminal states are immutable; only succeeded has a success result. Reads have no proposal/decision. An executing write is an armed durable intent, not proof that publication has occurred.

AgentConfig contains resource_id=`agent-profile`, name and skill_ids; no stored Agent UUID is invented. Read results are discriminated by kind. A successful update includes before_revision, after_revision, the saved AgentConfig and the exact existing AuditEvent. The audit's local_operator origin identifies the authorizing operator; the companion supplies model-call/grant/proposal linkage. Model follow-up receives a bounded success/error tool envelope, never a fabricated success string.

Target proposals additionally bind operation=`target_create` into the canonical digest, with before=null and an exact TargetInput after-value. A target_created result includes before_revision, after_revision, the full six-field Target and the exact target.created/local_operator audit; ID, timestamp, approved input and revision increment must agree. Duplicate names or addresses remain legal and never prove that a particular operation succeeded. Target list reads preserve order with offsets0..100 and limits1..10; detail reads require the actual stored ID.

SkillCreateArguments is the flat closed SkillInput (`name`, `description`, `instructions`, `category`) plus `expected_draft_revision`. Category is exactly planning, measurement or analysis. Existing nonblank text limits are120/1000/8000 Unicode codepoints, respectively; Cc/Cf/Cs controls are denied except LF/CR/TAB in description/instructions. Literal whitespace is preserved without trimming, case folding or normalization. Native argument admission applies independently; manual validity does not imply chat admissibility.

SkillCreateProposal contains operation=`skill_create`, digest, expected_draft_revision, before=null, after=SkillInput and expires_at. The digest binds the canonical `{call_id,grant_id,operation,expected_draft_revision,before,after,expires_at}` object without changing old Agent/Target digests. Null before means creation, not name uniqueness: equal-name Skills are legal distinct records.

SkillCreatedResult has exactly `{kind:"skill_created",before_revision,after_revision,skill,audit}`. Its complete Skill has all ten fields: `id`, `name`, `description`, `instructions`, `version`, `category`, `status`, `allowed_operations`, `required_capabilities`, `safety_rules`. The producer generates a fresh UUID4; the three text fields are closed `{en,ko}` copies of the exact approved literals, not translations. Version is1.0.0, status is draft, both operation/capability lists are empty, and safety_rules equals the existing catalog SAFETY_RULES. There is **no Skill created_at**. The audit has exactly `id`, `action`, `entity_id`, `created_at`, `origin`: a separately generated ID distinct from the Skill ID, action=skill.created, entity_id=skill.id, valid timestamp and origin=local_operator. No Skill/audit timestamp equality is invented. Arguments, proposal, both saved locales/category and the receipt must agree; before_revision equals the approved revision and after_revision is exactly one greater.

New failures use fixed nonreflecting CHAT_TOOL_* codes: GRANT_CONFLICT, GRANT_INVALID, APPROVAL_CONFLICT, CONFLICT, WRITE_FENCED, DENIED, LIMIT, PROTOCOL and UNCERTAIN. Existing chat input, busy, timeout, cancellation, storage and retention failures still apply. Invalid native syntax fails before dispatch; oversized valid Skill details produce a bounded failure rather than truncation.

## Read-only scenario-state inspection (B3 incremental slice)

GET `/api/v1/chat/tools/scenarios/state` connects the existing operator client to
the same runtime-owned domain worker and scenario store. Its closed response is
exactly `{schema_version:4,scenario_revision,registry_write_status}`: the revision
is an integer from0 through1000, and the status is `available` or `quarantined`.
Boolean/coerced revisions, unknown keys and malformed worker responses are not
successful observations. Unknown or duplicate query parameters are rejected
before worker admission. A JSON-framed POST is unsupported; the existing HTTP
boundary rejects an unframed mutation before routing.

Inspection does not save a scenario, change an audit, clear a fence, consume a
recovery ticket or repair retained files. A readable registry with a malformed
admission receipt remains observable as quarantined. An unreadable/corrupt
registry or receipt I/O failure remains `CHAT_STORAGE_ERROR`, not availability.
Each read observes current state through the shared no-queue lease, uses the
original deadline and rechecks it before returning the validated result.
Timeout/cancellation releases the preparing lease but does not declare a still
running native read retired: the worker stays busy until it actually completes.

The response's schema4 is only the existing inspection format. Native tool
metadata remains version3 with the same four tool names; public scenario grant/write
adapters remain unsupported. Normal UI scenario-write controls therefore remain
disabled. This endpoint is not acceptance of the complete B3 write workflow,
NORMAL execution, browser integration or actual DUT testing.

## Internal scenario grant lifecycle (stage 1, not public activation)

The internal runtime can resolve a validated `GrantInputV4` through its existing
domain worker and retain a closed `GrantV4` in the same chat ledger. The commitment
includes the complete intent, source/base references, revisions and operation,
alongside the existing session/sequence/text binding. Resolved protected inputs
come from the real domain resolver. A matching digest proves consistency, not
source authority; the ledger's resolved-input argument is a trusted internal
interface, not a model-facing authentication mechanism.

Exact replay returns the retained grant before fresh settings/source resolution,
without renewing its identity, expiry or resolved inputs. Lookup and revoke use
the existing ledger. Reopen validates the complete retained graph before recovery
and expires pending grants without dispatch. The existing 300-second lifetime,
8192-byte record limit, 2048-grant limit and shared retention budgets are unchanged.

New internal scenario grants retain the original preparation deadline and captured
Stop event through synchronous ledger work. A trusted, non-I/O publication guard
runs before insertion and after pool accounting, inside the existing transaction.
Denial rolls back the new grant and pending-expiry updates; failed rollback keeps
the storage fence and does not prove absence or transaction closure. Exact replay
does not invoke this guard. This cooperative precommit check cannot interrupt an
already-running SQLite COMMIT; no postcommit timeout is reported as if durable
authority had never been saved.

Public v4 grant POST remains rejected with `CHAT_INVALID_REQUEST`. A known staged
v4 grant cannot be sent publicly: public runtime and default direct-ledger admission return
`CHAT_TOOL_GRANT_INVALID` before turn/reservation/producer allocation or grant
consumption. Stage 1 rejected all consumed v4 grants and v4-bound turn graphs;
stage 2 admits only the fully linked internal graphs described below.
Native metadata remains version3; no new provider tool is advertised. The fixed
409 `CHAT_SCENARIO_WRITE_FENCED` error reports quarantine without clearing it.
Grant staging alone is not a scenario save or UI-writing feature.

## Internal native scenario proposals (stage 2, no save activation)

Independent review closed ambiguous old/new text-hash replay, the exchange-limit
read-publication bypass, and replaceable Stop/deadline references. The retained
regressions cover these repairs and the exact storage-observer adaptations.
This acceptance remains limited to the internal proposal path, not scenario saves
or public activation.

A private entry uses the same runtime owner, worker, turn and reservation to read
grant-scoped scenario context/details and prepare either `scenario_create` or
`scenario_append`. The selected native vocabulary is configuration_read plus the
grant's single operation. Legacy parser/transport defaults remain unchanged.
Real native arguments retain their original bytes; protected numeric inputs come
from the resolved grant, not model-supplied fields.

The complete proposal is retained in a version4 transcript at awaiting_approval.
Its call, arguments, operation, source/base versions, revisions, snapshots and
expiry bind to the retained grant. The scenario turn binding also commits the
immutable grant fields. Reopen validates that complete graph before recovery;
unlinked consumed grants and substitutions into legacy bindings remain invalid.
New v4 grants hash raw UTF-8 user text as required by the v4 bound-grant consumer.
Earlier stage-1 grants replay unchanged, without reissue, renewed expiry or silent
conversion into internally sendable authority; legacy v1–v3 hashes are unchanged.

Encoding provenance is private persisted metadata, not inferred from a hash match.
New v4 rows use a closed `{storage_version:1,text_encoding:"raw-utf8",grant,
authority_digest}` envelope in the existing grant table. The public grant shape
does not change. Validate the complete envelope before exposing its grant;
malformed-present metadata cannot fall back to a legacy record. Bare historical
records use only their original JSON-string commitment and cannot admit scenario
turns. Status updates preserve provenance. The whole stored envelope counts
against the unchanged record/pool limits. Its digest establishes consistency,
not authentication against a writer able to replace the entire database.

Complete prospective receipt/call/exchange/context sizing precedes approval wait.
Sizing witnesses are never saved or reported as actual results. Original deadline
and captured Stop checks extend through synchronous admission and publication.
In stage 2, scenario approval is rejected and no save adapter is dispatched.
Its denial, cancellation, expiry and restart paths do not change the scenario
registry. Public metadata remains version3; JavaScript byte
parity, actual provider integration and public activation are later gates.

Successful-read publication checks original authority on both retained-exchange
and exchange-overflow exits; on-time overflow can retain the read fact without a
provider continuation, but a late read is rolled back. This is not a rule to erase
an already durable write receipt. Decision publication checks the captured Stop
object and deadline, not a subsequently replaced runtime reference.

## Private scenario approval and saves (stage 3)

Private approval and reconciliation validate actual recursive model data before
serialization and retain detached checked values across awaits. Regression tests
preserve the copied-model unknown fields that originally bypassed validation.
Independent source/readback review supports the correction; fresh Codex-sandbox
tests timed out and are not counted as passes. The operator explicitly waived
that sandbox rerun for progression. Ordinary offline integration gates remain
required; browser/model/public activation are separate stage-4 obligations.

The private approval entry takes a separate exact operator decision for the
retained proposal. It uses
the same owner and ledger transaction to retain an executing intent before waking
the existing native scenario save worker. Public approval and default ledger
approval remain closed for v4; no model text or public feature flag grants consent.

Both create and append use the existing scenario store and immutable version
readback. Success binds the full saved definition, snapshots, proposal, grant and
decision, not merely a current latest-version ID. A later append does not erase
the earlier saved version. Original captured Stop/deadline and publication guards
still apply before mutation, without erasing a completed native acknowledgement.

Scenario outcome publication and provider-exchange delivery use separate SQLite
transactions. A failed delivery cannot roll back an already retained save receipt.
Registry JSON and chat SQLite are not atomic together: receipt-commit uncertainty
can leave durable executing intent for uncertain recovery. Restart does not repeat
the save or model request; executing writes become uncertain and fenced. Retained
terminal receipts may settle their missing exchange without domain execution.
This is not universal exchange repair: a retired call may retain a missing
exchange after logical refusal, and generalized near-cap recovery is not proven.

Private scenario reconciliation requires idle ownership, exact fence generation
and both draft/scenario revisions observed under the existing native lock bridge.
Its v4 receipt preserves `prior_outcomes:remain_uncertain` and
`scenario_recovery:not_performed`. Legacy reconciliation cannot clear a scenario
write fence. No scenario recovery ticket is consumed, registry quarantine is not
cleared, and old outcomes are not promoted to success. Exact reconciliation replay
returns historical facts without reacquiring mutable revisions.

Controlled model-final failure can still fail the conversation after a successful
save; the real receipt remains. This is not acceptance of the historical A-FINAL
issue, actual provider/browser integration, or public v4 activation.

## Public scenario workflow (stage 4 candidate)

The candidate advertises the closed schema-v4 runtime registry: the four legacy
tools plus `scenario_create` and `scenario_append`. Legacy grants keep their
existing scopes and handlers. Public scenario grants are parsed from the actual
raw request; turn and decision dispatch use the retained grant/call binding,
not a client-selected handler or a mutable feature flag. Generic/private legacy
entrypoints still reject scenario work unless the explicit scenario path owns it.

Variant discovery is not an admission or replay decision. A missing grant defers
to legacy turn admission, preserving session/replay precedence and
`CHAT_TOOL_GRANT_INVALID`. Decision bodies are validated before discovery;
missing calls defer to the original decision request-conflict/replay ordering.
The HTTP, runtime and ledger guards share missing-call classification, while
known v4 calls still reject new approval through default entrypoints. Storage
errors are not converted into a missing authority or a legacy fallback.

An operator first reads tool availability/fence and selects the scenario scope.
Only structured operator input or an exact immutable source-version reference
supplies protected inputs. Append can use a different immutable base. The model
proposes a complete definition; a separately submitted exact proposal approval
is required to save. Saved receipts, immutable history and fresh UI readback
retain the source/base distinction. No packet transmission or scenario execution
is enabled by creating or appending a definition.

Public v4 reconciliation retains exact fence-generation and draft/scenario
revision checks. It acknowledges uncertainty without recovering the scenario
registry, replaying a save or promoting an uncertain outcome to success.

Offline qualification uses real HTTP handlers and owned JSON/SQLite storage with
synthetic native-provider messages. The new `producer-compatibility.json` corpus is
generated by the actual Agent/Target/Skill capture path under public metadata v4;
the earlier `producer-current.json` and `producer.json` remain historical evidence.
Raw bodies, source pins,
approval, audit and restart assertions are retained rather than hash-only repinned.

For this closeout the operator explicitly deferred actual-model and PostgreSQL
execution. Consequently the normal-wire corpus, whose origin requires real
PostgreSQL and a separate worker, is unchanged and its current-source freshness
gate remains open. Neither SQLite nor mocked data substitutes for that evidence.
Unfiltered Web failure at that gate must remain visible; passing other checks
does not establish full-suite, model, PG or caller-deployment acceptance. No
historical model allowance is reset and no existing service is restarted.

## Actual publication, conflict and recovery

DraftState.audit_total is a conservative single-process CAS token. All existing manual draft writes advance it, including unrelated saves. A mismatch refuses the proposed operation; it does not silently rebase. The worker preserves MCP fields and validates references under the same draft lock used for publication and authoritative disk readback. The final stop/deadline guard runs after temporary serialization/file fsync and immediately before replacement, not merely when the request starts.

Target and Skill preparation are effect-free. Both preparation and execution use the session-bound settings revision: draft/settings CAS precedes typed input/quota validation, then audit headroom. The target quota is100; the custom Skill quota is100 excluding the three built-in templates. At SAFE_INT=9007199254740991, creation is refused before a proposal, decision or domain UUID/timestamp allocation; ceiling-minus-one can succeed. Stale draft/settings map to CHAT_TOOL_CONFLICT, full quota to CHAT_TOOL_LIMIT, and audit headroom refusal (AUDIT_LIMIT_REACHED) to CHAT_INVALID_REQUEST. The same checks run under the mutation lock. No wire counter range is reduced to conceal overflow. Skill publication writes one Skill, its audit and audit_total in one JSON image; full-state readback also checks untouched prior Skills, assignments and unrelated collections. Manual create_skill behavior remains unchanged.

Draft JSON and chat SQLite are separate commits. An intent must be durable before domain execution. Normal domain acknowledgement, exact lock-held disk readback/new audit, and a durable final tool receipt are all required to report success. A postpublication failure, failed readback or failed receipt commit can leave an uncertain write. Current value equality does not prove that this call owned the write or that earlier durability succeeded. There is no automatic retry or invented distributed transaction.

For Skill creation, proven prepublication storage refusal maps to CHAT_STORAGE_ERROR; post-replace directory-fsync/readback failure maps to CHAT_TOOL_UNCERTAIN and fences writes. An unexpected fault after mutation entry is uncertain without actual proof that publication did not occur. There is no rollback/delete/recreate or name-based recovery. A successful saved receipt survives a later failed exchange or final model narrative. A denied/failed write still consumes the one attempted-write slot across all three write kinds.

The chat database migrates validated v1 storage transactionally to v2, beginning the transaction before DDL. Additive Skill JSON variants introduce no new table/user_version migration. Existing messages and idempotency commitments remain intact. Unsupported/corrupt databases and caller sidecars are not replaced. On restart, outstanding write intents, including executing Skill creation, become uncertain, unfinished unadmitted work is cancelled, completed results remain, and no model/domain operation is replayed.

An uncertain write fences new tool writes across restart. Inspection does not clear it. Reconciliation requires no active turn/worker, an exact current fence generation and draft revision, and an explicit acknowledgement that prior outcomes remain uncertain. It neither changes domain state nor promotes the old result to success. Fence generation increases on installation and clear and never resets. An old reconciliation receipt's write_fenced=false is historical: UI must obtain a fresh generation-monotone fence GET before enabling writes. An old acknowledgement cannot hide a newer fence.

## Bounds and ownership

- One active ordinary/tool turn, one owned domain worker, no replacement queue.
- At most three tool calls, one proposed/attempted write and four provider requests per turn; no automatic retries.
- One original120-second turn clock covers provider rounds, reads and approval wait. Grants/proposals/reconnect never renew it.
- Existing8KiB input,64KiB assistant text,128KiB encoded request context,64KiB raw upstream frame and32KiB per-response headers; aggregate upstream body2MiB across all rounds.
- Native argument JSON at most16KiB, serialized result32KiB, Call/StoredCall256KiB, retained ordered provider exchanges96KiB, companion response/transcript1MiB. Count UTF-8 and nested JSON escaping, not characters. Full history is not silently trimmed.
- The operator target inventory is a closed version1 `{schema_version,draft_revision,targets}` response with at most100 unique IDs and a hard128KiB encoded cap. This is not a model read: native reads remain bounded pages/details. The full future provider payload and retained receipt reservations are checked before proposal and again before new approval, including nested escaping and generated-field bounds.
- Operator Skill inventory is closed version1 `{schema_version,draft_revision,skills}` with at most103 unique-ID summaries, each exactly `{id,name:{en,ko},category,status,version}`: three catalog templates first, then custom stored order. The separate selected-detail response is `{schema_version,draft_revision,skill}` with the complete actual record. Each raw/canonical response is capped at128KiB; there is no pagination or eager full-library detail fan-out. Full drafts obey the closed ten-field policy above; templates must equal one of the exact finite catalog records, not merely a template-shaped object. Model Skill pages remain at most ten and details retain the old localized projection and CHAT_TOOL_LIMIT on oversized results.
- Skill inspection paths accept the literal domain Identifier (`[a-z0-9-]+`, length1..64), not only UUIDs; no normalization or query parameters are allowed. Malformed selectors/queries return CHAT_INVALID_REQUEST; a missing valid ID returns CHAT_NOT_FOUND. Reads retain worker ownership, no-queue CHAT_BUSY, bounded deadlines and no automatic retry.
- Tool records share a2MiB logical retention pool, separate from existing8MiB text and16MiB physical database caps. Admission reserves1MiB conservatively for the bounded future record envelope; this can refuse new tool work before actual retained bytes fill the pool. All persisted copies are charged. An uncertain write retains8KiB for later reconciliation. Logical reservation cannot guarantee disk commit success.

All pre-existing caps remain unchanged, including the16MiB draft read. Before awaiting_approval and again before a new decision/intent, prospective admission accounts for the complete Skill receipt/Call, decision/link/fence and reservation copies, retained raw argument string, escaped provider IDs, narrative/history, nested JSON tool-message string and the entire128KiB next provider request. Conservative generated-ID/time/counter bounds do not allocate real domain identities or timestamps. Runtime also checks actual assembled exchanges/provider payloads and final serialization. A32KiB result alone is not sufficient. Overflow fails CHAT_TOOL_LIMIT before proposal/decision/domain publication: no truncation, dropped policy fields, partial proposed/saved record, cap increase or provider continuation after denial. Already saved facts remain saved if later settlement fails.

Provider client ownership spans all rounds; each response closes before tool execution/approval wait. For a tool turn, transport=open describes that owned local client, not an actively connected socket. Tool-only updates have their own revisions; text events remain contiguous. After observing a terminal Turn, the UI performs a fresh companion read before ending live observation; an earlier in-flight response is not sufficient.

Blocking filesystem work cannot be forcibly interrupted safely. Stop sets a thread-safe signal immediately; after the publication gate it cannot undo the operation. Ownership remains until native work, readback and receipt settlement complete, so the UI may show cancellation pending. Chat metadata requiring the busy worker refuses CHAT_BUSY rather than blocking the event loop; transcript inspection and Stop remain available. Remote provider generation termination remains unconfirmed after local closure.

## Evidence boundaries

Saved-target navigation retains an Application-owned, cloned and validated expectation `{target,after_revision}` of at most4096 UTF-8 bytes, bound to the selected ID. URL/history carry only the ID. The Targets page performs a fresh inventory GET and confirms a receipt only when every returned target field matches and the observed revision meets its floor. It never injects expected bytes into the inventory. Reload/history or other ID-only entry reports current-record-only observation, not historical receipt confirmation. A stale workspace or superseded selection invalidates confirmation and cannot replace independently inspected selected bytes. Target uncertainty inspection uses fence → inventory → fence; current equality never resolves ownership uncertainty.

Saved-Skill navigation separately retains an App-owned, validated, deeply cloned/frozen `{skill,after_revision}` expectation of at most32768 UTF-8 bytes, with every nested locale/policy list isolated from aliases and skill.id equal to the selection ID. Only `/skills?skill=<encoded Identifier>` selects a record; malformed, duplicate or extra parameters give no selection or authority. URL, history.state and localStorage cannot carry receipt authority. Ordinary navigation, popstate and reload clear the expectation; an ID-only entry can show current-only. A fresh retained tool-history read followed by its actual saved link can reacquire a receipt expectation.

A fresh selected-record GET confirms only when every full Skill field matches and draft_revision meets the receipt's after_revision floor. Missing/changed/below-floor records are discrepancy, failed reads are unavailable, and cancelled/superseded responses cannot confirm. This is full-record receipt confirmation, **not independent saved-audit confirmation**: the detail route has no audit. Integration acceptance must separately verify the actual saved audit in owned persistence. Later audit retention or inspection failure does not erase an immutable Saved receipt. Workspace/selection/expectation changes invalidate confirmation, and later workspace data never replaces inspected selected bytes.

Only one selected-record GET belongs to a live owner; retirement is checked before dispatch. No selected ID means no extra inspection, and locale changes rerender without another GET. The existing SkillDetails shows fresh inspected bytes, not a receipt injected into the workspace or locally created list. Selected details stay reachable outside list filters; same-page unsaved SkillDraftForm inputs and existing Agent/Target dirty forms are preserved. Close/Escape cancels presentation ownership so late responses cannot reopen or steal focus; focus returns to a connected trigger or stable selected-record control. Cancel inspection and explicit GET-only retry remain available with no automatic CHAT_BUSY retry. Outage recovery is read-only and does not enable create/assignment by relaxing disabled forms.

Uncertain Skill creation with an unknown ID uses fence → summary inventory → fence with identical generation, fenced-call IDs and draft revisions. All summaries remain reachable without eager detail fetches. Explicit candidate detail inspection must match that revision and a closing fence with the same revision/generation/IDs or the review is invalidated. This cannot infer ownership or change an uncertain call to success; explicit reconciliation acknowledges uncertainty and never assigns, executes or recreates a Skill. Scenario storage/recovery is unchanged.

Startup metadata GETs alone may recover a definite CHAT_BUSY response with at most three attempts, spaced at least 500ms after response completion. Tool runtime and fence reads are serialized. Cancellation, unmount or a newer read cancels this recovery; other failures remain explicit. This does not retry grants, decisions, turns, reconciliation writes or model requests, and never provisionally enables authority.

New decision admission rechecks live owner/Stop and the original monotonic deadlines after preparation, then samples UTC again before recording the decision and write intent. Expired new approval is refused without consuming the write slot; exact historical replay remains first. The browser acceptance harness owns port5175 to match the existing Origin allowlist, refuses collisions, and never expands the backend's Origin policy.

Controlled protocol/fault/approval tests, a genuine selected-model mutation, independent storage/UI readback, and caller deployment are distinct gates. A native-tool capability probe is not evidence of a configuration write. A simulated provider is not real-model acceptance. Source-UI tests do not imply that a caller's stopped service was restarted or its model configuration rewritten.

The CHAT-02A core checkpoint has a separate open final-model-explanation acceptance item (A-FINAL): successful storage does not imply a successful final model reply. B1/B2 preserve those saved facts and do not claim selected-model Target/Skill creation acceptance. The real-model ledger remains consumed5/admitted5/hard6, with no reserve use, reset or token/deadline expansion. The acceptance harness's closed `--fixture-case agent|target|skill` selector is fixture-only and rejected outside fixture mode before side effects; its default remains Agent. Skill fixture selection cannot enter real mode. Fixture responses are synthetic even when the API, JSON/SQLite persistence, browser and raw producer captures are real executions.

### B2 checkpoint and remaining gates

Checkpoint `4412cc985dfa36c0419dbcdf008820753bdd1f97` contains implemented B2 code, not accepted full-feature delivery. Named component reviews are closed. Current all-variant producer freshness, fresh normal PostgreSQL/separate-worker Node/Chromium parity, Agent/Target/Skill fixture browsers, the existing nine-spec browser suite, final canonical gates and owned-resource cleanup/acceptance remain open. Resource permission is not evidence of successful execution; this contract does not claim the in-progress capture, PostgreSQL or browser work has passed. Implementation/fixture acceptance, selected-model acceptance and deployment remain separate. Device/transmission acceptance is deferred, not implied by DOM/geometry checks or fixture success.

Old Agent/B1 raw bodies, digests and original producer-pin metadata remain byte-for-byte historical evidence. B1's original92 producer-input path/hash pairs are bound to actual base blobs at `5d41294644f1138f6638e69451e1e565a42c3b54` in `web/src/pages/ai/chat-target-producer-data/producer-baseline.json`, alongside the immutable corpus hash. Historical replay proves archival identity and strict consumer compatibility, not current production. At the WIP checkpoint the old live-file freshness comparison still requires the coordinated transition; a historical sidecar alone does not close it.

Replacing that historical live-file comparison is permitted **only together with** a genuine new current-source Agent v1/Target v2/Skill v3 capture/replay and mandatory current freshness checks, promoted atomically. `tests/chat/chat_skill_capture.py` supplies the separately admitted controlled-provider/native-handler/owned-store capture path; the existence of a helper is not a capture PASS. New raw responses must retain exact bytes and current source pins; negatives are explicitly derivatives. No hash-only refresh, stale-pin fallback or temporary skipped freshness gate is acceptable. Fresh normal-PG evidence must preserve12 positive rows and39 existing negative bytes with current pins and Node/Chromium parity; SQLite cannot substitute for that gate.

Final frozen-source verification requires separately admitted finite resources, exact source/command/exit/collection/cleanup receipts and independent closure. The scoped canonical targets are `make test-api`, `make test-chat`, `make test-tooling`, `make test-evidence`, `make test-phase3-config`, `make test-web`, `make lint` and `make build`, not broad `make test`, `test-runs` or historical full S02/W2 replay. B1 browser/PG allowances stay closed and are not reused; fresh B2 permission does not reopen model or device traffic budgets. Required Skill fixture proof includes zero preapproval mutation, separate exact approval, a single full saved Skill/audit/revision, independent storage/HTTP readback, and Skills details in EN/KO at900/390 widths, with reload/back/restart current-only and history-link receipt reacquisition. These are acceptance requirements, not claims that the checkpoint already passed them.
