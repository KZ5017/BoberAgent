# ADR 0021 — E5 prepared Python Resource and mandatory enforcement

**Status:** Accepted architecture; E5-A typed boundary and E5-B durable metadata ownership COMPLETE.
E5-C enforcement IMPLEMENTED / REAL KALI ACCEPTANCE PENDING; E5-D–H NOT STARTED; E5 remains OPEN.
Refines ADRs 0018–0020 without changing E1 authority, E4 publication, or the E/F boundary.

## Context

Real Kali E4 acceptance proved exact source publication and four isolation features. It
did not prove interpreter provenance, Python construction, pids/memory/storage enforcement
or descendant cleanup. E1's PREPARED manifest requires all twelve confinement features.
The existing generic process runner and E4 preflight cannot stand in for that proof.

## Decision

E5 creates a real `python_runtime` Resource, reserved before construction and made READY
only with immutable runtime evidence. It is a fresh dependency-empty CPython 3.12 venv
bound to one preparation/permit/Run/plan/Mission/Node and exact E4 publication. No Session,
shared venv, additional runtime identity type or execution-ready state is introduced.

The initial Node backend uses unprivileged bubblewrap namespaces, an explicitly delegated
cgroup v2 subtree for process/memory/descendant enforcement, and hard-bounded writable
scratch with a bounded trusted durable publisher. Full preparation controls must be proven
before construction; incomplete controls cannot yield READY. RLIMITs and post-write
accounting are not equivalent substitutes. No silent sudo, host reconfiguration or installer.

Runtime construction is limited to provider-owned inspect/create/verify operations. Tool
Registry selects the approved interpreter; the provider verifies its trusted runtime closure.
No acquired module, entrypoint, README command, package installer, secret or network is used.
E5 evidence is intermediate; E6 owns final manifest/Result/Core acceptance, E7 end-to-end
recovery, and F separate execution readiness/authorization/launch.

Detailed decisions, rejected alternatives, deployment gates and sub-slices are normative in
[M20E5_ARCHITECTURE](../m20/M20E5_ARCHITECTURE.md) and its five focused companion documents.

## Consequences

Some otherwise functional Kali Nodes will be unavailable for preparation until an operator
provides the required trusted interpreter and delegation. That is preferable to claiming
unenforced budgets. Existing E4 acceptance remains valid but is not upgraded to E5 proof.
Prepared bytes/history may survive authority expiry; current revalidation/reuse still needs
current authority. No production behavior, migration or execution authorization is added by
this ADR. `execute_plan()` remains denied; M20-E remains OPEN and M20-F NOT STARTED.
