# M20-H — Vertical smoke and acceptance

## Goal and dependency

Prove the **implemented** M20-A through M20-G interfaces together without a hidden direct
execution path. Begin with a harmless controlled fixture repository. Only after that passes and
policy/runtime isolation is enforceable should a separate, operator-authorized real unknown-PoC
lab smoke occur. This document chooses **no** real repository, CVE, target, provider, or command.

## Phase contract, reuse, and exclusions

Input is the implemented, versioned M20-A–G contracts plus an explicit controlled Mission,
target, fixture source, and policy profile. Output is a reproducible acceptance record linking
candidate, acquired Artifact/hash, inspection/classification, validated plan, Run/Attempt,
execution evidence, interpretation, and safe-stop decisions. Reuse existing test-only synthetic
capability patterns, Core/Node databases, Artifact synchronization, Router, in-memory transport,
and optional manual MCP composition. New work is a small fixture repository and focused
integration/architecture tests **during implementation**, not during this planning task.
This phase adds no production runtime or alternate dispatch route. Its non-goals are broad
vulnerability discovery, real-target automation, provider selection by the Reasoner, or making
every PoC class pass. A failed prerequisite is an explicit test result, not a skipped safety gate.

## Test boundaries

| Test tier | Input and expected result |
| --- | --- |
| Unit/contract | Typed hypothesis/candidate/inspection/plan/decision serialization, validation, provenance, classification and failure semantics |
| Component integration | Pinned acquisition, Artifact sync, static inspection, policy gate, Node runtime preparation, managed evidence capture, Core result interpretation; restart and duplicate-delivery cases |
| Controlled vertical fixture | Source-visible Python fixture; one explicit local/lab target; no authentication, listener, privilege, source modification or external destination; deterministic positive/negative/unknown indicators |
| Real manual acceptance | Previously unknown public PoC repository for **one** bounded hypothesis, pinned revision, explicit authorized lab target, complete inspection/classification/validation, isolated attacker-side preparation, controlled execution and evidence-backed interpretation |

The fixture must cross normal Core/Router/neutral transport/Node/SDK/Artifact/Result boundaries.
It may use existing in-memory transport for automated tests and existing MCP for an optional
manual cross-machine test. Do not implement a private harness that invokes the PoC entrypoint
directly from Core. After reopening Core and Node state, the source hash, candidate, inspection,
plan/approval, CapabilityRun, Artifacts, and interpretation must remain correlated. Duplicate
submission/acknowledgement must not repeat a side-effecting run. The initial fixture should prove
one `COMPLETED/SUCCESS` (only with corroboration), one `COMPLETED/NEGATIVE`, one honest
`UNKNOWN`, and execution failure without conflating these states.

For the final real smoke, an operator explicitly selects the bounded vulnerability hypothesis,
Mission target/scope, public repository and pinned revision **after** implementation and review.
It runs only in an authorized, disposable controlled lab. Record the chosen source/revision,
target authorization, policy decision, runtime controls, logs, Artifact hashes, expected
indicators, and cleanup before execution. A public repository being "unknown" means the
platform had no hard-coded adapter for it; it does not relax source inspection, scope, policy, or
result evidence. If classification is `ASSISTED` or `UNSUPPORTED`, the correct test result is a
documented safe stop, not pressure to execute it anyway.

## Negative acceptance cases

| Case | Required stop boundary |
| --- | --- |
| Binary-only or obfuscated repository | M20-C classification; no runtime preparation |
| Privileged/root/driver/kernel PoC | M20-C/D unsupported or policy denial; no launch |
| Source modification required | M20-C classification; no silent edit |
| Unexpected external destination | M20-C/D or Node launch enforcement; no out-of-envelope network action |
| Out-of-scope target or changed Mission scope | M20-A/D and Node revalidation; no dispatch/launch |
| Malformed/ambiguous entrypoint | M20-C/D; require explicit assistance or reject |
| Mutable source changed after inspection | M20-B/D/E hash/revision mismatch; re-acquire and reinspect |
| README prompt injection or install command | M20-C/E treats as data; no model or runtime instruction |
| Missing policy/isolation enforcement | M20-D/E fail closed; no automatic class |
| Lost result acknowledgement or Node restart mid-run | Existing durable outbox/recovery semantics; no blind rerun |

## Security, evidence, and definition of done

Automated tests use fixtures/controlled services only; they never scan arbitrary public or LAN
targets or download a live PoC. Artifacts retain exact source and raw output; secret-bearing
evidence follows Artifact access controls and is not copied to ordinary Result/Knowledge.
No global Knowledge promotion happens automatically. A model cannot issue tools, alter scope,
rewrite source or approve its own plan. Every stage has a typed error/stop and provenance link.

M20 is done only when the controlled fixture passes with policy and isolation actually enforced,
negative cases stop safely, crash/reconnect/idempotency behavior is demonstrated, and the manual
real-unknown-repository lab scenario traverses the same path without special-case code. A
completed process without trustworthy target evidence is not sufficient acceptance. If the
environment cannot enforce the automatic profile, report M20 incomplete rather than weakening
the test.

**OPEN DECISION (before real smoke):** which authorized lab hypothesis/repository to select and
which reproducible environment proves network/filesystem confinement. Do not select them during
this documentation-only task.
