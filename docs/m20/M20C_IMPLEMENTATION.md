# M20-C — Source Inspection + Conditional Support Classification

**Status: CLOSED.** The operator completed calibrated real C4 acceptance with C1@1,
C2@2 and C3@2: all COMPLETED, final classification UNSUPPORTED, Core reopen PASS and
identical-invocation reuse PASS. C5 is optional advisory future work, deferred and not
required for closure. M20-D has not begun. Inspection is Core-owned and offline;
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
execution. C3 adds classification separately; neither C1 nor C2 implicitly classifies source.

## C2 deterministic source observations

Use `CorePoCInspectionService.create_semantic(...)` then the existing explicit `inspect(ref)`
pump. The profile is `m20-c2-deterministic` version `2`; its strict Core-private JSON document
is `m20-c2-deterministic-v2`. Semantic rules changing materially require a new profile version.
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
C3 classification is described below; calibrated C4.1 real-source acceptance is complete.
C5 advisory reasoning remains optional/deferred, not a closure prerequisite. M20-D+ has not begun.


## C3 deterministic conditional support

Profile `m20-c3-support-classifier@2` produces the frozen, extra-forbidden Core-private
`m20-c3-support-classifier-v2` document. **Classification is not authorization, a validated
ExecutionPlan, runtime readiness, a safety guarantee, or permission to execute.**
A completed C3 attempt means classification was determined from retained C2 evidence;
`COMPLETED + UNSUPPORTED` is normal.

```python
from boberagent_core.inspections import CorePoCSupportClassificationService

classifier = CorePoCSupportClassificationService(database)
request = classifier.create(completed_c2.inspection_ref)
completed_c3 = classifier.classify(request.inspection_ref)
```

The service accepts only persisted `COMPLETED` C2 output and revalidates its envelope,
limits, citations/source binding and document. It never opens Artifacts, reads ZIP entries,
runs extractors, or contacts a Node. Output pins the C2 attempt ref and canonical semantic
SHA-256, with reasons referencing C2 item/conflict IDs and coverage paths. Resolving those
IDs leads to the original citations; no source excerpts are duplicated. Attempt timestamps
are separate from the deterministic result document.

### Fixed v2 rules and precedence

Hard support blocker wins over an assistance requirement, which wins over AUTOMATIC.
The classifier emits every applicable reason, not just the first matching rule. Reasons,
evidence refs and blockers are deduplicated/sorted. Codes are a closed `ReasonCode` enum;
each code is its fixed profile rule identifier, not model-written policy prose. Positive
codes explain the conditional Python target/entrypoint/coverage gates; `NON_BLOCKING_UNKNOWN`
retains nonmaterial gaps without pretending all repository bytes were understood.

| Gate | C3-v2 behavior |
| --- | --- |
| AUTOMATIC | One code-grounded observed Python entrypoint candidate, exactly one required target-host/URL parameter, adequate material coverage, and no blocker or assistance requirement |
| Entrypoints | None credible: UNSUPPORTED; multiple credible candidates: ASSISTED operator selection, never a chosen final executable |
| Runtime | Python is the only initial AUTOMATIC class; shell is ASSISTED; PowerShell/JavaScript are UNSUPPORTED in v2, even though C2 can inspect some syntax |
| Parameters | Credential/username: ASSISTED; callback: ASSISTED listener; input file/mode/unknown required or indeterminate role: ASSISTED manual resolution; explicit optional cosmetic unknown can be nonblocking |
| Target | Missing or competing Python target parameters block support; explicit mass-target/uncontrolled behavior unknowns block AUTOMATIC, without inventing a mass-target detector |
| Privilege | Observed code/metadata privilege requirement or privileged-execution risk: UNSUPPORTED; a privilege-check function alone is not a requirement |
| Authority | Documentation risk/privilege claims require review, not strong observed-risk classification; inferred risk is material uncertainty, not upgraded to OBSERVED |
| Hard typed risks | Destructive filesystem, arbitrary-command and security-control modification indicators block support and retain cited item refs |
| Effects | Process/shell/service/registry gates unchanged. FILE_WRITE/DELETE: literal bounded extent requires filesystem review; unknown extent is material uncertainty; observed broad extent blocks as unbounded. Primitive type alone does not prove destructive risk |
| Credentials/listeners | ASSISTED explicit prerequisites only; no Secret values, grants, Resource/Session allocation or callback bindings |
| Browser/build/environment | Representable bounded environment/manual/build/runtime requirements are ASSISTED; no preparation, build, installation or reviewed new runtime adapter |
| Dependencies | Stdlib-looking imports do not add a requirement; understandable third-party/declared/local/system-tool dependencies require ASSISTED review; unknown dependencies block support; no install commands |
| Conflicts | Every current typed runtime/credential conflict blocks support explicitly; neither source wins by convenience |
| Unknowns | Unknown material semantics default to UNSUPPORTED. Only enumerated entrypoint-choice, lexical-only and parameter-role gaps become assistance; irrelevant assets/helper main-guard absence/explicit cosmetic options may be nonblocking |
| Coverage | Unexplained partial, parser/encoding/binary/limit/unsupported material source blocks support; collection truncation blocks even if the unknown collection filled |

Aggregate C2 `EXTRACTOR_LIMITATIONS` unknowns retain the severity of their explicit underlying
causes. A bare unexplained aggregate still blocks. Explained partial coverage can require
assistance or be nonblocking; it never hides parser/limit failures. Source helpers without
their own main guard need not be independent entrypoints, but their other unknowns/effects
are still evaluated.

Relevance is conservative: unsupported/unknown file types, executable helpers, generated/vendor
source and dependency metadata are material by default. Directory rows and documentation/
image assets may be nonmaterial; a substantive non-documentation item on that path overrides
the asset exception. A skipped PNG screenshot alone does not make a Python checker unsupported.
Documentation requirements/conflicts are still evaluated even though the prose file is not
an execution entrypoint. Unknown relevance for a helper is not optimistic AUTOMATIC support.

### History, limits and recovery

No migration is needed: the existing `poc_inspections` attempt table stores versioned output
and typed configuration JSON. `ClassificationInspectionLimits` extends the existing request
configuration with C2 ref/digest and `ClassifierConfiguration` (4000 semantic/conflict items,
10,000 coverage paths by default). Inherited C1 evidence limits remain compatibility fields,
not a reason for C3 to read source. Bounds cannot disable policy gates.

The fingerprint includes this input identity and effective classifier configuration.
Equivalent requested/completed C3 attempts reuse; changed C2 identity/configuration or
`force_new` creates distinct history. Material policy changes require a new classifier
profile version, never reinterpret an existing completed document. C1/C2 histories and
their decoding remain unchanged. Failed/interrupted attempts are retained, not silently
rerun. Restart recovery marks unproven INSPECTING C3 attempts INTERRUPTED; REQUESTED survives.
Unexpected classifier defects persist safe FAILED diagnostics without exception/source text,
not a guessed support class. Out-of-band changes to a pinned C2 input fail classification.

### Limitations and validation

C2 syntax observations are bounded, not complete program understanding. C3 adds **no**
persistence, self-modification, obfuscation, mass-target, browser, interactive-input or
source-repair detectors. Those classes are evaluated only if represented by existing typed
requirements/risks/unknowns; material unmodeled unknowns fail closed. Typed unit fixtures test
these uncertainty paths without asserting that current extractors detected them.
No claim is made that absent indicators prove non-interaction, a single actual destination,
bounded output, or harmless runtime behavior. Later M20-D must validate actual bindings,
effects, runtime constraints and policy; richer evidence may be required before execution.

Run the offline synthetic proof:
`uv run python scripts/manual-smoke/m20c3_support_classification_smoke_test.py`.
It completes C1/C2/C3 with AUTOMATIC, ASSISTED and UNSUPPORTED examples, reopens Core and
checks immutable history. Output is only refs/profile/class/reason codes/evidence counts.
Tests separately cover authority, severity, precedence, exact reason binding, input permutation
determinism, strict serialization, coverage relevance, reuse/config/parent history and recovery.
Architecture guards forbid C3 source readers/extractors, execution, network, Knowledge and LLM.

**C4:** the initial @1 validation and calibrated @2 operator acceptance both completed;
M20-C is CLOSED. C5 advisory reasoning is optional/deferred and not required for closure.
M20-D final entrypoint/runtime/target/secret bindings and policy/ExecutionPlan,
and M20-E+ preparation, installation, staging, allocation and execution remain unimplemented.

## C4 real retained-source validation harness

**Calibrated C4 operator acceptance succeeded with C1@1/C2@2/C3@2; M20-C is CLOSED.**
See the [acceptance record below](#m20-c-closed-real-retained-source-acceptance).
This manual-only Core
composition uses existing production services, not synthetic replacement acquisition data:
`scripts/manual-smoke/m20c4_real_retained_source_inspection_smoke_test.py`.
Supply an existing absolute `--database`, existing absolute `--artifact-root`, and explicit
`--acquisition-ref`. Optional `--expected-raw-artifact-ref`,
`--expected-manifest-artifact-ref`, `--expected-raw-sha256`,
`--expected-manifest-sha256`, and `--expected-commit` fail on mismatched retained identity.
The exact operator commands are in [the manual-smoke guide](../../scripts/manual-smoke/README.md#m20-c4-real-retained-source-inspection-offline-opt-in).

The original B5 validation source is `CERTCC/CVE-2021-44228_scanner` (historical bindings):

- candidate `poc-candidate-5b2ead4a9b3847e4a2cf28d50b65a54b`, historical hit 4;
- acquisition `poc-acquisition-65dd487d65864967be3498f52e6c8038`;
- Run `run-m20b5-9313d1b8cade4372977bdd41df2c7d3a`;
- commit `042e5d9c15fe8312492d2f08063631be58486830`;
- Git tree `f7f9c58d621e09542d1d9d14f7b3174a40de18ba`;
- raw Artifact `artifact-c432aa44-d24e-4e53-98ba-8b64cef3973e`,
  SHA-256 `033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6`,
  305188 bytes;
- manifest Artifact `artifact-0ba70bf4-9503-4b00-bc22-7398b3dfd4c1`,
  SHA-256 `e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0`;
- structural manifest: 8 entries, 351930 uncompressed bytes, root
  `CERTCC-CVE-2021-44228_scanner-042e5d9/`.

Those identifiers are historical validation bindings, **not** default filesystem paths.
The harness can inspect another explicitly selected completed acquisition; the documented expected
bindings in the acceptance record below pin the calibrated C4 acquisition, distinct from the
original B5 attempt listed here. It does not search `/tmp`, re-fetch GitHub, create a
candidate/acquisition, contact Kali/MCP, or read provider/token/environment configuration.

### Preflight, production flow, and safe output

`--check-config` uses SQLite URI `mode=ro` with an escaped absolute path. It checks
COMPLETED acquisition, Mission/hypothesis/candidate ownership, receipt/catalog consistency,
expected identity and existing Artifact root, then prints bounded identity and C1/C2/C3 profiles.
It does not initialize filesystem storage, upgrade migrations, read Artifact content/ZIP entries,
or create attempts. Catalog existence is not proof of available or verified bytes; the real
run must establish that separately. Missing retained state stops with a bounded prerequisite
diagnostic; nothing is recreated.

Only `--real-retained-source` permits existing Core migrations to upgrade the selected DB and
new inspection history to be written. No C4 schema/dependency/production-service change is needed.
The harness rehashes both current Artifact streams against their receipts even when completed
history is reusable. C1 `create/inspect` verifies manifest and ZIP reconciliation with empty
entry selection; its verified-entry count is honestly zero. C2 `create_semantic/inspect`
independently verifies bounded selected entry bytes and records semantic coverage/citations.
C3 `create/classify` consumes that completed persisted C2, not source bytes.

Output includes all coverage statuses and per-file normalized paths/reasons/extractor versions,
typed collection counts, entrypoint candidates and derived line locations, parameter roles/
required flags and redacted string defaults, safe identifier-like dependency names, actual typed
requirements/behavior/risk codes, unknowns and conflicts with cited refs. It prints
CODE / DECLARATIVE_METADATA / DOCUMENTATION authority and OBSERVED / INFERRED / UNKNOWN separately;
an observed documentation claim is not a runtime fact. Terminal-control characters are escaped,
display strings bounded, arbitrary names redacted, and source excerpts never printed.

Up to five citation spot checks prioritize Python, PowerShell, shell and documentation if present.
Each goes through the production C1 citation validator, exact-byte reader and line mapper.
Only span length/SHA-256 and byte/line locator are displayed, never source/default/secret contents.
Classification prints C3 profile/document/digest, all reason codes, dispositions (including
blockers and assistance), linked C2 item/conflict/coverage refs and unknown/conflict blockers.
AUTOMATIC, ASSISTED and UNSUPPORTED are all honest completed inspection outcomes; none is
hardcoded as expected or translated into execution permission.

### Acceptance and durability

The harness disposes Core, reopens the same database/root, compares the whole immutable
acquisition and C1/C2/C3 records (including profile/version, source hashes, digest/classification),
and checks Artifact availability. It repeats the production create/inspect/classify flow and
requires identical attempt records and unchanged history. Rerunning the identical command
also reuses completed history. No force-new/reinspection mode or automatic interrupted-attempt
recovery is added.

Automated C4 tests use temporary synthetic persisted acquisitions only: read-only preflight,
missing/wrong/non-completed prerequisites, expected hash/ref/commit mismatch, all three honest
support classes through production services, citation and redaction output, changed cached bytes,
reopen mismatch, and history-growth rejection. Static and behavioral guards forbid network,
extraction, source execution, package installation, direct extractor/classifier invocation,
Secret resolution, Knowledge and LLM use. Existing C1–C3 tests retain exact-byte and migration
coverage. The operator met the real acceptance gate on retained state: complete integrity,
durable/reusable history, and an honest classification, recorded below. Another real rerun is
not required for this documentation closure.
Missing historical files require a separate operator decision, not automatic B5 acquisition.

C4 always stops after reporting. C5 and M20-D+ remain untouched: no final entrypoint, argv,
target/callback/secret bindings, plan, policy approval, runtime preparation, source staging,
installation, allocation or execution.


## C4.1 real-source semantic calibration

The operator's first real C4 inspection of CERTCC/CVE-2021-44228_scanner at
`042e5d9c15fe8312492d2f08063631be58486830` successfully completed C1/C2/C3,
reopened Core, and reused identical history without fetching, execution, LLM or a plan.
The UNSUPPORTED result is not assumed wrong. Its primitive-only filesystem reasons were
overstated: C2 promoted every recognized delete primitive to DESTRUCTIVE_FILESYSTEM;
C3 mapped every FILE_WRITE/FILE_DELETE to UNSUPPORTED_UNBOUNDED_EFFECT.

### Calibrated deterministic rules

Current profiles/documents are C2@2/`m20-c2-deterministic-v2` and
C3@2/`m20-c3-support-classifier-v2`. C1 stays @1. No migration, Contract change,
dependency or new execution authority is introduced.

- FILE_WRITE/FILE_DELETE remain CODE/OBSERVED syntax, including Python remove/unlink,
  Path.unlink/write_text/write_bytes, writable open and shutil.rmtree, shell rm/redirection,
  and PowerShell Remove-Item/content operations.
- Scope is persisted in the existing behavior `reason` as
  `FILE_EFFECT_SCOPE_BOUNDED`, `FILE_EFFECT_SCOPE_UNKNOWN` or `FILE_EFFECT_SCOPE_BROAD`.
  The derived typed `FileEffectScope` view adds no serialized fields to old documents.
- BOUNDED is deliberately only a nonrecursive, literal single basename
  (conservative ASCII identifier/file-name grammar). It is not evidence of workspace
  confinement, symlink safety, resolved runtime effects or approval. C3 emits
  REQUIRES_FILESYSTEM_REVIEW; it does not silently make mutation AUTOMATIC.
- Variables, computed/absolute/compound paths, multiple operands, recursive non-root targets
  and unrecognized syntax stay UNKNOWN, with an UNKNOWN/CODE cited item in addition to the
  observed primitive. No assignment propagation or filesystem/path resolution is attempted.
  C3 retains UNSUPPORTED_MATERIAL_UNKNOWN with actual behavior/unknown item refs.
- BROAD deletion requires literal recursive filesystem root or root wildcard:
  standalone shell `rm -rf /` / `rm -rf /*`, standalone PowerShell
  `Remove-Item -Recurse -Force 'C:\*'`, or Python `shutil.rmtree("/")`.
  Shell/PowerShell lexical scope proof requires command-position syntax; quoted words,
  echo/Write-Output mentions and unresolved substitutions are not strong destructive proof.
  Wildcards require language expansion semantics: quoted shell wildcards, Python literal stars,
  and PowerShell -LiteralPath wildcards remain UNKNOWN rather than broad proof.
  Broad deletion emits DESTRUCTIVE_FILESYSTEM/CODE/OBSERVED from the whole operation span.
  C3 retains UNSUPPORTED_DESTRUCTIVE_BEHAVIOR and UNSUPPORTED_UNBOUNDED_EFFECT.
- Other process, shell, environment, network, dependency, runtime, credential/listener,
  privilege, binary, coverage/conflict and target-boundary gates are unchanged.
  In particular, UNSUPPORTED_TARGET_BOUNDARY has no new exceptions.

C2/C3 collection caps, deterministic IDs/sort/dedup, evidence hash/byte binding, and
UNSUPPORTED > ASSISTED > AUTOMATIC precedence remain. Long/ambiguous syntax is never
evaluated to obtain a scope. The new filesystem helper is pure lexical/AST support;
C3 cannot import it or rescan source.

### Historical preservation and real rerun

Historical operator records remain immutable/readable:

- C1 `poc-inspection-e3bad26d882449e196d9146b841d42e8`;
- C2@1 `poc-inspection-f4613eced4a64d339367582978d2ae57`;
- C3@1 `poc-inspection-5897302e458a4514a29039b26e6e71fc`.

Completed @1 attempts return their stored documents, preserving JSON and semantic digest.
New creates only use @2; C3@2 rejects a C2@1 parent instead of reinterpreting old evidence.
Incomplete retired attempts are not silently executed with new semantics.
C4 composes current services, producing separate @2 records and reusing them subsequently.

The accepted calibrated acquisition is
`poc-acquisition-2f6a3658a57c42f5ae2252edf1736352`, raw
`artifact-032c7c87-c1c2-402a-ba2e-269545766f3a` (SHA-256
`033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6`) and manifest
`artifact-463d3e1b-e38a-41ed-afb9-b59fc33bee56` (SHA-256
`e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0`).
These are operator-supplied bindings, not auto-discovered filesystem locations.
The command is in the manual-smoke guide; it still requires explicit existing absolute paths.

Offline regressions cover Python/PowerShell/shell bounded, dynamic and root-delete cases,
non-command mentions, evidence references, precedence, deterministic repeated analysis,
v1 JSON/digest preservation/reopen, @2 selection/reuse and actual C4 service composition.
No operator retained source was automatically re-inspected during calibration.
**M20-C is CLOSED:** calibrated real retained-source operator acceptance succeeded.
The final real classification is UNSUPPORTED, observed from evidence rather than prescribed.
C5 is optional/deferred and not required for closure. M20-D has not begun.


## M20-C CLOSED: real retained-source acceptance

This closure records the operator-reported successful calibrated C4 rerun; it does not rerun
or modify retained evidence, classification rules, production code, or historical results.

| Immutable binding | Accepted value |
| --- | --- |
| Source | CERTCC/CVE-2021-44228_scanner |
| PoCAcquisition | `poc-acquisition-2f6a3658a57c42f5ae2252edf1736352` |
| Commit | `042e5d9c15fe8312492d2f08063631be58486830` |
| Raw Artifact | `artifact-032c7c87-c1c2-402a-ba2e-269545766f3a` |
| Raw SHA-256 | `033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6` |
| Manifest Artifact | `artifact-463d3e1b-e38a-41ed-afb9-b59fc33bee56` |
| Manifest SHA-256 | `e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0` |

| Authoritative profile | Document | Real acceptance |
| --- | --- | --- |
| `m20-c1-evidence@1` | `m20-c1-evidence-v1` | COMPLETED |
| `m20-c2-deterministic@2` | `m20-c2-deterministic-v2` | COMPLETED |
| `m20-c3-support-classifier@2` | `m20-c3-support-classifier-v2` | COMPLETED; UNSUPPORTED |

**Core reopen: PASS. Identical-invocation reuse: PASS.** Durable inspection and classification
survived reopen, and the same invocation reused history without duplicate attempts.

C4.1 was necessary because the initial @1 rules promoted ordinary deletion syntax into
destructive risk and ordinary writes/deletes into unbounded-effect reasons without proven scope.
The calibrated real run retained FILE_DELETE/FILE_WRITE observations while removing false
automatic DESTRUCTIVE_FILESYSTEM, UNSUPPORTED_DESTRUCTIVE_BEHAVIOR and
UNSUPPORTED_UNBOUNDED_EFFECT where destructive/unbounded scope was not proven.
UNKNOWN file-effect scope remains explicit and fail-closed; genuinely broad/destructive
evidence still blocks under the unchanged calibrated rules.

Remaining evidence-driven blocker categories include:

- `UNSUPPORTED_INSUFFICIENT_COVERAGE`;
- `UNSUPPORTED_MATERIAL_UNKNOWN`;
- `UNSUPPORTED_TARGET_BOUNDARY`.

Assistance reasons include:

- `REQUIRES_ENTRYPOINT_SELECTION`;
- `REQUIRES_MANUAL_PARAMETER`;
- `REQUIRES_RUNTIME_CONFIRMATION`;
- `REQUIRES_DEPENDENCY_REVIEW`.

UNSUPPORTED is the honest conditional-support result, not inspection failure, a safety
guarantee, target vulnerability confirmation, authorization or permission to execute.
No gate was weakened to obtain closure.

The accepted run involved **no network, source execution, extraction, installation, Secret
resolution, LLM, Knowledge/RAG, ExecutionPlan, staging, authorization or runtime preparation**.
Historical C2@1/C3@1 records listed above remain immutable; @2 output is separate versioned
history, not a rewrite or reinterpretation of @1.

**C5 is optional advisory future work and remains deferred. It is not required for M20-C
closure. M20-D has not begun and remains untouched.** Closing this phase does not close the
overall M20 pipeline or initiate plan/policy/runtime work.
