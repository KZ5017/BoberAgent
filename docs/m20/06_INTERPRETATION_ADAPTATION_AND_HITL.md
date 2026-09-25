# M20-G — Interpretation, bounded adaptation, and human assistance

## Goal and dependency

Interpret M20-F execution **evidence** under the validated M20-D plan and original Mission
hypothesis. Decide whether to stop, make one explicitly permitted variant attempt, or request
human assistance. Do not equate process completion with target vulnerability. This phase depends
on durable Artifact/Result ingestion and the existing Core Workflow/Interaction boundaries.

## Typed boundary

| Input | Output |
| --- | --- |
| Plan, source/inspection provenance, `CapabilityResult`, stdout/stderr/output Artifact refs, current World State and bounded relevant Knowledge | Interpretation with cited evidence, execution/semantic classification, uncertainty and contradictions, optional next bounded action or durable assistance request |

Use existing Contract execution status and `CapabilityOutcomeCategory` (`SUCCESS`, `NEGATIVE`,
`PARTIAL`, `UNKNOWN`) for the CapabilityResult. A PoC-specific interpretation may express
`CONFIRMED`, `NOT_CONFIRMED`, `INCONCLUSIVE`, or `EXECUTION_FAILED`, but must map transparently:
confirmation requires target-specific corroborating evidence; not-confirmed after a valid check
is normally `COMPLETED/NEGATIVE`; ambiguous response is `COMPLETED/UNKNOWN` or `PARTIAL`;
process/plan failure is execution failure. Never create a `Finding` solely because stdout says
"success" or because a public PoC claims a version is vulnerable. Findings require appropriate
Core-owned interpretation and evidence provenance. Research candidates and source claims do not
become target Observations by themselves.

Deterministic parsers/checks take priority. M19 advisory Reasoner may interpret bounded raw
excerpts with explicit Artifact citations, expected-result semantics and current World State;
untrusted PoC output/README remains data, never a command or priority instruction. Record
provider/model and uncertainty when used. Invalid model output or absent provider yields an
explicit inconclusive state, not fabricated confirmation. Preserve complete raw evidence even
when normalization fails; do not promote it to global Knowledge automatically.

## Adaptation boundary

One attempt is identified by plan/source revision, target, explicit bindings, runtime and a
stable Attempt identity. Never replay the same failed state-changing attempt automatically.
M20-v1 may propose **only** documented parameter adjustment, bounded timeout adjustment,
selection among already-declared modes, or an alternate explicitly inspected entrypoint. Each
variant is a new, recorded plan/Attempt, with the same target and pinned source, fresh validation
and policy check, an explicit finite attempt budget, and a reason tied to prior evidence. There
is no open-ended self-modifying loop.

No automatic exploit-logic rewrite, arbitrary source patch, compiler-error repair, payload
redesign, target expansion, safety-check removal, or dependency refresh. Such needs stop and may
be explained to the operator. A human-supplied modified Artifact, if supported later, is a **new
source revision** requiring acquisition-style hash/provenance, inspection, plan and policy anew;
it does not mutate the previously inspected Artifact.

## Human assistance and policy

Reuse M15 durable `InteractionRequest`/response and `Checkpoint` for missing credential binding,
listener/Session prerequisite, entrypoint choice, bounded manual parameter, or a request to stop.
Use M16 refs/grants for credential/secret values; never put plaintext in prompts, Events,
checkpoints or normal logs. Reuse existing Resource/Session leases for prerequisites. A missing
policy approval is **not** an InteractionRequest: policy decisions and approvals require the
separate M20-D gate, and a denied action remains denied regardless of human input.

The accepted M15 implementation preserves Core restart while a Node waiter lives, but a Node
restart fails a waiting Run conservatively; it cannot restore a Python coroutine. M20 must not
claim otherwise. If logical PoC continuation across Node restart is required, add an explicit
checkpoint-driven re-entry design under review and test it before promising that behavior.

## Reuse, additions, non-goals, and stop conditions

Reuse M11 Workflow/Step and Attempt-oriented provenance where applicable, M15 Interaction,
M19 provider/context/validator pattern, M17/18 Knowledge, Result ingestion and World State
queries. New typed PoC interpretation and bounded variant decision records are likely needed;
do not stretch M19 `ActionProposal` into an unvalidated shell plan. Current M11 static sequential
Workflow has no dynamic branch/loop language; extend Core orchestration only if reviewed and
necessary, with stable Run identities and no duplicate dispatch on restart.

Stop on unclear evidence, contradictory indicators, unavailable prerequisite, exhausted budget,
rejected policy, changed source/target, lost Node continuation, or unsupported adaptation. An
inconclusive result is not automatically retried.

Tests: exit-zero false-positive, completed negative, partial/unknown with preserved Artifacts,
cited confirmation, malformed Reasoner output, repeated evaluation idempotency, variant budget,
same-target/source enforcement, source edit rejection, Interaction response/restart behavior,
policy denial not bypassed, and no global Knowledge promotion. Manual smoke should show the
evidence chain and one honest terminal interpretation without requiring a model to label every
output. **Done** when an operator can explain every attempted variant and why the pipeline
confirmed, did not confirm, remained inconclusive, failed, or waited.

**OPEN DECISION (M20-G ADR likely):** exact per-hypothesis attempt budget and durable dynamic
phase orchestration; whether any Node-restart-resumable PoC continuation is required in v1.
