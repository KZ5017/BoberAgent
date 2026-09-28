# M20-C1 exact source-evidence foundation

**Status:** C1 and C2 implemented. C3–C5 remain unimplemented. Inspection is Core-owned and offline;
it reads only retained Core Artifacts from a `COMPLETED` `PoCAcquisition`. It does not import,
extract, compile for execution, execute, or re-fetch acquired source. C1 does not interpret semantics;
C2 adds the bounded deterministic profile described below.

`PoCInspectionRef` is a Core-private logical attempt ID, distinct from acquisition, Artifact,
commit, and content hashes. Creation checks Mission→hypothesis→candidate→acquisition ownership,
the completed receipt, both Artifact catalog descriptors, and the resolved commit. A request
stores exact raw ZIP/manifest refs and hashes, raw size, profile ID/version, explicit C1 limits,
selected structural verification paths, and a SHA-256 fingerprint of those settings. The profile
is `m20-c1-evidence` version `1`; changing profile/version/limits/selected paths creates a new
attempt. For an identical acquisition/source/profile/config, a completed or requested attempt
is reused unless explicit `force_new` is requested. Failed/interrupted attempts are historical
and are not silently retried.

The lifecycle is `REQUESTED → INSPECTING → COMPLETED` or terminal `FAILED`/`INTERRUPTED`.
`COMPLETED` means only that both retained Artifacts rehashed, the strict
`poc-source-manifest-v1` structure and identity validated, the ZIP inventory reconciled,
and explicitly selected entry bytes (if any) passed SHA-256/size verification. It does **not**
assert a source language, entrypoint, dependency, runtime safety, or execution support.
Unselected entries are recorded as unverified structural coverage. A failed exact-byte check
stores only a bounded reason code, not source text. `recover_interrupted()` conservatively
marks unproven `INSPECTING` attempts interrupted after restart; `REQUESTED` survives and may
be inspected later. Completed output is immutable.

Core opens both Artifacts through `CoreArtifactService`, streams and rehashes them before ZIP
parsing, then validates the bounded JSON manifest independently of the acquiring capability.
It checks version, exact raw hash/size, commit, archive representation, root prefix, sorted
unique normalized paths, types, sizes, count and total. A bounded ZIP central-directory
preflight rejects unsupported counts and raw NUL names before `zipfile` constructs entries;
reconciliation rejects missing/extra entries, unsafe paths, unsupported file types, and size
disagreement. A selected regular file is decompressed under C1 limits and its actual bytes are
SHA-256 checked against the manifest. No archive extraction API is used.

The default independent limits are 16 MiB manifest, 10,000 ZIP entries, 64 MiB per verified
entry, 512 MiB total selected-entry verification, 64 KiB per citation, 100 citations, and
30 seconds wall time. Tests can override them. Exceeding a selected-entry or total bound fails
the attempt; unselected entries remain explicit unverified coverage. No oversized entry becomes
citable evidence.

A canonical `SourceCitation` binds both Artifact refs and SHA-256 identities, normalized ZIP
relative path, verified per-entry SHA-256, a **nonempty half-open byte span** `[start, end)` in
the decompressed file, and reader ID/version. Core validates source binding, entry identity,
byte bounds and citation length before returning exact cited bytes. No large excerpt is stored.
Human 1-based line positions are derived only from deterministically decoded UTF-8 (including
BOM), ASCII-compatible bytes, or explicit UTF-16 LE/BE BOM. LF and CRLF each count as one line
separator; an undecodable or binary span has no line display. Byte offsets remain authoritative.

SQLite migration `0012_m20_c1_inspection` adds only the private attempt table and versioned
structural output JSON. It upgrades from `0011_m20_b3_fixture_mode` without rewriting older
rows. The offline manual check is
`uv run python scripts/manual-smoke/m20c1_inspection_evidence_smoke_test.py`.

C2 implements bounded deterministic source-fact extraction, requirements, risks, and semantic coverage;
C3 owns conditional support classification. C4 may inspect the retained real B5 Artifacts only
after deterministic semantic inspection exists. M20-D+ owns plans, policy, preparation, and
execution. Classification and later phases are not implemented by C1/C2.

## C2 deterministic source observations

Use `CorePoCInspectionService.create_semantic(...)` then the existing explicit `inspect(ref)`
pump. The profile is `m20-c2-deterministic` version `1`; its strict Core-private JSON document
is `m20-c2-deterministic-v1`. Semantic rules changing materially require a new profile version.
The inherited C1 attempt table stores the versioned document; no schema migration, per-fact
tables, Contract changes or new dependencies are needed. Existing C1 limit JSON/document output
still decodes as C1 and remains immutable. C2 uses distinct profile/config reuse keys, preserves
failed/interrupted history, and uses the same conservative recovery service.

Every emitted observed item has a C1-validated nonempty byte citation: raw/manifest refs and
hashes, path, entry hash, span, extractor ID/version. IDs are deterministic hashes of location,
extractor and observation category, not attempt IDs. All facts/candidates/requirements/indicators
carry `OBSERVED`, `INFERRED` or `UNKNOWN` authority and `CODE`, `DECLARATIVE_METADATA` or
`DOCUMENTATION` origin. This profile emits observed syntax/claims and explicit unknowns; it
does not manufacture runtime confirmations or inferred prerequisites. Inferred output requires
cited supporting fact refs if used by future versions.

| Source | Implemented C2 boundary |
| --- | --- |
| Python | Bounded stdlib AST observations: imports, top-level definitions, main guards, literal argparse declarations, argv, recognizable network/process/filesystem/environment/privilege-check syntax |
| PowerShell | Partial lexical indicators and simple typed `param()` declarations; no interpreter or complete grammar |
| Shell | Partial lexical tokens, shebang, positional parameters, simple getopts; no shell/parser executable |
| pyproject / requirements | Literal PEP 621 Python requirement, simple dependency declarations, script candidates; no build backend/import/package installation |
| JSON / other TOML | Strict data parsing only; unknown schemas explicitly partial, arbitrary strings never evaluated |
| README / Markdown | Narrow attributed runtime, dependency, usage, target and prerequisite claims; hostile instructions have no authority |
| Other / generated / binary | Structural coverage only, or verified binary skip; no binary-analysis claims |

Selection uses sorted validated manifest paths. An empty explicit selection means supported
files up to the configured budgets; a nonempty selection restricts it, with other files explicitly
covered as not selected. Directories, unsupported extensions, vendor/node_modules/cache/build/dist,
and `.min.`/`.generated.` names are skipped structurally. Binary detection uses a bounded 4096-byte
control-byte prefix (BOM-aware) plus control-character checks after strict decoding. Only UTF-8,
UTF-8 BOM, ASCII-compatible UTF-8 and explicit UTF-16 LE/BE BOM are supported. No guesses or
replacement decoding. AST UTF-8 columns are converted through decoded character boundaries back
to the original retained encoding. LF/CRLF preserve canonical byte offsets; lone CR is explicitly
skipped as unsupported newline representation. Dependency tokens are bounded to 512 characters
before the simple requirement parser; complex/multiline TOML source locators remain unknown.

Parameters expose names, conservative roles, statically known required flags and numeric/boolean
defaults; string defaults are **redacted**, never Mission bindings. Imported modules are separate
from declared packages: stdlib-looking is relative to the inspector's Python stdlib inventory;
known common third-party-looking names, local/relative and unknown categories do not promise
installation or package resolution. Entrypoints are main-guard, shebang or declarative-script
**candidates**, never argv or selected executables. Syntax indicators cannot prove a side effect
occurred. Shell/PowerShell always retain a lexical-only unknown and partial coverage; comments
and ordinary quoted strings are not executable-word indicators.

Conflicts retain both cited observations without choosing a winner. Different documentation
and declarative Python requirements are marked as potentially differing claims, not solved
version-range incompatibility. A documented “no credentials required” claim and a code credential
parameter similarly remain a disagreement; the inspector does not authenticate or decide policy.

Independent default semantic limits: 100 attempted files, 8 MiB total, 256 KiB/file, 5000 logical
line starts/file, 20,000 AST nodes/file, 200 facts, 50 entrypoints, 100 parameters, 100 dependency
observations, 100 requirements, 200 behavior indicators, 100 risk indicators, 100 unknowns,
50 conflicts. Inherited evidence limits still apply (including 100 total citations, 64 KiB/span
and 30 seconds wall time). Byte budgets are checked before decompression and exact entry SHA-256
verification precedes decoding/extraction. Wall time is cooperative between bounded operations,
not a hard OS preemption guarantee for stdlib parsers. Every output/selection bound hit remains
explicit in coverage and/or document `limit_reasons`, even if the unknown collection is full.

Coverage includes every manifest entry with size/hash, extractor version and encoding where
known: inspected, partial, unsupported, binary, encoding skip, limit skip, parser failure.
“Inspected” means the bounded extractor completed, **not complete program understanding**.
Semantic syntax/encoding/limit gaps normally complete with coverage/unknowns; integrity errors
fail the attempt. Unexpected inspector bugs durably fail with `INSPECTOR_INTERNAL_ERROR` and
raise that safe error, never become unknown or persist exception/source text.

Source stays immutable evidence. C2 does not persist arbitrary documentation prose, commands,
URLs, environment values or string defaults. Actual embedded-secret pattern detection is deferred:
no reliability claim, no Mission Secret/Credential creation, no source indexing or model delivery.
Explicit citation reads may return original sensitive evidence; ordinary output must not dump it.

Run the fully offline synthetic smoke (dev/pytest environment):
`uv run python scripts/manual-smoke/m20c2_deterministic_inspection_smoke_test.py`.
It uses the shared migration-backed fixture test, completes C2, reopens Core and prints only
bounded semantic metadata. No GitHub, Kali, MCP, live B5 Artifacts or network is involved.
C3 classification, C4 retained real-source inspection, C5 advisory LLM and M20-D+ remain deferred.
