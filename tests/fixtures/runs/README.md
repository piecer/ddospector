# Frozen Runs consumer fixtures

These are exact copies of the existing reviewed candidate's input bytes, not freshly generated backend results.

- `h1/selected-index.json`: 1,096 earlier H1 response entries, including repeated/legacy/seeded cases. Each referenced body retains its original SHA256 and relative name. Entries are not a count of independent worker acceptance tests.
- `parity/manifest.json`: 5,259 entries: 938 earlier H1 HTTP samples, 2 earlier I3 HTTP samples, and 4,319 labeled synthetic negative cases. Manifest SHA256 is `acc596572800a936e7c319a3adcbe1cd6547f8968ca58c05757eb57cb69227c7`.
- Bodies and manifest order/expected verdicts are unchanged. Only the Web test loader paths moved from private campaign directories to these tracked directories.
- Malformed encoding, whitespace and unusual byte sequences are deliberate negative fixtures. Do not autoformat or normalize `.body` files.

The suite imports the shipped consumer. These historical fixtures do not replace final backend, real browser, worker, device or end-to-end acceptance.

## Current normal-only corpus

- `normal-wire.json` is the unchanged historical ASGI/PG corpus, SHA256
  `e3ee5b76d6a180d3a6d61462174c695989c444adc2f4bdb9c11a94d0aca47922`.
- `normal-wire-p0a.json` preserves the exact accepted P0-A corpus formerly held at
  the current path, SHA256
  `04fa85bd80ea052efb35c1fea781fe8dac01095da36addbc95fc1bca947877d2`.
  It remains historical evidence, not a current-source acceptance fallback.
- `normal-wire-current.json` is a separate explicit capture through actual private
  PostgreSQL and a selected separate-process worker. Its 12 positive rows are new
  exact ASGI response bytes; all 39 historical synthetic-negative rows are unchanged.
- Schema 2 embeds the final report, worker exits, actual import origins, native
  retirement and PG ownership/cleanup journal. It binds the complete src Python/SQL
  inventory, manifests and capture helpers. Hashes establish consistency, not
  authentication against a malicious local writer.
- `tools/normal_wire.py --output /absolute/new-directory` is an explicit capture
  operation, never run by fixture loading or ordinary Web tests. It does not
  overwrite this directory. Missing prerequisites and incomplete cleanup are
  failures, not permission to substitute old or synthetic positive responses.
- Promotion requires source review, exact artifact hashing, Node/Chromium replay
  and the current freshness guard. Do not edit pins alone or regenerate on test start.

See `docs/NORMAL_WIRE_VERIFICATION.md` for historical P0-A scope and
`docs/P0B1_EXECUTION_AUTHORITY.md` for the subsequent source/capture gates.
ASGI capture plus browser parser replay is not a TCP UI-to-worker workflow,
local-authority execution, W2 or DUT acceptance.
