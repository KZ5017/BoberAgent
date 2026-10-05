# ADR 0021 — E5 prepared Python Resource and mandatory enforcement

**Status:** Accepted architecture; E5-A typed boundary and E5-B durable metadata ownership COMPLETE.
E5-C CLOSED on operator real acceptance; E5-D implemented offline, real acceptance required;
E5-E–H NOT STARTED; E5 remains OPEN.
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
Registry selects backend tools; the E5-D refinement below selects the explicit interpreter
distribution and the provider verifies its trusted runtime closure.
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

## Approved E5-D refinement

The operator approved an explicitly configured, preprovisioned **uv-managed CPython 3.12
Linux x86_64 distribution** instead of requiring the absent `/usr/bin/python3.12`.
This supersedes the system-only interpreter-selection assumption in ADR 0020 and the
original provider spec, not the confinement, empty-dependency or authority requirements.
uv is only out-of-band provisioning: production does not invoke it, discover/download/install
Python, use PATH, or fall back to system Python/3.13. Explicit root/library configuration
and reviewed full-distribution/binary pins are required before candidate execution.

Root or Node-user-owned runtime material with non-group/world-writable parents is allowed;
malicious same-UID operator/root compromise is not newly covered. Inventory hashes include
stdlib/extensions/shared libraries/metadata, links, owners/modes and root binding. Self-declared
metadata/path names do not attest vendor origin. Only fixed confined `-I -S -B` identity
executes; no acquired source or environment is constructed.

The subsequently approved [ADR 0022](0022-m20-e5-trusted-python-runtime-projection.md)
refines full-tree executable exposure into a typed non-GUI runtime projection.
All base bytes remain trust-checked/inventoried, but optional structurally identified
Tkinter/Tcl/Tk material is absent from the certified identity view. Selected absolute
RPATH remains denied. New v2 manifest/projection pins are distinct from immutable v1
history; E5-E must expose exactly the same certified projection.

Existing `PythonRuntimeEvidence-v1` gains a distinct `PROVENANCE_VERIFIED` inspection verdict
with no environment. Resource lifecycle/current validity/readiness remain separate and
unchanged. Node migration 0010 adds immutable evidence attached to existing E5-B operation/
Resource ownership; it does not relax READY guards or add transport/authority. See the
[E5-D implementation](../m20/M20E5D_IMPLEMENTATION.md) for the exact supported closure,
fixed operation, replay/revalidation and operator acceptance limits.
