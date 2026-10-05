# M20-E5 — Prepared Python runtime architecture

**Status: E5-A–C COMPLETE/CLOSED; E5-D IMPLEMENTED OFFLINE / REAL ACCEPTANCE REQUIRED; E5-E–H NOT STARTED.** E1–E3 COMPLETE,
E4 COMPLETE/CLOSED with real Kali acceptance; E6–E9 NOT STARTED; M20-E OPEN;
M20-F NOT STARTED. This package specifies future implementation, not a permission,
host capability attestation, or claim that a usable Python runtime exists today.

Read this with [ADR 0018](../adr/0018-m20-e-preparation-authority-and-applicability.md),
[ADR 0019](../adr/0019-m20-e-immutable-source-import-and-prepared-resource.md),
[ADR 0020](../adr/0020-m20-e-trusted-python-preparation-boundary.md), and
[ADR 0021](../adr/0021-m20-e5-prepared-python-resource-and-enforcement.md).
The requested filename `0019-m20-e-immutable-source-delivery-and-resource-identity.md`
does not exist: ADR 0019 above is the authoritative document. There is no
`M20E_EF_BOUNDARY.md`; the accepted boundary is
[05_RUNTIME_PREPARATION_AND_EXECUTION.md](05_RUNTIME_PREPARATION_AND_EXECUTION.md).

## Product and authority

An **E5 prepared Python runtime** is a Node-owned `ResourceRef` of type
`python_runtime`, with a fresh, dependency-empty CPython 3.12 environment, an immutable
binding to the admitted E4 source and preparation, and immutable evidence that closed
trusted construction/verification ran under every E1-required preparation control.
Its current availability must also be valid. It has not imported, compiled or executed
acquired source. It is not a Session, an ExecutionPlan, or execution authorization.

`READY` on this Resource means **prepared for the E profile**, not safe source, proven
dependency completeness, or permission to use its interpreter to launch arbitrary code.
A directory alone is not a Resource success. A Resource is reserved durably before
construction and becomes READY only after verified durable publication. No provisional
"PREPARED except for limits" state is permitted.

| Milestone | Owns | Does not own |
| --- | --- | --- |
| E4, already closed | Exact immutable source publication and its existing receipt | Python Resource or general subprocess confinement |
| E5 | Resource construction, full preparation enforcement, runtime evidence, local revalidation/cleanup foundations | Terminal preparation Result/Core completion or acquired-code launch |
| E6, not started | Final `RuntimePreparationManifest`, normal receipt/Result, Artifact sync and Core reconciliation | Execution authorization |
| E7, not started | Full preparation recovery/reuse/cleanup acceptance across components | Acquired-code launch |
| E8/E9, not started | Complete synthetic/real E acceptance | Execution |
| M20-F, not started | Separate current execution authorization, execution gate, controlled launch/evidence | Inferring authority from an E Resource |

`PREPARED != EXECUTION_READY != EXECUTION_AUTHORIZED`. E5–E7 do not introduce an
`EXECUTION_READY` boolean. In F, readiness will be a fresh, operation-specific projection
of current Resource integrity, available enforcement, target and plan compatibility;
authorization remains a separate Core decision. F must re-prove its own launch controls.
Production `ProcessService.execute_plan()` remains denied throughout E.

## Current repository audit

| Existing component | Reuse / exact gap |
| --- | --- |
| Contracts `runtime_preparation.py` | Spec, permit, budgets, all twelve confinement features and final manifest already exist. PREPARED requires every feature and usage within budget. Do not relax this validator. |
| E2 Core preparation/applicability | Already owns current D validation/policy/approval and fifteen-minute issued permit; do not create a Node policy engine. |
| E3 dispatch/import | Existing Router, ordinary admitted `runtime.prepare` Run, authenticated neutral transport, exact imports; no second preparation Run. |
| E4 materializer/service | Revalidate exact PUBLISHED tree; preserve accepted usrmerge handling and immutable receipt. Do not rerun extraction to construct Python. |
| Node `RuntimeResourceRow` / `ResourceRuntimeState` | Real reusable Resource identity/lifecycle already exist; add provider detail, not a parallel Resource store. |
| Node `RuntimeSessionRow` | No use in E5. A venv is not an interactive Session. |
| SDK `RuntimePreparationService` | Final `prepare_runtime` returns the existing receipt. E5 internal provider evidence is not that final receipt; completion wiring is E6. |
| Tool Registry | Configured backend-tool selection; E5-D uses explicit operator distribution/library roots and full pins. Availability/PATH/version probes are not confined interpreter provenance proof. |
| `ManagedProcessService` | Generic argv execution, direct-child cancellation and output spillover are insufficient for E5 hard limits/descendants. `execute_plan` denies today. |
| E4 `ConfinementBackend.preflight()` | Proves only four E4 features. Its tmpfs, timeout and process-group probe do not prove full runtime limits. Keep that proof's meaning unchanged. |
| Workspace manager | Logical ownership/path confinement, not storage quota. E5 needs Resource ownership and real enforcement. |
| Node recovery | E3 admitted QUEUED Runs survive; active process records conservatively become LOST. No prepared-runtime verifier or cgroup reconciliation exists yet. |

Audited paths are under `packages/contracts/src/boberagent_contracts/`,
`packages/sdk/src/boberagent_sdk/services/preparation.py`, and
`packages/execution-node/src/boberagent_execution_node/{preparation,processes,tools,workspace,persistence,services}`.
This is an implementation gap inventory, not permission to rewrite completed E1–E4.

## Focused normative specifications

- [Resource and persistence](M20E5_RUNTIME_RESOURCE.md): identity, state, evidence, protocol.
- [Python provider](M20E5_PYTHON_PROVIDER.md): closed operations, provenance, venv and filesystem.
- [Limits/backend](M20E5_RUNTIME_LIMITS.md): mandatory controls and fail-closed alternatives.
- [Recovery/revalidation](M20E5_RECOVERY_AND_REVALIDATION.md): authority expiry and current validity.
- [Acceptance and slices](M20E5_ACCEPTANCE.md): safe Kali preflight, test oracles and implementation order.

Initial identifiers specified here are `python_runtime`, provider `python-stdlib@1`, and
backend profile `m20-e5-linux-bwrap-cgroup@1`. These are not additions to the current
registry. Retain the E1 preparation profile `m20-e-python-stdlib-kali@1`; new backend
mechanism detail is not a widening of that profile's permitted actions.

E5-A implements immutable Contracts and unwired neutral messages. E5-B adds Node-only
durable Resource reservations, exclusive ownership, budget accounting and metadata recovery.
The runtime remains UNAVAILABLE: a reserved Resource is not a constructed runtime. There is
no Python provider operation, interpreter probe, venv, E5 dispatch or execution authorization.
See [typed boundary](M20E5_RUNTIME_RESOURCE.md#e5-a-implemented-boundary) and
[durable ownership](M20E5_RUNTIME_RESOURCE.md#e5-b-implemented-durable-ownership).

## Decisions and alternatives

| Question | Options considered | Decision / why | Security consequence | Implementation consequence |
| --- | --- | --- | --- | --- |
| Venv or base Python only? | No venv; shared venv; fresh venv | Fresh venv, as ADR 0020 requires | No shared package state; not a security sandbox by itself | Closed creation without pip, activation or site packages |
| When is Resource real? | E5; defer to E6 | Reserve in E5 before writes | Failed construction remains attributable | Existing Resource row plus provider binding |
| Resource identity? | Content-derived; deterministic ref; generated bound ref | Generated ResourceRef, unique preparation/permit binding | Content equality never grants sharing/authority | Atomic reserve/reuse and immutable binding digest |
| Cgroup required? | RLIMIT only; delegated cgroup v2; privileged container | Delegated cgroup v2 for this backend | Missing delegation denies positive E5 | Operator supplies delegation, Node never sudo/configures host |
| Memory? | Advisory; per-process RLIMIT; aggregate cgroup | `memory.max`, zero swap, fail-stop on OOM | No false PREPARED with unenforced memory | Mandatory live proof before constructing |
| Process count? | UID-wide limit; namespace; `pids.max` | Per-attempt cgroup pids cap | Descendants/threads count; no root/UID exception substitute | Attach before launching wrapper, prove denial |
| Storage? | Directory accounting; quota/image; capped tmpfs | Sized/inode-bounded scratch, bounded trusted durable publisher | No general writable host bind; accounting not mislabeled quota | Stable namespace venv path, bounded export and verification |
| Descendants? | Process group; bwrap alone; cgroup plus supervised namespace | Cgroup kill + PID namespace + death-aware supervisor | No detached orphan on cancellation/Node death | Empty-group proof, durable recovery identity |
| Readiness? | E5 or E6 execution-ready; separate F projection | E5 only prepared, E6 accepts evidence | E never authorizes launch | Keep execute_plan denied |
| Permit expiry? | Auto-renew; retain as reusable; historical only | Retain history/bytes, deny new preparation/reuse | Old files never substitute for current authority | No renewal/rebuild hidden in revalidation |
| Manifest owner? | E5 final manifest; E5 evidence then E6 final | E5 evidence composed by E6 | No premature Core completion | Existing Artifact flow and receipt retained |
| Confinement interface? | Widen E4 proof; separate versioned runtime interface | New Node `RuntimeConfinementBackend` beside E4 probe | Four-feature proof cannot satisfy twelve-feature gate | Share validated low-level topology code only |
| Transport? | Direct shell; new Run; typed same-Run pump | Closed prepare/status/revalidate operations under E3 authority | No argv/path/process API | Neutral composition, no Core/Node cross-import |

## Remaining deployment facts, not permissive defaults

E5-C implements the selected backend's closed trusted probes, independent supervisor/guardian
and Node journal. See [E5-C implementation](M20E5C_IMPLEMENTATION.md). Portable wiring tests
are not active enforcement proof. Operator real acceptance has now closed E5-C (thirteen
probes; retained digest in its implementation record). C itself added no interpreter,
environment, E5 transport wiring or READY transition.

No E5 architecture choice remains delegated to an implementation shortcut. Supplied Kali
reconnaissance confirms namespace availability and delegated cgroup control-file writes,
not active enforcement. System CPython 3.12 is absent; 3.13.7 is not an approved fallback.
An explicit preprovisioned uv-managed CPython 3.12 distribution is approved for E5-D;
its real provenance acceptance is still required. Trusted
interpreter layout remains an **unverified real-host prerequisite**;
see [acceptance](M20E5_ACCEPTANCE.md#operator-supplied-reconnaissance-e5-a). E4's CPython probe
may use another host version; it is not E5 interpreter provenance. Do not install Python,
change systemd configuration, grant root or weaken a limit to make acceptance pass.
If the approved backend cannot meet this package, report the failed prerequisite and stop
positive acceptance; a different backend needs an explicit architecture revision.

E5-D implements bounded base inventory, a versioned non-GUI executable projection
and fixed confined identity over exactly that projection, with
immutable Resource-bound PROVENANCE_VERIFIED evidence. It never constructs an environment
or makes READY; the approved uv-source refinement and trust transition are recorded in
ADRs 0021–0022 and [E5-D implementation](M20E5D_IMPLEMENTATION.md). E5-E must instantiate
the same certified projection, never re-expose excluded optional Tcl/Tk or package-manager
bytes (site-packages, ensurepip/wheels and dependent launchers). General
environment construction remains unimplemented and real D acceptance remains required.
