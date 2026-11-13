# Original M20 track — controlled development pause and archival handoff

**Recorded: 2026-11-13. Original track deliberately PAUSED, not abandoned.**
This is an archival checkpoint, not a new implementation or acceptance result.
It neither authorizes resumption nor begins an alternative development track.

## Authoritative status at this checkpoint

| Work | Status |
| --- | --- |
| M0–M19 foundation | Existing accepted implementation retained |
| M20-A / A2 | Research/candidate foundation and live provider implemented; retained unchanged |
| M20-B | CLOSED; real immutable acquisition acceptance retained |
| M20-C | CLOSED; retained-source inspection/classification acceptance retained |
| M20-D | CLOSED; D1–D8 acceptance retained |
| M20-E1–E6 | CLOSED; accepted implementation and evidence retained |
| M20-E7 | **INCOMPLETE — DEVELOPMENT PAUSED** |
| M20-E8–E9 | NOT STARTED |
| M20-E overall | OPEN |
| M20-F | NOT STARTED |

PAUSED does not mean COMPLETED, failed technical acceptance, or permanently
CANCELLED. Earlier documents saying E7–E9 were not started describe their historical
checkpoint; the current distinction is that E7 was attempted but remains incomplete,
while E8–E9 have not started. No E7 acceptance is claimed.

## Project and original M20 objective

BoberAgent is a capability-driven Core orchestration platform for authorized
penetration tests, labs and CTFs. Capabilities provide reusable abilities; Workflows
sequence them; Core owns Mission meaning, scope, policy and canonical World State.
The Execution Node owns execution mechanics. An advisory LLM is not an authority.

The original M20 objective was a generic unknown-PoC pipeline: bounded research
and candidate identity → immutable acquisition/provenance → source inspection and
conditional classification → immutable plan/validation/policy → prepared runtime →
separately authorized controlled execution → interpretation/adaptation/HITL. This
**overall objective is not complete**. Acquiring source, classifying it, approving
policy or preparing a runtime does not authorize executing that source.

## Accepted architecture and safety boundaries

- Core owns durable preparation attempts, current D applicability, permit issuance,
  canonical Artifact content/catalog and final preparation evidence reconciliation.
- Core selects the explicit provider using its existing Capability Registry/Router.
  Contracts and the neutral transport carry typed data. Real MCP Streamable HTTP
  is a carrier, not the domain model; Core must not import Node implementation code.
- The Kali Execution Node owns authenticated permit admission, exact Core→Node
  source Artifact Import, bounded source materialization, prepared Python Resource
  ownership/confinement and local runtime persistence. Capabilities use the SDK.
- E5 produced the prepared Resource and intermediate evidence. E6 owns the final
  `RuntimePreparationManifest`, ordinary terminal CapabilityResult/receipt,
  Artifact synchronization reconciliation and Core preparation completion.
- Historical completion is not current Resource availability. Permit expiry, changed
  D/policy/provider/source/runtime context or a new Node boot requires the defined
  current checks; retained bytes and old verification never renew authority.
- `PREPARED != EXECUTION_READY != EXECUTION_AUTHORIZED`.
  Production `ProcessService.execute_plan()` **remains denied**. M20-F and its
  separate execution authorization have not been implemented.
- Preserve immutable observations, Artifacts, manifests, decisions, terminal attempts
  and audit history. No acquired-source execution, source import/compilation, package
  installation, target activity, Secret grant or generic shell/delete API follows
  from this pause or the approved E7 design.

## Proven history versus planned work

M20-B's real public GitHub acceptance established immutable revision/tree validation,
bounded archive acquisition, raw/manifest Artifacts, Kali/TLS/MCP delivery, Node→Core
Artifact sync and durable Core finalization/reopen without re-fetch. M20-C retained
C1 evidence and calibrated C2@2/C3@2 inspection/classification; the retained real
CERTCC source was **UNSUPPORTED**, not safe or authorized. Historical @1 records remain.
M20-D's synthetic D7 acceptance passed; real retained-source D8 admission was
`COMPLETED / UNSUPPORTED / REJECTED_UNSUPPORTED` and created no execution plan or
downstream approval/execution records. Exact identities remain in the linked records.

E1 supplied typed preparation boundaries; E2 durable Core admission/permit identity;
E3 authenticated Node admission/routing and exact source import; E4 bounded source
materialization; E5 prepared Python Resource/confinement/current verification;
E6 ordinary terminal evidence and independent Core reconciliation. Existing Core
migration head at the accepted checkpoint is `0018_m20_e6_completion`; Node head is
`0012_python_revalidation`. No E7 migration exists at this archive checkpoint.

The accepted E5-H real Core↔Kali **v2** record includes:

| Identity | Retained value |
| --- | --- |
| Node | `node-ac6331a1-ecdb-47ef-aa9c-d44dd539b615` |
| Resource | `resource-ad6b7821-af17-439c-a706-95b1adf75499` |
| Permit | `preparation-permit-c89f2cdc72274c7b9e8d78e6d18a1137` |
| Run | `run-preparation-7a35929b35aa4ccaab136c380601b534` |
| Construction SHA-256 | `74efa984590f4da547d8f1a128a3962978db7c067e3ad53b30183b891ec1ea79` |
| Binding SHA-256 | `bb09639e824737bfa1fd835755a05ded9162b801900810d71780a3d3590a6f09` |

That operator-run acceptance proved one Resource, fresh current revalidation after
Node process restart/Core reopen, unchanged binding/construction and retained cumulative
accounting; it did not execute acquired source or authorize execution. The earlier H v1
expired and correctly failed closed; it must not be repaired, reused or rewritten as PASS.
Earlier E5 real-host acceptance and forensic failed attempts remain untouched.

E6's accepted record reports **1711 passed, 9 skipped, 1 warning** on its final code
tree, plus the recorded focused/migration/architecture and quality gates. These are
**historical E6 results**, not tests rerun for this archive and not E7 acceptance.
E6 focused synthetic acceptance is not a new real-Kali E8/E9 acceptance.

## Git checkpoint and exact interrupted state

Last accepted implementation checkpoint:

`e4651341357e9f09e681ce891e7b0a0e58b858d9`
— `M20-E6 — terminal preparation result and Core reconciliation`.

Before archival changes, `main` was at that commit, two commits ahead of its locally
recorded `origin/main`: E5-H/E5 closure `ba7d4c3`, then E6 `e465134`. No tracked file
was modified. Exactly one untracked file existed:

`packages/transport/src/boberagent_transport/preparation_maintenance.py`

It had **126 lines**, SHA-256
`cd52e3c49805a9520fc9ba013ff870bcef6a76add58a8e22a40278dd90091788`.
Its exact bytes are retained as
[archived unaccepted text](archive/e7-interrupted/preparation_maintenance.py.txt),
with [archive provenance and warnings](archive/e7-interrupted/README.md).
Equality was verified before removing the untracked active-package copy. It was not
imported, executed, repaired, reformatted or completed during archival.

The archival branch is `archive/m20-original-plan-2026-11-13`. Its documentation-only
commit descends from the accepted checkpoint; the annotated tag
`m20-original-paused-2026-11-13` identifies that archival commit. `main` and accepted
history are not rewritten. Publication is a separate explicit operator action.

## Approved E7 decisions — intent, not implemented capability

### Explicit Core-private successor attempt

Ordinary identical `admit(request)` must keep its exact-context deduplication.
A fresh retry is an **explicit** Core-owned successor after proven safe cleanup,
with a durable predecessor relationship and fresh PreparationRef, PermitRef,
reserved RunRef and eventual Resource binding. No caller-supplied retry key.
One successor per predecessor must provide durable idempotency under concurrency;
conflicting requests fail closed. Fresh current D/policy/approval/provider/profile/
source admission is mandatory. Terminal status alone is not cleanup proof.
Do not renew, reopen, rebind, overwrite the predecessor or silently dispatch a retry.

### Transport-neutral preparation maintenance

The approved boundary supports only bounded STATUS / CANCEL / CLEANUP, quarantine
and retirement of exact previously owned preparation state, including before a
Resource exists. It uses the existing authenticated Core↔Node transport and exact
PreparationRef/PermitRef/RunRef/Node correlation; ResourceRef applies only when real.
No new MCP tool or separate control plane. The original expired permit is immutable
correlation, **not fresh authority**. Node must independently establish ownership.

Durable retirement must prevent delayed mutating messages from resurrecting stopped
work. Maintenance replay is idempotent; conflicts fail closed. Cleanup must prove
empty relevant process ownership and terminal owned-state cleanup while preserving
immutable/shared evidence. Core records typed cleanup evidence separately from
predecessor history; that proof gates successor admission. Existing `RELEASE_RUNTIME`
remains exact Resource teardown, not a fake pre-Resource request.

Maintenance must not permit construction, revalidation, reuse, permit renewal,
Resource creation/rebinding, execution authorization, generic process control or
arbitrary deletion. Cancellation is not automatic Resource deletion. The incomplete
draft does not implement or establish these guarantees; identity/digest fields still
require authoritative derivation/verification before any future production use.

## What E7 still requires

Only the initial unreviewed transport draft was written; **no accepted E7 production
wiring, persistence or acceptance was added**. Required work remains:

- Neutral transport wiring over the existing carrier, durable Node retirement,
  authenticated cancellation/reconciliation and owned cleanup before Resource creation.
- Real filesystem/process-safe cleanup, production `RELEASE_RUNTIME` handling,
  generation/lease exclusion and interrupted-cleanup recovery. Existing metadata-only
  cleanup completion is not proof that constructed runtime files were removed.
- Separate durable Core cleanup evidence; explicit successor persistence/admission,
  uniqueness/concurrency/reopen tests and fresh identities after proven cleanup.
- Current availability/revalidation after E6 completion without requiring the old
  DISPATCHED/QUEUED creator state or reopening historical completion.
- Cross-component cancellation and uncertain-outcome reconciliation; replay/lost-ack
  behavior across import, staging, Resource/accounting, terminal Result, manifest
  synchronization and Core reconciliation without duplicate work or blind rebuild.
- The full E7 matrix: Core/Node restarts; conflicting/exact replay; interrupted
  construction/revalidation/publication; evidence failures; changed D/policy/provider/
  source/runtime/helper/backend; expired permits; cleanup races and interruption;
  no resurrection; and explicit successor only after independently proven cleanup.

Existing E3–E6 recovery foundations must be reused where correct, not duplicated.
No full E7 test result, acceptance matrix or closure was achieved. E8's full synthetic
D→E vertical acceptance, E9's final real Kali acceptance and M20-F remain unstarted.

## Why the operator paused this track

The operator reports repeated Codex execution interruptions by the platform's
cybersecurity safety controls while E7 recovery/reuse/cancellation/cleanup was being
developed. The successor and maintenance decisions above had already been approved.
The second interruption occurred after the initial 126-line transport module was
created; a subsequent attempt was blocked before additional code was written.
The operator's Daybreak verification process was unsuccessful, and the current
environment did not provide a reliable way to continue. The operator deliberately
suspended this track rather than repeatedly retrying blocked operations.

These are operator-reported platform workflow circumstances, not a demonstrated
implementation/test failure or an architectural rejection. No claim is made that a
particular file caused the restriction or that Daybreak would guarantee future access.
This archive does not attempt to bypass restrictions or start replacement development.

## Read before any separately authorized resumption

1. [Agent instructions](../../AGENTS.md), [project context](../00_PROJECT_CONTEXT.md),
   [system architecture](../01_SYSTEM_ARCHITECTURE.md),
   [Capability Contract](../02_CAPABILITY_CONTRACT.md), [SDK](../03_CAPABILITY_SDK.md),
   [World State](../04_WORLD_STATE_MODEL.md),
   [Workflow/reasoning](../05_WORKFLOW_AND_REASONING.md),
   [Execution Node](../07_EXECUTION_NODE.md) and [bootstrap plan](../09_BOOTSTRAP_PLAN.md).
2. [M20 pipeline](../10_M20_UNKNOWN_POC_PIPELINE.md),
   [support boundary](00_SCOPE_AND_SUPPORT_MATRIX.md),
   [B](M20B_IMPLEMENTATION.md), [C](M20C_IMPLEMENTATION.md),
   [D](M20D_IMPLEMENTATION.md) and [E implementation plan](M20E_IMPLEMENTATION.md).
3. [E authority](M20E_RUNTIME_AUTHORITY.md), [source/workspace](M20E_SOURCE_AND_WORKSPACE.md),
   [recovery](M20E_PREPARATION_RECOVERY.md), [acceptance](M20E_ACCEPTANCE.md),
   [E5 architecture](M20E5_ARCHITECTURE.md),
   [E5 Resource ownership](M20E5_RUNTIME_RESOURCE.md),
   [E5 recovery/revalidation](M20E5_RECOVERY_AND_REVALIDATION.md),
   [E5-H real acceptance](M20E5H_IMPLEMENTATION.md) and
   [E6 accepted implementation/validation](M20E6_IMPLEMENTATION.md).
4. Accepted ADRs [0018](../adr/0018-m20-e-preparation-authority-and-applicability.md),
   [0019](../adr/0019-m20-e-immutable-source-import-and-prepared-resource.md),
   [0020](../adr/0020-m20-e-trusted-python-preparation-boundary.md),
   [0021](../adr/0021-m20-e5-prepared-python-resource-and-enforcement.md) and
   [0022](../adr/0022-m20-e5-trusted-python-runtime-projection.md).

Then inspect actual Core/Node preparation services/repositories/migrations, Resource
ownership and confinement journal, ordinary Router/Run/outbox/Artifact paths, neutral
transport/MCP adapters and migration-backed E3–E6 tests. Repository state is authoritative
over stale status prose or assumed chat memory. The draft is not an installed component.

## Conditions for future resumption

- Obtain a **new explicit operator request** in an environment where the requested
  authorized work can proceed under applicable controls; do not repeatedly retry or
  circumvent a restriction. This checkpoint itself authorizes no development or execution.
- Verify branch/commit/tag, worktree and archive hash; preserve accepted history and
  distinguish the archived unreviewed draft from production. Re-audit current code and
  approved decisions before reusing any draft; do not blindly restore it into a package.
- Review any new material architecture conflict before changing semantics. New database
  state needs forward migrations; preserve all old evidence, terminal history and budgets.
- Treat all old permits as historical; check actual current validity rather than editing
  clocks/expiry. Never reuse expired authority or forensic failed runtimes. An old READY
  Resource, accepted manifest or successful host test is not current availability or a
  lease, and is never execution authorization.
- Use isolated harmless fixtures, deterministic failures and current migration/architecture/
  regression gates for future implementation. Do not infer E7 acceptance from E6 tests or
  historical real Kali evidence. Real runtime access requires separate explicit authority.
- Stop at the separately requested scope. Do not automatically begin E8/E9/M20-F, acquired
  source execution or a non-PoC development track.

## Archival validation only

This checkpoint preserves the original bytes, accepted ancestry and production files.
Validation is limited to byte/hash/line equality, documentation paths and status
consistency, documentation-only commit scope, `git diff --check` and clean final Git
state. No application tests, preparation operations, real Kali acceptance or PoCs are
run for this archive. Historical acceptance records and runtimes remain untouched.
