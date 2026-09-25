# M20-C — Inspection and execution classification

## Goal and dependency

Inspect the verified M20-B source Artifact without running the PoC, installing its dependencies,
importing its modules, evaluating package hooks, or obeying its documentation. Produce typed
facts and explicit uncertainty, then classify the candidate as `AUTOMATIC`, `ASSISTED`, or
`UNSUPPORTED` under the [support matrix](00_SCOPE_AND_SUPPORT_MATRIX.md). Inspection is a gate,
not a rehearsal execution.

## Typed boundary

| Input | Output |
| --- | --- |
| Candidate/hypothesis refs, pinned source `ArtifactRef` and file inventory, selected Mission target evidence | Versioned `PoCInspection`, citations to source files/line spans or Artifacts, classification, reason codes, unresolved questions |

Planned `PoCInspection` records runtime/language and version hints; candidate entrypoints and
their confidence; dependency manifests; build and CLI parameters; target binding; environment,
credential/secret, listener/Resource/Session, and privilege requirements; filesystem, subprocess,
external-network, target-state, and cleanup behavior; expected outputs; source-modification
requirements; explicit risk flags and unknowns. Separate **observed source fact**, **inferred
requirement**, and **unknown**. Every claimed fact should cite inspected bytes or a named external
source. README claims cannot outweigh contradictory code evidence.

Deterministic inspection should inventory extensions/manifests, parse known declarative files as
data, identify entrypoint candidates and command-line parsing without importing, flag suspicious
constructs and destinations, and enforce time/size limits. It cannot prove arbitrary code safe.
M19-style Reasoner assistance may summarize bounded, provenance-tagged excerpts into a typed
proposal, but the Reasoner sees source text as **untrusted quoted data**, not higher-priority
instructions. Prompt injection in comments/README/issue text must not alter tool permissions,
scope, or classification. Deterministic validation checks references and structure; unsupported
or contradictory behavior remains `ASSISTED`/`UNSUPPORTED`, not model-certified safe.

Classification is explicit and persisted with a profile version and reason codes such as
`requires_credentials`, `requires_listener`, `multiple_entrypoints`,
`requires_privileged_runtime`, `binary_only`, `obfuscated_source`,
`requires_source_modification`, `destructive_behavior`, `unknown_side_effects`, or
`unexpected_network_destination`. Do not replace these reasons with a single score. The same
classification does not authorize execution; M20-D policy still decides.

## Reuse, additions, and non-goals

Reuse Core Artifact availability/hash, M17/18 curated Knowledge for bounded explanatory context,
M19 advisory Reasoner/provider pattern, and Contract logical refs. M19's current
`InterpretationResult`/`ActionProposal` and ContextBuilder do **not** already encode full source
inspection: add a narrow typed inspection output/context only after review. A deterministic
inspector and Core-owned inspection record are new. No PoC-specific parser belongs in Core's
World State reducer.

No static-analysis claim that arbitrary PoC code is harmless, no sandboxed trial run, no build,
no package installation, no source rewriting, no automatic Finding, and no permanent Knowledge
ingestion. If inspection needs active execution to understand a source, it is not an inspection
shortcut; classify and stop for a separately reviewed design.

## Stop, security, and tests

Stop on inaccessible/corrupt Artifact, mismatched source hash, unsupported binary/obfuscated
source, ambiguous entrypoint/target, unknown privileged or broad side effects, or source-directed
prompt injection. Retain the source and an explainable inspection/diagnostic; do not discard
evidence or guess missing facts. A benign-looking README cannot override detected code behavior.

Tests: known harmless Python fixture, absent/ambiguous entrypoint, manifest dependency parsing as
data, binary-only/obfuscated source, hidden external destination, declared listener/credential,
source modification, malicious README instructions, conflicting evidence, and deterministic
reclassification under the same profile. Manual validation should show file-level citations and
the exact reason for classification; it must not execute source. **Done** when an operator can
inspect the durable facts/reasons and M20-D can consume them without rereading untrusted prose.

**OPEN DECISION (M20-C ADR likely):** inspector techniques and the explicit confidence/evidence
schema; whether LLM-assisted inspection is enabled for the first automatic fixture. The safety
gate must function when the LLM is absent or produces invalid output.
