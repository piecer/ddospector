# S02 I0 — Exact native-warning stderr amendment

Status: AUTHORIZED_NARROW_AMENDMENT_PENDING_INDEPENDENT_REVIEW. This document changes one diagnostic framing rule; it does not establish product GREEN or I0/S02 acceptance.

## 1. Authorization, precedence and preserved history

User: “승인할테니 진행해.” This accepts the immediately preceding proposal: one contract correction allowing the exact `/dev/null` password-file warning to be preserved and separated within the existing 4096-byte stderr total, with every other malformed, partial or oversized output refused. Credentials and success conditions remain unchanged, and the incomplete current product cycle continues rather than opening another product repair cycle.

The authority receipt is `inputs/amendment-parent/supervised-stderr-amendment-authorization.json`, SHA256 `03ab0f46fe3342c032d9fdc798922c4eddb91d80d212c573f905a768fa89a96e`. Contract corrections are cumulative 4/4; product remains the incomplete 3/3; S01 remains 3/3; reset=false. The completed primitive study remains sealed at 3/3 experiments and 23/24 test processes, with its reserve unused. These research ceilings do not replace the separately required actual product tests.

Keep `S02_RUNS.md` SHA256 `9de2bdd662227fef9d8a6538bb7e366f19b381db21e3c81ae4225844b4fe08c2` and `S02_I0_SUPERVISED_HANDOFF.md` SHA256 `c63a37804dad67ac216b933cfc8f0066d987b4b483a2c15225c31b0142c198ac` byte-identical. The original addendum's historical DRAFT heading is already superseded by parent adoption `265d051223c0725f143d60fb0b97d73b621d6c1126d6cde1a70411e06bda0762`. This amendment supersedes only its section 5 JSON-only stderr framing sentence and the directly corresponding output oracles. All admission, proof, error classification, publication, deadline, privacy, retirement, custody and test-migration rules continue to apply.

The stopped author changed no existing product source. Its one real-PG RED and the previous JSON-only replay RED remain immutable. Healthy old setup/write and legacy unadmitted raw-read outputs contain respectively 4/11/2 copies of the warning below; those are observed witnesses, not fixed future warning-count expectations. The raw-read exit0 is still the authority defect, not a newly accepted supervised success. See `inputs/stopped-author/implementation-evidence/diagnostic-boundary.json` and the provenance-corrected parent checkpoint in `inputs/amendment-parent/`.

## 2. Exact wire grammar

Let W be exactly these 55 ASCII bytes, including the final LF (the backslash-n below denotes byte 0x0a, not two literal characters):

    WARNING: password file "/dev/null" is not a plain file\n

Let J be one complete UTF-8 JSON object with the inherited closed `{blocked,site}` schema and one final LF. The existing diagnostic identifier, site count, function-name and uint32-line restrictions are unchanged. Preserve the producer's legal JSON spelling, including its existing spaces; compact encoding is not newly required. No extra keys, second object or trailing record is allowed. JSON string contents are data, never another framing channel.

The only admitted stderr framing is W repeated zero or more times, followed by either no bytes or one J. Thus empty stderr, W-only, J-only and W-prefix-plus-J are syntactically representable. The ENTIRE original stream, including every W and J byte and LF, must be at most 4096 bytes. This is one shared bound, not 4096 for each component. There is no separate warning-count or business-operation quota.

Match W as exact complete bytes at the current beginning offset only. Do not use substring removal, regex/substring warning suppression, case folding, `.strip()`, newline normalization, locale translation, JSON reserialization or a general warning allowlist. A changed path, spelling, capitalization, CRLF, missing LF, truncated W, arbitrary line or warning after J is invalid. A JSON field containing an escaped warning cannot be removed or treated as W. Decode/validate the remaining J as one complete inherited closed object, without accepting duplicate-key or trailing-value ambiguity. The old permitted JSON spaces and existing diagnostic assertions must remain reachable.

This rule covers the granted PG child's stderr. The generic `run_child` DEVNULL/text/communicate route and its original retirement tests are unchanged. Unadmitted raw requests still refuse78 before PG and cannot revoke an unrelated healthy owner. Recognizing W supplies no admission authority and cannot convert a raw refusal or unverified output into a valid attempt.

## 3. Success and failure remain distinct from framing

For a granted child, exit0 with empty or W-only stderr is merely diagnostic-compatible. Success additionally requires every original requirement: exact bound stdout proof and grant binding, original owner/source/custody/deadline, no latched failure, actual reap, all three pipes' proved single-close disposition, required publications, context restoration and the final fallible tail before ELIGIBLE.

A J is an error diagnostic: even with exit0 and a valid-looking stdout proof it cannot succeed. Nonzero, timeout, interrupted/unknown outcome, unrepresentable diagnostic, malformed framing or excess bytes all remain failure and revoke an enrolled owner before fallible logging. Missing/empty stderr on a failed child does not remove failure. W followed by a genuine SQL/body error J remains failure; neither W nor its count may override exit, deadline or error precedence. Required warning-evidence publication failure remains failure, including after child exit0.

Preserve the complete VALIDATED stderr bytes in the existing `pg_child_exit.diagnostic` evidence and the real `run_child` Result; do not replace them with a warning count, rewritten JSON or a synthesized Result. Native warning prefixes and valid child error JSON retain their original order and spelling. Since valid bytes are ASCII/UTF-8, their stored string must round-trip to the same bytes. Do not drop warnings before journaling. Existing append-only history remains unchanged, with no new lifecycle retention or deletion policy.

On invalid stderr, do not persist or print untrusted rejected suffixes, driver exception strings, SQL, credentials, nonce or raw grant. An already recognized exact W prefix may be retained, and the inherited sanitized parent failure classification must describe the failure without masquerading as child-generated J. If diagnostic retention itself fails, preserve the original primary object/type/message and terminal work denial; successful publication is not a prerequisite for revocation. Retain the original test/warning/failure artifacts unchanged.

## 4. Unchanged resource and implementation boundaries

The parent still bounds stdout to81920 and stderr to4096 bytes, with86016 aggregate transport bytes. The granted reader still requests at most `min(4096, remaining+1)` and refuses the one-byte overflow before append. A large valid prefix does not create room for J; no truncation, spill file or uncapped intermediate line/record history is permitted. Parse by bounded offsets/views rather than retaining a warning list. Release transport data at the same settlement boundary. The existing return/evidence ownership distinction remains; this amendment does not add retained owner histories or enlarge the87-byte logical control record.

Grant161/input162, three original pipes, observed finite kernel capacities without resizing, one current attempt, original D and cleanup bounds all remain unchanged. Keep `passfile=/dev/null` and every existing connection/environment restriction. Do not add native-FD redirection, an extra pipe/thread/capture file, alternate passfile, environment fallback, new daemon/RPC or broad native-output suppression. No source/dependency/Makefile/API/UI/worker/application-schema ownership expands except adding this normative amendment document to the future candidate.

## 5. Required evidence and continuation gate

Narrow independent review assesses authorization/scope, exact framing, preservation/privacy, unchanged bounds/failure precedence and executable producer-to-parser obligations. It may replay the saved real stderr bytes and generate bounded static grammar cases. Such replay is NOT a fresh PG execution, product parser GREEN, the sealed native primitive study, or independent R03 acceptance. Parent exact-byte adoption of the reviewed amendment precedes resumed mechanism implementation. A blocking new contract finding does not authorize another correction automatically.

The continuing author must add permanent tests and close these rows on the actual final product, in addition to all existing G01–G10/H01–H08 and original/migrated/external cases:

| Row | Required witness |
|---|---|
| W01 | Retain the saved actual setup/write/raw-read warning bytes and prior JSON-only RED. Replay accepts their diagnostic framing without relabeling the raw-read authority defect as success. |
| W02 | Fresh supervised setup→write→restart→read succeeds with real native warning bytes preserved exactly in Result and journal, alongside all original proof/ownership/final-tail requirements. Do not hardcode observed 4/11/2 counts as required behavior. |
| W03 | Actual admitted PG UndefinedTable after a native warning reaches the SQL error, retains the real J/Result and blocks the next writer. Publication failure and warning-only nonzero outcomes remain failure. |
| W04 | Exact W plus single-byte mutations, wrong path/case/newline, partial records, unknown lines, invalid UTF-8 and arbitrary text all receive their correct positive or refusal outcome. No normalization/suppression fallback. |
| W05 | W+J, J-only, duplicate/extra keys, malformed J, second JSON value, warning-after-J and escaped warning inside JSON are tested without weakening inherited schema or privacy. Exit0+J still fails. |
| W06 | Complete valid exact4096 and invalid4097 streams, combined W+J budget, overflow-before-append and all relevant fragmented-read boundaries are exercised through the real bounded transport/parser. The boundary corpus must contain structurally valid exact-limit cases, not only padding that would be invalid anyway. |
| W07 | Warning-free healthy control, warning-only healthy control and fail-closed unknown-output control are separate; no deny-everything or accept-warning-only success oracle. Grant/proof/exit/deadline/finalizer failure always wins. |
| W08 | Actual required evidence/publication failure after otherwise valid warning output revokes; local primary identity and cleanup-only authority remain independently checked. No invented child Result or error output is substituted. |
| W09 | Parent retains no growing warnings/process/grant history; logs preserve known bytes but not rejected secret-bearing suffixes. Generic R03/original spaced-diagnostic assertions and all original file/body preservation requirements remain accounted for. |

Resume the preserved product RED in a fresh isolated candidate, carrying the stopped source, test, reports and warnings as immutable inputs. Continue the SAME incomplete product3 cycle with strict vertical RED→GREEN. Ordinary in-scope TDD corrections before author completion are allowed; this amendment is not product4 or permission to reopen sealed experiments. After the final edit, run the authorized actual-PG/fixture/retirement/wire cases and fresh canonical setup/test/lint/build, then parent reconciliation and a distinct fresh independent product/R03 review. Active integration, browser/full S02 acceptance and per-stage commit/exact verification remain later gates.
