# M20-E6 — terminal preparation evidence and Core reconciliation

**Status:** CLOSED / focused synthetic acceptance PASSED. M20-E remains OPEN.
E7–E9 and M20-F have NOT STARTED. E5/H acceptance and all retained real-host evidence
are unchanged. This slice uses isolated synthetic fixtures, not a new real Kali acceptance.

## Current-repository audit and reused boundaries

E1 already defined `RuntimePreparationManifest` and `RuntimePreparationReceipt`, both v1,
and the typed SDK `RuntimePreparationService`. E2/E3 retained the permit, reserved/queued
Run and routing provenance. E4 supplied exact materialization evidence. E5 supplied the
one prepared Resource, sealed binding, construction history, current revalidation evidence
and cumulative ledger, but deliberately emitted no terminal preparation Result. Ordinary
Result outboxes/ingestion and bounded Node→Core Artifact synchronization already existed.
The missing work was Run-bound SDK wiring, final evidence publication and durable Core
reconciliation; no new shared final type or transport message is necessary.

## Production path

1. `CorePreparationCompletionService.finalize()` rechecks current E2/D applicability and
   proves that the existing Node Run is still QUEUED. It first proves current E5 status
   through `CorePythonRuntimeService`, using the prior E4 projection only for correlation.
   It then obtains the exact accepted E4 receipt through the existing materialization
   replay, retaining E4's existing trusted preflight/passive source verification. No new
   E5 control/revalidation operation is issued. Missing/invalid E5 state cannot cause E4 staging. Caller-provided E4 summaries
   are not retained as authoritative. It requires READY / PUBLISHED / VALID, matching bindings,
   current boot evidence and independently consistent E4/E5 accounting.
2. Before dispatch, Core durably freezes those exact authoritative responses on the
   existing preparation attempt. A conflicting second context is not substituted.
3. The existing Router explicitly submits the same invocation/permit/Run to the selected
   provider through the existing authenticated transport. There is no new opcode, direct
   Core→Node implementation call or alternate execution path. E5 typed operations remain
   intermediate and do not invoke E6 implicitly.
4. A fresh initial invocation still only admits/queues E3. An identical queued invocation
   can finish only when the existing E5 Resource is currently valid. The endpoint supplies
   a service bound to that exact permit/Run to the normal Capability Runtime. Active or
   terminal duplicate invocations do not create another execution; uncertain/failed Runs
   are never rebuilt or retried. Generic invocation/execute-local paths still deny
   `runtime.prepare` without authenticated preparation admission.
5. The built-in, lazily loaded `runtime.prepare` implementation uses only Contracts/SDK.
   `ctx.preparation.prepare_runtime()` rechecks admitted RUNNING ownership, the current
   permit, the quiescent current Resource, passive retained-source verification, exact
   construction/revalidation binding and aggregate ledger. It performs no construction,
   control probes, revalidation, source import/compilation/execution or installation.
6. It publishes a bounded (64 KiB maximum) final manifest as an ordinary JSON Artifact.
   Metadata binds the sealed runtime binding, construction digest and runtime-evidence
   digest. The existing E5 control/publication allowance covers this fixed metadata;
   E6 does not reset or increase budgets, reserve a second Resource or run a new operation.
   Current validity is checked again after publication and before a receipt is returned.
7. The normal Capability Runtime persists COMPLETED / SUCCESS, with the existing typed
   receipt in `outcome.details.preparation_receipt` and the manifest descriptor in
   `artifacts`. Normal runtime Events and Result outboxes are used. Artifact bytes are
   never embedded in Results/Events, and the Result does not expose a generic Python
   Resource driver. Other contexts have an explicitly unavailable preparation port.
8. Existing transport delivery and M9 ingestion update the ordinary CapabilityRun/catalog.
   Existing M6 synchronization moves the manifest and referenced E5 proof Artifacts.
   `CorePreparationCompletionService.reconcile()` is explicitly pumped; it neither
   dispatches nor synchronizes bytes itself.

```python
from boberagent_core.preparation import CorePreparationCompletionService

completion = CorePreparationCompletionService(database, artifacts)
await completion.finalize(
    dispatch, preparation_ref,
    materialization=accepted_e4_projection,
    resource_ref=current_resource_ref, binding_sha256=current_binding_sha256,
)
# Existing Result delivery/ingestion and ordinary Node Artifact sync are separate pumps.
attempt = completion.reconcile(preparation_ref)
```

## Contract correction: exact source versus aggregate usage

The unchanged `runtime-preparation-manifest-v1` now expresses
`usage.file_count >= materialization.file_count`. E4's field is the **exact materialized
source file count**; E5's field includes retained construction/control/revalidation usage.
Equality was inconsistent with already accepted E5 aggregate-accounting semantics.
This is a validator correction, not a new authority, schema version, or budget relaxation.
Exact materialized-byte equality and every admitted usage ceiling remain unchanged.

The cross-field inequality is not sufficient for Core acceptance. Independently:

- `manifest.materialization.file_count` must equal the frozen authoritative E4 count;
- E4 bytes/tree/entrypoint must exactly match their accepted E4/permit evidence;
- the **entire** `manifest.usage` must equal the frozen authoritative E5 aggregate usage;
- E4 bytes/count must also agree with E5's byte equality/source-count minimum;
- the Node compares retained aggregate ledger values to its retained E5 evidence, rather
  than synthesizing either summary from the other;
- Core retrieves, rehashes and parses the ordinary synchronized E5 evidence Artifacts and
  requires their exact agreement with its retained E5 response (excluding self-references).

Conflicting authoritative evidence fails closed even if a standalone manifest validates.
Core also checks the exact spec/Mission/plan/source/provider/profile, permit digest, Run,
Node, ResourceRef, manifest ref/hash/size, binding/construction/evidence metadata,
workspace/interpreter/confinement and authority-bounded timestamps. Missing context or
success without required current accepted evidence is never inferred into existence.

## Durable state, waiting and failure

Core migration **0018_m20_e6_completion**, after `0017_m20_e3_import_progress`, adds four
nullable fields to the existing attempt: completion-context JSON, receipt JSON, final-manifest
JSON and a bounded completion error code. It preserves prior attempt/permit/import history.
No Node migration, helper repin/recompile, dependency, manifest version or new state machine
is introduced. Strict E5 nested data is decoded through its JSON boundary on reopen.

Normal Result-before-Artifact delivery retains the receipt and leaves AWAITING_ARTIFACT.
Missing/incomplete Artifact content reports `ARTIFACT_SYNC_PENDING`; failed synchronization
reports `ARTIFACT_SYNC_FAILED`. Neither marks completion or dispatches again. The existing
M6 explicit retry can later make content available. Artifact-first delivery is equally valid.
Only verified available bytes plus exact evidence reconciliation mark the existing attempt
COMPLETED and retain its immutable manifest/receipt. Receipt hashing uses the actual Artifact
bytes, not a different semantic/canonical digest.

Malformed/corrupt/mismatched evidence, wrong identity/binding, conflicting canonical Result,
or an unsuccessful terminal Result becomes FAILED / `PREPARATION_EVIDENCE_REJECTED`.
Normal inbox/Result conflict handling remains authoritative; conflicting redelivery cannot
replace canonical history. Repeated reconciliation of a terminal attempt is read-only.
CAS protects context binding and completion transitions. Reopen while waiting, lost Result
acknowledgement and exact replay retain one Run, Resource, manifest and completion.

Historical completion does not renew an expired permit, promote a restarted Resource,
or assert live availability. Later recovery/cleanup/reuse acceptance remains E7-owned;
full E vertical acceptance remains E8-owned, and real Kali E acceptance remains E9-owned.

## Acceptance and non-actions

Focused migration-backed tests exercise the real Core Router/registry, authenticated neutral
transport, Node Capability Runtime/SDK, normal Result and Artifact paths, and independent Core
reconciliation. Upstream harmless synthetic D/E fixtures provide a controlled enforcement
backend; they are not real-host confinement attestation or E8/E9 acceptance.

Coverage includes both delivery orders; lost ack/dedup/reopen; independent E4/E5 count and
byte mismatches that still satisfy the standalone Contract; wrong Run/preparation/Node/
provider/profile/permit/Resource/source/tree/binding; corrupt manifest/digest and E5 bytes;
missing authoritative context; conflicting terminal claims; sync failure/retry; and current
Resource validity disappearing before final publication. Existing valid Contract fixtures,
equal counts, greater aggregate counts, underreporting and admitted ceilings are covered.
Forward migration is verified from a populated previous head and from empty databases.

Throughout: **PREPARED != EXECUTION_READY != EXECUTION_AUTHORIZED**. No acquired-source
execution/import/compilation, pip/package install, target network/listener/Session, Secret
grant/resolution, Reasoner/Knowledge, execution authorization or M20-F handoff is added.
`ProcessService.execute_plan()` remains denied and is exercised as denied in the E6 tests.
No retained real H runtime/evidence is mutated, rerun or reinterpreted.

## Validation and closure (2026-10-20)

- Current E6 tests: **25 passed**.
- Contract/SDK/architecture tests: **249 passed**.
- Focused E2/E3/E4/E5 and Node Capability Runtime regressions: **29 passed**.
- Fresh/forward migration verification, including populated previous-head history:
  **10 passed**.
- Final exact-code-tree full suite: **1711 passed, 9 skipped, 1 warning** in 697.83s.
  Skips are existing real Bubblewrap/Chromium or explicit host-delegation/configuration
  prerequisites, not E6 cases or claimed host acceptance. The warning is the intentional
  duplicate-name ZIP rejection fixture.
- `uv lock`, locked all-package/dev sync, Ruff, formatting, strict mypy (**527 files**)
  and `git diff --check` passed. No dependency/lock or generated Contract schema changed.

The sandbox initially denied loopback sockets in two existing MCP regressions. They and the
full suite were rerun with local-test permissions; no production/Kali environment was used.
A superseded partial full-suite run was explicitly interrupted after the gate-order correction;
the count above is the complete final-code-tree rerun. Only closure documentation changed
after that full validation.

**M20-E6 CLOSED. M20-E remains OPEN. E7–E9 and M20-F NOT STARTED.**
