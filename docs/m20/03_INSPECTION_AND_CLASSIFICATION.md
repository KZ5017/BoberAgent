# M20-C — Inspection and execution classification

**Status:** Architecture accepted in [ADR 0015](../adr/0015-m20-c-source-inspection-ownership-evidence-and-authority.md);
implementation not started. M20-C stops before `ExecutionPlan`, preparation, or execution.

## Goal and dependency

Inspect the verified M20-B source Artifact without running the PoC, installing its dependencies,
importing its modules, evaluating package hooks, or obeying its documentation. Produce typed
facts and explicit uncertainty, then classify the candidate as `AUTOMATIC`, `ASSISTED`, or
`UNSUPPORTED` under the [support matrix](00_SCOPE_AND_SUPPORT_MATRIX.md). Inspection is a gate,
not a rehearsal execution.

## Typed boundary

| Input | Output |
| --- | --- |
| Completed `PoCAcquisition` with Mission/hypothesis/candidate refs, raw ZIP and structural-manifest ArtifactRefs, their SHA-256 identities, size, resolved commit, and recognized manifest version | Core-private versioned `PoCInspection`, byte-grounded citations, coverage, typed facts/requirements/risks/unknowns, conditional classification and reason codes |

Core owns read-only inspection of the **exact synchronized M20-B Artifacts**. It rehashes raw
ZIP and manifest before trusting them, independently validates `poc-source-manifest-v1`
against the opened ZIP (identity, paths, types, sizes, hashes, root prefix), and verifies a
bounded decompressed entry against its manifest hash before citing it. Use the Core Artifact
service's seekable stream and selected ZIP entry streams; do not extract a repository tree,
contact the Node, re-fetch GitHub, or import the acquisition capability's manifest internals.
Availability alone is not integrity proof. An Artifact/manifest mismatch fails inspection.

`PoCInspectionRef` and `PoCInspection` remain Core-private. The record binds exact source
identities, inspector/profile version, effective limits/configuration fingerprint, lifecycle,
timestamps, coverage, typed output, citations and bounded diagnostics. Completed output is
immutable history. Reuse an existing completed inspection for the same source hashes,
engine/profile, and effective configuration; explicit reinspection or version/configuration
changes create a new attempt. Preserve failed/interrupted attempts. The lifecycle is
`REQUESTED → INSPECTING → COMPLETED`, with terminal `FAILED` and `INTERRUPTED`;
an unproven in-progress attempt after restart becomes `INTERRUPTED` without automatic rerun.
`COMPLETED + UNSUPPORTED` is valid: unsupported execution support is not inspection failure.

Planned `PoCInspection` records runtime/language and version hints; candidate entrypoints and
their confidence; dependency manifests; build and CLI parameters; target binding; environment,
credential/secret, listener/Resource/Session, and privilege requirements; filesystem, subprocess,
external-network, target-state, and cleanup behavior; expected outputs; source-modification
requirements; explicit risk flags and unknowns. Separate `OBSERVED`, `INFERRED`, and `UNKNOWN`
and origins `CODE`, `DECLARATIVE_METADATA`, and `DOCUMENTATION`. Every nontrivial observed
source fact needs a validated citation; an inference cites its supporting facts. Contradictory
claims remain separately cited with a conflict/unknown record. README claims cannot outweigh
contradictory code evidence.

Canonical citations bind both ArtifactRefs and SHA-256 values, normalized manifest path,
per-entry SHA-256, half-open byte range in decompressed entry, and extractor ID/version.
Accept only ranges within an entry verified against both ZIP and manifest. Human 1-based
line ranges are derived display data, not the canonical locator. Do not persist large source
excerpts by default. Deterministically decode UTF-8 (including BOM), ASCII-compatible text,
and explicit UTF-16 BOM; no host-default encoding, replacement characters, or arbitrary
guessing. Invalid/unsupported encoding is explicit coverage/unknown. Define reproducible
CRLF/LF handling for display line numbers while retaining byte positions as authority.

The initial deterministic profile uses bounded Python stdlib `ast.parse` without import or
evaluation; parses JSON/TOML/`pyproject.toml`/`requirements.txt` as data/text; uses only
bounded lexical/token indicators for `.sh` and `.ps1`; and records README/docs as attributed
claims. Other files remain structurally known and semantically uninspected. No universal
parser, shell/PowerShell interpreter, tree-sitter, or binary-analysis framework is required.
Separate declared package, imported module, invoked system tool, and inferred dependency.
Entrypoint and parameter roles are **candidates**, not argv or actual Mission bindings.
Requirements and risk indicators describe apparent behavior; they do not allocate Resources,
resolve Secrets, install dependencies, or authorize effects. The profile must enforce
independent limits on files, total/per-file bytes, lines, binary samples, facts, citations,
and wall time; skipped files have explicit coverage reasons. Numeric defaults are tuned during
implementation, but limits cannot be omitted.

Source text, README instructions, package metadata, and potential prompt injections are
untrusted data. They cannot invoke tools, network calls, ProcessService, policy overrides, or
dispatch. Preserve raw evidence, but do not copy possible secrets into diagnostics, logs,
general model context, Mission Secret/Credential storage, or global Knowledge. M20-C C1–C3
works without an LLM, Procedure Registry, or semantic RAG. If later added, the Reasoner sees
only bounded, delimited, provenance-labelled verified excerpts and proposes cited inferences
subject to a separate source-citation/output validator. It cannot assert uncited `OBSERVED`
facts or authorize classification. Curated Knowledge may explain syntax, never substitute for
evidence of what these retained bytes contain.

Classification is explicit, **conditional support**, and persisted with a profile version and
reason codes such as
`requires_credentials`, `requires_listener`, `multiple_entrypoints`,
`requires_privileged_runtime`, `binary_only`, `obfuscated_source`,
`requires_source_modification`, `destructive_behavior`, `unknown_side_effects`, or
`unexpected_network_destination`. Do not replace these reasons with a single score. Ambiguous
entrypoints, unknown side effects, or material coverage gaps prevent unjustified `AUTOMATIC`.
The classification does not mean safe, authorized, or ready to dispatch; M20-D policy still
decides. Invalid Artifacts or manifest/ZIP disagreement are `FAILED`; unsupported language,
encoding, parser coverage, or bounded semantic size may instead be explicit unknown/coverage
without discarding already verified facts.

## Reuse, additions, and non-goals

Reuse Core Artifact access and M20-B provenance. The current M19
`InterpretationResult`/`ActionProposal` and ContextBuilder do **not** encode full source
inspection. Any later model context/output must be narrow and separately validated. No
PoC-specific parser belongs in Core's World State reducer; no inspection model needs to enter
shared Contracts unless a future cross-component need is demonstrated.

No static-analysis claim that arbitrary PoC code is harmless, no sandboxed trial run, no build,
no package installation, no source rewriting, no automatic Finding, and no permanent Knowledge
ingestion. If inspection needs active execution to understand a source, it is not an inspection
shortcut; classify and stop for a separately reviewed design.

## Stop, security, and tests

Fail on inaccessible/corrupt Artifact, mismatched source hash, invalid trusted manifest, or
manifest↔ZIP disagreement. For unsupported binary/obfuscated source, ambiguous entrypoint,
unknown privileged/broad side effects, or source-directed prompt injection, retain evidence,
record explicit coverage/risks/unknowns and stop at an honest `ASSISTED`/`UNSUPPORTED`
classification rather than obeying the source or claiming it safe. A benign-looking README
cannot override detected code behavior.

Tests: known harmless Python fixture, absent/ambiguous entrypoint, manifest dependency parsing as
data, binary-only/obfuscated source, hidden external destination, declared listener/credential,
source modification, malicious README instructions, conflicting evidence, and deterministic
reclassification under the same profile. Manual validation should show file-level citations and
the exact reason for classification; it must not execute source. **Done** when an operator can
inspect the durable facts/reasons and M20-D can consume them without rereading untrusted prose.

Implement in order: **C1** Core-private identity/persistence, exact Artifact/manifest reader,
rehash/reconciliation, and citation validator (no semantic parser beyond structural/text
access); **C2** bounded deterministic extractors, typed facts, coverage, requirements/risks/
unknowns; **C3** conditional classifier, versioned reasons, hostile/prompt-injection/restart
tests; **C4** manual read-only inspection of the retained real B5 Core Artifacts (no GitHub or
execution); **C5 only if needed** optional advisory model over bounded verified excerpts.
The C4 target is `CERTCC/CVE-2021-44228_scanner` commit
`042e5d9c15fe8312492d2f08063631be58486830`, raw Artifact
`artifact-c432aa44-d24e-4e53-98ba-8b64cef3973e` (SHA-256
`033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6`), and
manifest Artifact `artifact-0ba70bf4-9503-4b00-bc22-7398b3dfd4c1` (SHA-256
`e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0`).
These bytes have **not** been inspected by this planning work.
