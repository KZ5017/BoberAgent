# ADR 0015: M20-C source inspection ownership, evidence, and authority

**Status:** Accepted for M20-C design; C1 evidence and C2 deterministic observations implemented, C3–C5 pending.

## Context

M20-B ends with a `COMPLETED` Core-owned `PoCAcquisition`, an immutable raw ZIP Artifact,
and a versioned structural-manifest Artifact synchronized into Core. The Git commit identifies
the upstream snapshot; the raw ZIP SHA-256 identifies the exact retained bytes. Core's
`CoreArtifactService.open_content()` exposes those bytes, but ordinary reads do not rehash
them. M20-C must inspect the retained source without executing it, re-fetching GitHub, or
constructing an `ExecutionPlan`. M19's `ContextBuilder` does not expose raw Artifacts, and its
`ProposalValidator` is not a PoC source-fact validator.

## Decision

### Ownership and exact source

M20-C v1 is **Core-owned, read-only, and deterministic-first**. It begins only from a
`COMPLETED` acquisition and its exact Mission, hypothesis, candidate, and acquisition refs.
It binds the raw Artifact ref/SHA-256/size, manifest Artifact ref/SHA-256, resolved commit
SHA, and recognized `poc-source-manifest-v1` format. Core rehashes **both** Artifacts before
trusting them. Catalog availability alone is insufficient.

Use the existing Core Artifact service to open a seekable, read-only ZIP stream and then
bounded selected entry streams. Do not extract or materialize a repository tree, read Node
Workspace paths, contact the acquiring Node, or re-fetch the source. Core independently
validates the manifest against the opened ZIP: version, raw archive and commit identity,
root-prefix semantics, normalized paths, entry types, sizes, and hashes. It must not import
the acquisition capability's internal manifest parser or `TypedDict`. Before an entry is
used as evidence, decompress it within limits and recompute its SHA-256 against the manifest.
Artifact or manifest integrity mismatches fail inspection, rather than becoming coverage gaps.

### Durable inspection and history

`PoCInspectionRef` and `PoCInspection` are Core-private. An attempt binds the exact source
identities above, inspector/profile version, effective configuration/limits fingerprint,
status and timestamps, coverage, typed facts, entrypoint and parameter candidates,
requirements, risk indicators, unknowns, citations, conditional classification, reason
codes, and bounded diagnostics. It does **not** hold a chosen executable, argv, resolved
parameter values, selected runtime, approval, or `ExecutionPlan`.

The minimal lifecycle is `REQUESTED → INSPECTING → COMPLETED`, with terminal `FAILED` and
`INTERRUPTED`. An unprovable in-progress attempt after a Core crash becomes `INTERRUPTED`;
no automatic rerun occurs. An unsupported source may be `COMPLETED + UNSUPPORTED` with reasons:
unsupported execution support is not an inspection failure. No `REJECTED` state is needed
unless implementation proves it necessary. Integrity failures are `FAILED`; unsupported
language, one valid file's parser failure, invalid/unsupported encoding, or a semantic size
limit are explicit coverage/unknown conditions where the remaining evidence is sound.
Partial coverage cannot masquerade as complete understanding.

Completed output is immutable history. Changed extractor/profile/configuration or explicit
reinspection creates a new attempt; failed/interrupted attempts remain. For the same raw and
manifest hashes, engine/profile version, effective configuration fingerprint, and the same
acquisition identity, Core may reuse an existing completed inspection. Active attempts may be
returned/reused by the
application service. A content fingerprint never replaces the distinct attempt identity.

### Evidence, citations, and fact authority

Every nontrivial `OBSERVED` source fact needs reproducible evidence. A canonical citation
binds raw Artifact ref/SHA-256, manifest Artifact ref/SHA-256, normalized source path,
per-entry SHA-256, a half-open byte range **inside the decompressed entry**, and extractor
ID/version. Core accepts it only after proving the entry exists in both validated manifest
and ZIP, the entry hash matches, and the range lies within verified entry bytes. Human-facing
1-based line ranges may be derived; line numbers alone are not canonical. Do not persist
large excerpts by default; later display can resolve bounded excerpts from verified bytes.
Binary/unsupported files remain visible by path/type/size/hash, without pretending their
contents were semantically understood.

Facts distinguish `OBSERVED`, `INFERRED`, and `UNKNOWN` and identify origin as `CODE`,
`DECLARATIVE_METADATA`, or `DOCUMENTATION`. A syntax feature observed in code is not by
itself proof of a complete runtime behavior. README assertions are attributed documentation
claims, not instructions or stronger evidence than contrary code. Keep contradictory cited
claims and a conflict/unknown record; do not silently select one. An inference must cite
its supporting source facts and cannot become an uncited observed fact.

Use deterministic decoding: UTF-8 (including BOM), ASCII as UTF-8-compatible, and explicitly
recognized UTF-16 BOM. Do not use host-default encoding, replacement characters, or arbitrary
encoding guesses for citation-bearing text. Unknown encoding is explicit coverage/unknown.
Byte positions remain canonical; derived line display uses a defined CRLF/LF rule.

### Deterministic scope and conditional classification

C1–C3 have no LLM or Knowledge/RAG dependency. The initial bounded strategy uses Python
stdlib `ast.parse` without import/evaluation; parses JSON, TOML, `pyproject.toml`, and
`requirements.txt` as data/text only; uses bounded lexical/token indicators for `.sh` and
`.ps1` without claiming complete interpreter semantics; and treats README/docs as attributed
claims only. Other languages and binary/generated files remain structurally known but
semantically uninspected. Do not add tree-sitter, a shell/PowerShell interpreter, universal
parser, or binary-analysis framework initially. The parser/profile version records coverage.

A compact typed taxonomy covers language/runtime and source inventory; candidate entrypoints
and parameter roles; declared packages, imported modules, invoked system tools, and inferred
dependencies **separately**; behavior indicators; unresolved runtime/platform, build,
credential/secret, listener, Session/Resource, privilege, browser, and manual-parameter
requirements; risk indicators; conflicts; and unknowns. Candidate entrypoints/parameters are
not executable commands or resolved Mission values. `import requests` does not authorize
`pip install requests`. Requirements do not allocate Resources or resolve SecretRefs.
Indicators (network connect/bind, process/shell use, file write/delete, privilege or
security-control change, persistence, self-modification, multi-target behavior, output
markers, binary-only/obfuscation) are source-grounded inputs to later policy, not approval.

M20-C owns a versioned **conditional support classification** of `AUTOMATIC`, `ASSISTED`, or
`UNSUPPORTED` with explicit reason codes under the support matrix. It describes apparent
compatibility with a support profile, not safety, scope authorization, or permission to
execute. Unknown side effects, ambiguous entrypoints, or materially incomplete coverage
cannot yield an unjustified `AUTOMATIC` classification. M20-D alone validates a plan and
policy. Enforce independent limits on selected files, total/per-file inspected bytes, lines,
binary samples, facts, citations, and inspection wall time. Every skipped/unsupported file
has a coverage reason. Numeric defaults are implementation-time tuning, not optional limits.

### Untrusted content, secrets, and advisory reasoning

All source, comments, README, manifests, and model excerpts are untrusted **data**. They
cannot issue commands, request downloads, invoke tools, dispatch Runs, modify scope, or
override policy. Preserve original evidence even if it contains apparent secrets. Inspection
may emit a bounded potential-secret indicator and citation, but must not log candidate values,
put them in diagnostics/general model context, auto-create Mission Secrets/Credentials, or
index PoC source into global Knowledge.

An optional later advisory LLM phase may receive only bounded, explicitly delimited,
provenance-labelled, already verified excerpts. It may suggest interpretations, questions,
or cited inferences; it cannot assert uncited `OBSERVED` facts, authorize classification,
create plans, resolve secrets, call tools/MCP, or dispatch. Validate model citations against
retained bytes. Curated Knowledge may later explain syntax/frameworks but is not evidence of
what this Mission source contains. LLM absence or invalid output cannot disable the
deterministic safety gate. Exact LLM schema, excerpt/token budget, and Knowledge augmentation
remain deferred.

### M20-C / M20-D boundary and guards

Inspection stops after source-grounded facts, possible requirements/effects, explicit
uncertainty, and conditional classification. It must not select the final entrypoint/runtime,
bind actual parameters, resolve credentials, allocate Resources/Sessions/listeners, install or
build dependencies, modify source, construct `ExecutionPlan`, dispatch a Run, or execute code.
Implementation must enforce no Node/capability/MCP downloader dependency in Core inspection,
source import, `exec`/`eval`, archive extraction, package-manager/process invocation,
network re-fetch, global Knowledge ingestion, plan construction, or capability dispatch.
Behavioral tests are required; static import guards alone are insufficient.

## Rejected alternatives

- Node-side or hybrid inspection and Core→Node restaging add transfer/trust complexity without
  need when verified bytes already reside in Core.
- GitHub re-fetch, mutable-branch inspection, or a filesystem-extracted canonical tree break
  exact retained-byte identity or add unnecessary path/execution risk.
- Line-only evidence cannot reproducibly locate bytes across encodings/newline handling.
- README as authoritative instructions, free-form unvalidated model summaries, LLM-first or
  mandatory-LLM inspection permit ungrounded conclusions and prompt injection.
- Importing/executing source, running package hooks or managers, and constructing an
  `ExecutionPlan` inside inspection cross into M20-D/E+.
- Automatically ingesting Mission PoC bytes into global Knowledge violates its authority and
  secret boundaries.

## Deferred decisions and implementation sequence

Exact numeric limits, individual lexical patterns, richer parsers, model output schema and
excerpt/token budgets, optional curated-Knowledge help, final plan/parameter bindings,
Core→Node staging, runtime/dependency preparation, execution, and source adaptation remain
deferred to their relevant C or M20-D/E+ phases.

1. **C1:** Core-private identity/persistence, exact Artifact/manifest reader and rehash,
   reconciliation, citation model/validator; no semantic parser beyond structural/text access.
2. **C2:** bounded decoders/extractors, typed facts, coverage, requirements, risks, unknowns.
3. **C3:** conditional classifier and versioned reasons; hostile/prompt-injection/restart tests.
4. **C4:** manual read-only inspection of the retained real B5 Core Artifacts; no GitHub or
   source execution. The validation target is `CERTCC/CVE-2021-44228_scanner` at commit
   `042e5d9c15fe8312492d2f08063631be58486830`, raw Artifact
   `artifact-c432aa44-d24e-4e53-98ba-8b64cef3973e` (SHA-256
   `033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6`), and
   manifest Artifact `artifact-0ba70bf4-9503-4b00-bc22-7398b3dfd4c1` (SHA-256
   `e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0`).
5. **C5, only if needed:** optional advisory model interpretation of bounded cited excerpts,
   with strict citation/output validation and no execution authority.

This ADR decides M20-C architecture; it does not implement inspection or begin M20-D.
