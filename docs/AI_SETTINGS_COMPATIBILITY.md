# AI-02 configuration text compatibility

Companion clarification to AI_SETTINGS_CONTRACT.md. These semantics preserve the supported Python 3.12 producer language; they do not authorize endpoint execution.

- AI profile-name comparison is Python 3.12 / Unicode 15.0.0 full casefold.
  Browser comparison uses a complete generated nonidentity mapping and identity
  for all other code points, not native browser lowercase. Comparison never
  changes the stored/displayed name. Canonical/compatibility normalization is
  not applied to name/model fields.
- Name/model validation uses code-point limits and the producer's Unicode
  15.0.0 `Cc`, `Cf`, `Cs` exclusions and `str.isspace` boundary semantics.
  The same exclusions apply throughout nonempty Base URLs; whitespace anywhere
  in those URLs is rejected.
- Base URLs remain literal, inert draft metadata. Admission mirrors the actual
  AI-only backend's `urlsplit` authority grammar, Python 3.12 `idna` encoder
  (IDNA2003/Nameprep, its Unicode 3.2 normalization/bidi/prohibition tables and
  Unicode 15 B2 fallback mappings), and syntactic `ipaddress`/hostname checks.
  It is not WHATWG navigation parsing, IDNA2008/UTS46, DNS existence checking,
  or permission to connect. The backend remains the authoritative validator.
- Numeric/hex-looking DNS final labels, Unicode-dot mappings, unassigned IDNA
  characters, and syntactically valid ASCII ACE-looking labels retain the
  producer's accepted language. This does not admit IPv4 shorthand, leading-zero
  IPv4, numeric invalid addresses, malformed IPv6, empty/out-of-range ports,
  credentials, percent-encoded authorities, query/fragment, whitespace/control
  characters, backslashes, or over-limit strings.
- Table generation and byte-freshness checks must execute through the project
  `.venv/bin/python` (3.12 / Unicode 15.0.0). Wrong runtime versions fail rather
  than silently regenerating different semantics. Native browser Unicode and
  URL versions do not decide AI validation.
- Closed field sets/types, profile cap, response schema, revision/CAS, read/save
  recovery, native dialogs, App guards, and execution denials are unchanged.
  Browser composition acceptance remains a separate parent-owned gate; Node/
  jsdom differential passes do not assert that Chromium has been rerun.
