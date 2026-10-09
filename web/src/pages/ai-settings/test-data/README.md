# Producer wire witnesses

These four JSON files are exact, unformatted HTTP response bytes retained from
the independent AI-02 composition review's `producer-OnRPQw` run. They are not
handwritten success snapshots. Preserve the bytes, including whitespace; code
formatters must not rewrite them.

| File                                          | Original response SHA-256                                          |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `numeric-tld-put-response.json`               | `664e9479690131b061b378363c5421231cf98397a25234bc35a5d324144df718` |
| `hex-looking-host-put-response.json`          | `6ef3c0c0671ad7fef3c915fd062fe51f6a3796ad3e8e01e913077bc54111a4f5` |
| `unicode-cyrillic-casefold-put-response.json` | `e8fe170ed24b03c3f9fcf5b848618a11927d1dd8d5d7792497a85181982c2d58` |
| `unicode-latin-casefold-put-response.json`    | `0fa21bd2fe7c088748c3e32f0287b6173ffde577137030ee5807fcb39facd044` |

`producer-compatibility.test.ts` feeds these bytes into the shipped client.
`producer-differential.test.ts` additionally executes the current real TestClient
serializers against owned temporary state through `tools/producer_oracle.py`.
It compares accepted literal profiles and rejected controls, not constructed
success-response objects. All endpoint values are inert metadata.

`unicode-differential.test.ts` uses the project `.venv/bin/python` to compare
all Unicode code points, seeded multi-character IDNA/URL cases and generated
file freshness. No browser or listener is started. Regenerate the runtime data
from the repository root with:

```sh
.venv/bin/python web/src/pages/ai-settings/tools/generate_unicode.py
.venv/bin/python web/src/pages/ai-settings/tools/generate_unicode.py --check
```

The generator rejects non-3.12 or non-Unicode-15.0.0 interpreters. Python's IDNA
codec uses Unicode 3.2 Nameprep normalization/prohibition/bidi tables separately
from current-runtime case mappings; the generator captures that distinction.
