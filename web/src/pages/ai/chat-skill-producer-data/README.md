# Native Agent / Target / Skill producer corpora

## Current P0-B1 source refresh

The current strict replay uses `producer-p0b1.json`, emitted unchanged by a
separately user-approved invocation of `tests/chat/chat_skill_capture.py` on the
P0-B1 candidate. The prior `producer-dev-lan.json` remains unchanged and pinned
as historical evidence. All other preceding bundles below are also preserved.

- Bundle SHA-256: `17eec715a415f100c58f77ac53603809fcf66bcb778a546ced6df55f27acce33`.
- Capture source digest: `af3a8d8b6bee978be059df0c76b36e230f149973b38c5f714cda28cde435c232`.
- Equal before/after source snapshots: 399 entries; 104 exact live producer
  hash/mode pins, including the new local authority module.
- Actual HTTP responses: Agent 20, Target 22, Skill 23, total 65. Every captured
  row remains intact; counts reflect this execution rather than copied historical
  polling counts. Client request/approval/persistence/restart and negative
  assertions are retained.
- One all-variant batch, three synthetic provider requests per variant, nine
  total; no real model, DUT, PG, browser or dependency download. Each variant uses
  its own store and an API restart. This is not real-model or device acceptance.
- Capture and supervisor exit 0, completion within the original 900-second
  bound, provider handlers closed, all seven observed process identities absent
  (capture child plus six API instances). The existing outbound fixture guard
  permits only the invocation's loopback provider.
- Raw responses, saved stores, admission, source snapshots, supervisor and
  readback: `.hermes/artifacts/progress2-p0b1/attempt-5a1b1221c80b/chat-refresh/`.
  This refresh closes source evidence debt exposed by the changed `session.py`;
  it does not change chat runtime behavior. The original failed full Web run is
  retained at the task's `final-gates/web.log`.

Publication of this bundle, README and replay pins follows capture. Their
consumer-side snapshot entries are not rewritten; live producer pins stay
mandatory. No recapture or stale-source fallback happens during ordinary tests.

## Historical first native Skill closure

`producer.json` is the byte-identical package emitted by the admitted
`tests/chat/chat_skill_capture.py` renewal on the final candidate based on
`4412cc985dfa36c0419dbcdf008820753bdd1f97`, after correcting the tooling
PYTHONPATH test oracle. It is **actual loopback product API
output with a synthetic native provider**, not a real-model run, hand-authored
positive fixture, reconstructed response, browser proof or PostgreSQL proof.

- Bundle SHA-256: `cb3b7e080c6f59a5669429f9722a1ceddd057b949030971f0a8f2b933dda8732`.
- Capture source-manifest digest: `b7da80d6fd376bf7dc583a10ec7f18452cdc69e478dae6a67a5bb8c51d0ea3fb`.
- Positive HTTP rows: Agent 20, Target 22, Skill 23 (65 total). Every captured
  response and polling observation is retained; no row identity is duplicated.
  Compared with the preserved earlier 67-row bundle, Target completed with one
  fewer companion poll and one fewer turn poll; no response was discarded.
- Admission: one attempt for each variant; three synthetic provider requests
  each, nine total; real-model requests zero; automatic retries zero.
- Actual HTTP → native read/proposal → separate approval → persisted JSON and
  chat SQLite → API restart. The helper independently asserts the saved domain
  record, audit and revision, no preapproval mutation and no repeated provider
  dispatch after restart.
- The supervisor observed six owned API process identities (initial and restart
  for each variant) and verified their retirement. The three retained final API
  receipts record deliberate SIGTERM shutdown, actual exit `-15`. All provider
  handlers closed (3/3 each). Capture child and supervisor returned zero within
  the unchanged 900-second external supervision bound. Earlier capture receipts
  remain separate historical evidence, not rewritten results of this renewal.

### Gates at that historical checkpoint

`../chat-skill-producer-wire.test.ts` binds the entire bundle hash, equal original
source pre/post manifests, all 100 current backend/dependency/helper pins and
modes, all raw response hashes/lengths and all three authority variants. Exact
positive strings enter real `Response` objects and the shipped clients. All
captured runtime, session, grant/recovery, tool-turn, companion, decision and
turn-read rows are consumed. Target inventories, Skill summaries and both full
selected Skill reads are parsed through their shipped methods. In particular,
`toolClient.skill(requestedID)` validates the complete record and requested ID;
full record equality and revision floor are compared to the saved receipt.
Negative mutations are explicitly named **SYNTHETIC derivatives**, not captures.

The 366-entry source pre/post snapshots retain the exact producer-time bytes.
Subsequent bundle publication, replay-digest bindings and this README are
consumer-side packaging changes; their earlier entries in those snapshots are
not rewritten. The 100 current producer pins still include the corrected tooling
test. This bundle came from a new actual capture, not a hash-only refresh.

`../chat-target-producer-wire.test.ts` now checks the unchanged B1 corpus and
frozen `../chat-target-producer-data/producer-baseline.json` against all 92 actual
Git blobs/modes at base `5d41294644f1138f6638e69451e1e565a42c3b54`, tree
`ed72b8827aa7136c043cc8f12de417df6162bef8`. This establishes historical identity,
not current production. The old raw corpus, producer metadata and sidecar remain
byte-for-byte unchanged. That transition requires this exact new bundle and is
shipped atomically with the current strict replay test. There is no stale-pin
fallback, skip or automatic recapture.

### Replay command and historical retained evidence

Offline replay from `web/` (no server/browser/provider started):

```sh
node node_modules/vitest/vitest.mjs run \
  src/pages/ai/chat-skill-producer-wire.test.ts \
  src/pages/ai/chat-target-producer-wire.test.ts \
  src/pages/ai/chat-tool-producer-wire.test.ts \
  src/pages/ai/chat-tool-producer-client.test.ts \
  src/pages/ai/chat-tool-producer-hook.test.tsx \
  src/test/chat-grant-observer.test.ts
```

Use the campaign's sanitized, offline environment. Run the parent-owned canonical
gates separately. Raw HTTP files, persisted stores, synthetic requests,
source manifests, import origins, exclusive admission ledger, PID/start/boot and
provider/thread/socket cleanup observations, original freshness RED, command
receipts and JUnits are retained under the renewal evidence directory recorded
in `.hermes/artifacts/chat-agent/chat02b2-test-oracle-renewal-authorization.json`;
the actual capture is its `actual-capture/` subdirectory. The earlier
`.hermes/current-capture-delivery/` remains intact in the predecessor workspace.
Those retained local artifacts are not required to replay this committed bundle.
Creating a new capture requires a new explicit admission; running replay never
spends or renews that allowance.
