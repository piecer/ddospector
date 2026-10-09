# AI-02 verification scope

AI-02 adds model configuration drafts, not model execution. The original `PLAN.md`, historical plans and UI-01 verification record remain unchanged.

## Reproduce

From the project root after `make setup` and installation of the locked Playwright Chromium:

```sh
make test
make lint
make build
make test-e2e
```

Both Python and Node dependencies are needed for frontend tests: the Unicode/URL differential tests invoke the actual project Python 3.12 producer, not system Python. Generated-data freshness is included in canonical UI tests and can also be checked with:

```sh
.venv/bin/python web/src/pages/ai-settings/tools/generate_unicode.py --check
```

## Independent acceptance

- Backend: 642 canonical API cases plus 210 separate independent storage, validation, migration, concurrency, uncertain-outcome and execution-denial probes. All passed.
- Final frontend corrective review: 642 API cases, 256 UI cases and 73 Chromium cases, plus lint/typecheck/build. No failed, skipped or flaky browser cases.
- Separate independent producer-to-Chromium checks covered all 1,114,112 code points for fold/text parity, 23,722 IDNA hosts, 26,228 URLs, 362 producer-response cases, 30 response mutations, four historical responses and seven fresh real API/browser scenarios. No mismatches were observed. Finite multi-character corpora are not an exhaustive proof for every possible string.
- The independent frontend review preserved all 144 frozen source files. Its separate Python imports and browser requests were bound to that candidate, without Origin rewriting or product/test/config edits.

Reports and original RED evidence are retained under `.hermes/artifacts/ai-02/reviews/`. Final frontend acceptance is `frontend-cycle1-deleg_ad19cfd2/evidence/frontend-cycle1-acceptance.json`. Source-bound logs and subsequent active-tree verification are separate from inherited candidate evidence.

## Repaired blockers

- AI02-FE-01: native browser URL parsing rejected valid stored numeric/hex-looking DNS labels and some IDNA metadata. The UI now uses the supported producer's deterministic metadata grammar and retains original values.
- AI02-FE-02: a casefold exception table with browser-native lowercase fallback collapsed names the producer considered distinct. Complete pinned fold data with identity fallback fixes this; control/whitespace and IDNA tables are generated and freshness-checked too.
- AI action denial is classified before semantic JSON parsing, so bounded malformed bodies cannot bypass the fixed no-execution response. Storage, credential-value lookup, DNS and outbound operations remain absent from these denial paths.

## Browser and integration coverage

The real API-backed browser suite covers 15 routes, English/Korean, profile create/edit/default/agent binding/reload/delete, all three protocols, advanced and retry fields, closed validation, revision conflicts, unknown save outcomes, explicit recovery, stale/loading mutation locks, late settlements, keyboard focus, responsive layouts and automated accessibility. It retains the UI-01 workflows and modal-lifecycle regressions.

Browser tests use their own API/UI on 5182/5175 and fresh scratch state. They must not seed the development API on 5180. The final development-page check is read-only, with mutations/external requests blocked, and compares workspace/settings before and after.

The authoritative active-tree verdict, final source manifest, per-command exits, browser collection and screenshots are in `.hermes/artifacts/ai-02/final/verification.json` and adjacent evidence. Do not infer active integration or deployment success solely from an independent candidate PASS. The final manifest records the documentation-only closeout delta separately from reviewed runtime/test bytes.

## Limits

Profiles remain untested local drafts. API-key values, connection/completion tests, model discovery, provider activation, failover execution, MCP connection, equipment control and LIVE traffic are unavailable. Retry settings are stored policy, not an implemented retry engine. No production authentication, encryption, multiprocess-store, physical-device or human screen-reader acceptance is claimed. Existing draft data is not test data and must be preserved.

No commit or push is part of AI-02 implementation acceptance.
