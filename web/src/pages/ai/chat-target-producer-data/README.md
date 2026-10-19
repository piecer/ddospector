# Actual target producer bytes — inherited capture replay

`producer.json` embeds the **unmodified UTF-8 strings** of all 23 HTTP bodies
(50,466 bytes) from the successful author capture in
`.hermes/chat02b1-harness-repair/actual-capture/` of the frozen
`chat02b1-acceptance-dqibboxc` workspace. Each entry retains the recorded filename,
method, path, status, Content-Type, byte length and SHA256. The ordered raw-body
SHA256 is `4d596d3e64473d86c1bb4592d923d3dad1e6c852f69659041129f62bc8c9ce94`.
The enclosing JSON escapes strings for storage; decoding `raw_utf8` recovers the
original bytes, including insertion order, number lexemes and Unicode. No
positive response is parsed and re-encoded to construct a test response.

This is **inherited actual HTTP producer evidence**, not a fresh runtime capture,
not actual-model evidence and not synthetic success data. The author's native
provider content was synthetic (three requests, zero real-model requests); the
HTTP handlers, IDs, timestamps, JSON/SQLite storage, approval, saved receipt and
restart readback were actual product behavior. Original capture-result and
source-pre/source-post files are embedded verbatim with their own byte/hash
guards. Their original provenance is not rewritten. Historical HOLD captures
are not included as successful inputs.

The original capture recorded request method/path, not raw request bodies.
Tests reconstruct request bindings from the actual session/grant/turn/decision
responses and the unchanged capture helpers. Those bindings are **not claimed
to be captured request bytes**. In particular, the legacy-worded user text is
retained exactly from the actual admitted turn, not rewritten to say Target.

## Current-source binding

The test pins this entire bundle, all response lengths/hashes, the source
manifest's canonical hash, and 92 producer/dependency/harness files selected
from the original capture manifest. It compares their current SHA256 and modes
to the original entries. The complete original 336-entry source manifest remains
embedded as historical evidence; unrelated frontend files are not live producer
pins. Consequently a separately reviewed frontend readback repair need not
pretend these are newly generated Python responses. A changed producer requires
an explicit provenance decision/new actual capture, never a blind hash refresh.

## Persistent coverage

From `web/`, with existing dependencies and offline environment:

```sh
npm_config_offline=true npm_config_update_notifier=false \
  npm_config_audit=false npm_config_fund=false \
  node node_modules/vitest/vitest.mjs run \
  src/pages/ai/chat-target-producer-wire.test.ts
```

`chat-target-producer-wire.test.ts` replaces only fetch transport, constructing
real `Response` objects from guarded raw strings at recorded paths/statuses.
The shipped `chatClient`/`toolClient` perform bounded streaming JSON decoding,
lexical admission, closed schema validation and authority/receipt binding.
Coverage includes:

- Actual runtime v2 and chat bootstrap; target grant POST, idempotent POST and
  GET-by-request recovery with exact requested authority; pre-submit rebinding.
- Actual requested/pending/saved transcripts, target read, canonical proposal
  and argument digests, and explicit decision receipt.
- Complete saved Target/audit, expected before/after revisions, unchanged
  preapproval workspace, actual post-save workspace, identical restart receipt,
  fresh inventory and validated selected-ID/receipt handoff. ID-only navigation
  intentionally carries no historical receipt expectation.
- Explicitly **synthetic malformed derivatives** for operation, audit action,
  origin/time/ID, target ID, revisions, float/exponent integer tokens, duplicate
  and escaped duplicate keys, extra authority and proposal digest.
- Genuine v2-as-Agent rejection and explicitly synthetic valid legacy-as-Target
  substitution rejection on POST, GET and pre-submit, plus duplicate inventory
  ID rejection. Synthetic controls are never described as producer captures.

Replay performs no network requests, inference, service startup or fresh store
mutation. It proves captured producer-to-shipped-client parity, **not browser
acceptance**. The separate target-browser `429 CHAT_BUSY` readback blocker and
full B1 acceptance remain open; offline replay does not repair or close them.
Existing A corpora and all prior evidence are untouched.
