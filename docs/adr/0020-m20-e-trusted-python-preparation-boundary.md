# ADR 0020: M20-E trusted Python preparation and E/F boundary

**Status:** Accepted for M20-E architecture. E1 typed boundary is complete; runtime behavior has not begun.

## Decision

The initial supported preparation profile is Kali attacker-side, noninteractive, user-space
CPython 3.12, one target, current D4-compatible Python intent, and apparently standard-library-
only dependencies. The interpreter is selected through the trusted Tool Registry, its exact
version and platform/ABI are recorded, and a fresh managed venv is created without system
site-packages or pip bootstrap/use. The manifest attests `external installed dependency set =
empty`. No external package installation, download, build backend, wheel/sdist, editable/local
install, direct URL, VCS dependency, requirements execution, source import/compilation for
verification, source modification, or PoC entrypoint execution occurs in E.

Preparation process authority is a closed set: inspect the approved interpreter, create an
empty isolated environment, and verify that environment. A typed SDK/provider boundary may
expose these operations, but each provider operation constructs its own argv and fixed
environment; callers cannot supply arbitrary argv, shell strings, ExecutionPlan invocation
arguments, README commands, activation scripts, or source-derived commands. The generic
ProcessService may be used internally only under this gate. `execute_plan()` stays denied.

Preparation subprocesses require an explicit `ConfinementBackend` capability boundary. Its
required, *enforced* properties are no subprocess network or inherited sockets, no host-control
socket access, bounded writable filesystem and read-only managed source visibility, bounded
process descendants, memory, wall time, output and storage, and no arbitrary host filesystem
authority. A venv and the current ProcessService do not enforce these properties. A rootless
Linux mechanism such as bubblewrap is a preferred candidate, **not** the normative backend;
its capabilities must be proven on the intended Kali environment. Missing controls fail
closed. No root/admin or system-wide install is assumed.

Core↔Node control and authorized Artifact Import use their own transport authority.
Preparation subprocesses receive no package, target, listener or Session network authority.
Target SecretRef/CredentialRef requirements are unsupported in baseline E; no target-secret
grant or resolution occurs. Logs, manifests and ordinary Results contain no secret values.
Missing prerequisites stop; baseline E has no preparation WAITING_INPUT path. Future HITL
would be preparation-owned, never a reopened terminal PlanningAttempt and never an override
of DENY, integrity failure, missing confinement, unsupported privileged setup, unknown package
execution or unbounded filesystem effects.

M20-F is a separate execution gate. A prepared Resource and manifest are not permission to
run source. F must independently establish current plan/policy/approval applicability and
execution authorization, Resource/Node/provider/lease, source/entrypoint/runtime integrity,
target scope/network, F budgets and any separately authorized secret grants. F derives the
invocation from ExecutionPlanV2, never from README or preparation logs.

## Rejected alternatives

- Installing even pinned dependencies during the initial E baseline; package code can execute.
- Calling the venv a sandbox or relying on process timeout alone.
- Treating bubblewrap installation as proof of confinement without Kali preflight tests.
- Exposing arbitrary `run_tool`/`execute_plan` as preparation authority.
- Allowing human assistance to override policy denial or missing enforcement.

## Consequences

E5 must test the backend's actual security properties and fail closed on Kali before a
positive real-environment claim. Dependency installation needs a future reviewed/versioned
extension and separate ADR when proposed; no dependency-installation ADR is created now.
See [Python runtime profile](../m20/M20E_PYTHON_RUNTIME.md).
