# M20-E/F — Attacker-side runtime preparation and controlled execution

M20-E and M20-F have distinct authority and implementation gates. **M20-E architecture is
SPECIFIED; E1–E3 are COMPLETE, including real Core↔Kali E3 acceptance,
E4–E9 have NOT STARTED, and M20-E remains OPEN.
M20-F has NOT STARTED.** Both depend on exact
immutable v2 intent and current D decisions, but E uses a preparation-only permit and F later
requires its own execution authorization. Initial E support is attacker-side, source-visible,
non-interactive, user-space, apparently standard-library-only CPython 3.12 on Kali. Other
languages and target-side or remote-Session execution are future adapter classes.

D5 now records a separate deterministic `ALLOW`, `DENY` or `REQUIRES_APPROVAL` assessment
under an explicit Core-owned Mission/target policy profile. These are append-only planning
decisions, not permission envelopes or readiness. A historical ALLOW may be stale after scope,
profile or validation changes. D6 approval remains separate; current D applicability and
preparation-profile admission precede a distinct E permit. F must define a distinct execution
authorization. See [D5 policy](M20D5_POLICY.md) and [E authority](M20E_RUNTIME_AUTHORITY.md).

## M20-E: prepare runtime

| Input | Output |
| --- | --- |
| Exact v2 intent/digest, current D decisions, distinct PreparationPermit, pinned raw/manifest Artifacts and preparation limits | Resource-owned managed Workspace, verified read-only source, isolated Python Resource/venv, immutable manifest/receipt and explicit Core reconciliation |

Core owns a durable RuntimePreparationAttempt and exact PreparationPermit; one ordinary routed
CapabilityRun invokes `runtime.prepare`. A separate authorized Core→Node Artifact Import moves
the existing retained raw ZIP and structural manifest without re-fetching. Node verifies and
materializes them under bounded rules in a Resource-owned Workspace. The Node emits a
RuntimePreparationManifest/receipt, and Core waits for normal Node→Core Artifact synchronization
before completing the attempt. Artifact Import, materialization and preparation are separate;
none is PoC execution.

The initial profile creates a fresh CPython 3.12 venv through a trusted interpreter and closed
provider operations, with no pip bootstrap/use, no external dependency installation, no source
import/compilation or entrypoint execution, and no preparation-subprocess network. Its manifest
explicitly records an empty external installed dependency set. A venv is **not** confinement.
The typed ConfinementBackend must prove no network/host sockets, bounded writable filesystem,
processes, memory, time, output and storage on the intended Kali environment; a rootless Linux
mechanism is a candidate, not an assumption. Missing enforcement fails closed. Unsupported
dependencies, target credentials or runtime prerequisites stop explicitly; no E WAITING_INPUT.

Read the [M20-E implementation sequence](M20E_IMPLEMENTATION.md),
[authority](M20E_RUNTIME_AUTHORITY.md), [source/workspace](M20E_SOURCE_AND_WORKSPACE.md),
[Python baseline](M20E_PYTHON_RUNTIME.md), [recovery/evidence](M20E_PREPARATION_RECOVERY.md)
and [acceptance](M20E_ACCEPTANCE.md). E is complete only after E1–E9 acceptance.
E1's typed boundary, E2's Core-only durable admission, and E3's authenticated dispatch
and opaque Artifact Import are complete. No source materialization or preparation process
has run. Production `execute_plan()` remains denied.

## M20-F: execute and capture evidence

| Input | Output |
| --- | --- |
| Exact v2 intent/digest, accepted preparation manifest and ready Resource, explicit single target and separate current F execution authorization | Managed Process record and `CapabilityResult` with execution status, raw stdout/stderr/output Artifacts, timing, exit/timeout/cancel state, Diagnostics and declared Effects/Resources/Sessions actually observed |

Reuse SDK `ProcessService.execute_plan`, `ExecutionContext` scope/secrets/cancellation/logger,
Node Process Manager, Artifact spool/sync, Event/Result outboxes, and normal Core Result ingestion.
The production `ManagedProcessService.execute_plan()` currently raises `PolicyDenied`; a narrow
Node plan executor and runtime adapter are required. F owns execution-authorization admission
and forged-plan enforcement tests before staging or launch. Legacy APPROVED, VALID + ALLOW,
and operator approval alone are not execution credentials. Reject legacy-only, unpermitted,
stale, forged, or out-of-scope intent even if a caller bypasses higher-level sequencing. Do not make
`run_tool` or a general-purpose shell command a replacement for this gate. Launch an explicit
executable and argument vector. Any needed secret is resolved only through a Run-scoped grant at
the final tool boundary and redacted from BoberAgent logs/normal results; tool-produced raw
evidence may still contain sensitive bytes and must be access-controlled rather than silently
edited.

Capture stdout/stderr to bounded or spillover Artifacts, exit code, timestamps, timeout and
cancellation, generated files allowed by the plan, and relevant network/session/effect evidence.
Preserve evidence before interpretation. Process exit `0` only means a process completed; it
does not prove a vulnerability. A correctly executed negative test may be `COMPLETED/NEGATIVE`;
ambiguous evidence may be `COMPLETED/UNKNOWN`; a launch/timeout/policy failure is an execution
failure. Actual target changes belong in `Effect` records, not optimistic expected-effects text.

Run identity, process identity, plan/source refs, Runtime Resource, Workspace and output Artifacts
must correlate. No blind rerun after crash: a previously running process with unprovable outcome
is recorded as interrupted/unknown under existing conservative Node recovery and requires a
separate authorized attempt. Cleanup is recorded separately from target effects; deleting a
Workspace must not delete synchronized evidence. For long-running work, the plan must define
finite time/resource limits and a cancellation path.

Tests: exact permitted intent vs legacy/forged/unpermitted intent; argv not shell concatenation; single-target scope; blocked
unexpected egress/filesystem activity (or fail-closed when enforcement unavailable); stdout/
stderr and binary output capture; zero/nonzero/timeout/cancel; secret redaction; restart ambiguity;
no duplicate process for duplicate invocation; Artifact sync and Result delivery independently.
Manual execution initially targets a controlled local/lab fixture only. **M20-F done** when a
managed plan produces durable evidence and an honest Result without direct Core-to-process calls.

## Explicit exclusions and decisions

No target-side local privilege escalation, arbitrary shell, root/admin execution, source
modification, compiler repair, listener creation by model whim, or multi-host propagation.
`ASSISTED` prerequisites such as existing listener/Session/credential must be separately bound
and authorized; absence does not trigger an unsafe fallback.

E's authority, source/Resource ownership, Python baseline and confinement properties are fixed
by [ADRs 0018–0020](../adr/0018-m20-e-preparation-authority-and-applicability.md). The
concrete rootless Kali backend must pass E9 preflight; its absence blocks E. Dependency
installation is unsupported baseline E and needs separate future review. F-specific execution
authorization, target-network enforcement and execution confinement remain M20-F decisions;
E completion cannot imply them. Existing venv and process management alone do not satisfy E
or F confinement.
