# Frozen Runs consumer fixtures

These are exact copies of the existing reviewed candidate's input bytes, not freshly generated backend results.

- `h1/selected-index.json`: 1,096 earlier H1 response entries, including repeated/legacy/seeded cases. Each referenced body retains its original SHA256 and relative name. Entries are not a count of independent worker acceptance tests.
- `parity/manifest.json`: 5,259 entries: 938 earlier H1 HTTP samples, 2 earlier I3 HTTP samples, and 4,319 labeled synthetic negative cases. Manifest SHA256 is `acc596572800a936e7c319a3adcbe1cd6547f8968ca58c05757eb57cb69227c7`.
- Bodies and manifest order/expected verdicts are unchanged. Only the Web test loader paths moved from private campaign directories to these tracked directories.
- Malformed encoding, whitespace and unusual byte sequences are deliberate negative fixtures. Do not autoformat or normalize `.body` files.

The suite imports the shipped consumer. These fixtures do not replace final backend, real browser, worker, device or end-to-end acceptance.
