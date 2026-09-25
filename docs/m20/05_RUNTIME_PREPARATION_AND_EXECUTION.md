# M20-E/F — Attacker-side runtime preparation and controlled execution

M20-E and M20-F have distinct contracts even if one future capability implementation coordinates
them. Both depend on a current M20-D validated/approved plan, a verified M20-B source Artifact,
and one in-scope Mission target. Initial automatic support is attacker-side, source-visible,
non-interactive, user-space Python on the Kali Execution Node. Other languages and target-side or
remote-Session execution are representable future adapter classes, not automatic M20-v1 support.

## M20-E: prepare runtime

| Input | Output |
| --- | --- |
| Validated plan, pinned source Artifact/hash, exact dependency declarations and policy limits | Run-owned managed Workspace, staged source with verified hash, isolated Python runtime Resource/venv with recorded provenance, readiness or explicit failure |

Reuse Node Workspace manager, Artifact spool/verified Core bytes, Tool Registry/Dependency
Resolver, Resource identity and SDK abstractions. A runtime-preparation adapter is new. A venv
only separates Python packages; it does **not** confine filesystem, processes or network. Before
untrusted code runs, the Node needs a reviewed, enforceable execution isolation profile with
bounded filesystem/network destinations, privileges, process/resource limits, and cancellation.
If those controls are unavailable on the Node, M20 must remain `ASSISTED`/blocked, not silently
fall back to `run_tool("python", ...)`.

Stage source only from the pinned Artifact, with path confinement; verify hashes after extraction
and before launch. Dependencies are installed only from explicit inspected declarations under
policy, with locked versions/hashes or a documented equivalent provenance strategy. No arbitrary
README `pip install`, editable install, build hook, dependency resolver network access, or
subprocess is implicitly trusted. A dependency install that executes package code is an
execution-risk event in its own right and may need a separate gate. Never make an unknown
repository trusted by placing it in a Workspace. Record runtime/interpreter version, dependency
resolution, prepared Resource/Workspace refs and cleanup ownership.

Stop on hash drift, missing/ambiguous dependency, unapproved install network destination or
build step, failed confinement, missing runtime, resource exhaustion, or privilege request. A
partially prepared Resource is not `READY`; cleanup is recorded and safe across restart.

Tests: source hash/revision remains stable; path/symlink confinement; pinned vs mutable
dependency; setup-hook refusal; isolated workspace/venv; unavailable confinement fails closed;
Resource ownership/cleanup; restart of partially prepared state. Manual preparation uses only a
harmless controlled fixture. **M20-E done** when the ready runtime records exact source and
dependency provenance and no PoC entrypoint has yet run.

## M20-F: execute and capture evidence

| Input | Output |
| --- | --- |
| Validated/approved plan, ready runtime/Workspace, explicit single target, current authorization | Managed Process record and `CapabilityResult` with execution status, raw stdout/stderr/output Artifacts, timing, exit/timeout/cancel state, Diagnostics and declared Effects/Resources/Sessions actually observed |

Reuse SDK `ProcessService.execute_plan`, `ExecutionContext` scope/secrets/cancellation/logger,
Node Process Manager, Artifact spool/sync, Event/Result outboxes, and normal Core Result ingestion.
The production `ManagedProcessService.execute_plan()` currently raises `PolicyDenied`; a narrow
Node plan executor and runtime adapter are required. It must reject DRAFT, REJECTED, stale,
forged, or out-of-scope plans even if a caller bypasses higher-level sequencing. Do not make
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

Tests: validated vs rejected plan; argv not shell concatenation; single-target scope; blocked
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

**OPEN DECISION (M20-E/F ADR required):** concrete attacker-side confinement mechanism and
testable guarantees, dependency acquisition/lock format and install approval boundary, runtime
Resource lifecycle, and how destination constraints are enforced for both preparation and PoC
execution. Existing venv and process management alone do not satisfy these guarantees.
