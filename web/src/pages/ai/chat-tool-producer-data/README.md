# CHAT02A producer regression captures

These are component-level **actual producer bytes**, not HTTP/model/browser
acceptance and not synthetic frontend hash expectations.

- `producer.json`: byte-identical independent review corpus (17 grants, 90 wire
  rows), SHA256 `f6d451a242f3e09139314e565a834575ec4061b4098c6565f99917da6820ead5`.
- `extra-producer.json`: byte-identical independent review corpus, SHA256
  `96c5317bb2c86e6f02c12235795c504796d08d879c41e94b6beb2dd5d869bc31`.
  Its `differential` entries are explicitly **malformed derivatives**, not valid
  producer output. The two repaired gaps are `requested-with-proposal` and
  `finished-before-decision`.
- `grants.json`: eight additional actual `ToolLedger.create_grant` and `admit`
  captures using separate owned SQLite state. Covers ASCII, non-BMP Unicode,
  quotes, backslashes, newlines/CR/tabs, combined escaping, and the exact
  8192-UTF8-byte boundary in ASCII and non-BMP form. SHA256
  `d16496f249d49218fc81ef1d581ef1c3bd6bf4c4fd9ecb7303d13fefbd8153f9`.
  Producer source hashes are included in this file. The input boundary is bytes,
  not codepoints. State was removed by the capture helper after closing storage.

The first two files came from the preserved independent review at
`chat02a-independent-ui-to09fbd_`; they have never been rewritten. All three are
hash-bound by `chat-tool-producer-test-data.ts`. Assertions compare captured
commitments, not two implementations of the same synthetic fixture algorithm.

`capture-grants.py` can generate a **new** output file with the backend `src`
and `tests/chat` directories on absolute `PYTHONPATH`, using the project's
existing virtualenv. It refuses to overwrite an existing capture. Its
`--state-parent` must be an invocation-owned directory. No provider, domain
worker, network or shared database is involved.

`chat-tool-producer-wire.test.ts` runs `wire-oracle.py` against actual Pydantic
models. In an integrated tree its default source is the repository's `src`.
For the isolated frontend repair, `CHAT02A_PRODUCER_SOURCE` is explicitly bound
to the repair-owned byte-preserved independent backend snapshot; the helper
checks the imported module origin. This is a component oracle, not a backend
source change. It tests original malformed witnesses, legal requested and
awaiting states, and microsecond before/equal/after terminal Decision ordering.

The original independent probes are preserved separately in the repair evidence
folder, with only import/corpus/output path bindings changed for replay. One
saved-input probe deliberately characterizes the OLD bug (a valid grant must
not dispatch); it is preserved and its post-fix failure is reported, not edited
into a false green. Persistent positive hook regressions instead assert exact
captured-message dispatch, POST→GET recovery, explicit continuation, unchanged
later editor text, and no duplicate grant POST.
