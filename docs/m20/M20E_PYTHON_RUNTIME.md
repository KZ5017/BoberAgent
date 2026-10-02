# M20-E trusted Python preparation profile

**Status:** E1 profile typed; E4 source materializer and bubblewrap *preflight* implemented
offline, real Kali acceptance pending. E5 Python provider/venv unimplemented. See [ADR 0020](../adr/0020-m20-e-trusted-python-preparation-boundary.md).

## Initial profile and rejection rule

The initial profile is attacker-side Kali, CPython 3.12, one target, current D4-compatible
Python plan, user-space and noninteractive. Inspected requirements must appear standard-library
only; Core/Node still verify the admitted profile and dependency evidence. No target SecretRef,
CredentialRef, listener, remote Session, privileged setup, package/network dependency or source
modification is supported. Unsupported or ambiguous prerequisites fail explicitly. D4/D5 are
not broadened to make installs fit. A profile/version change requires separate review.

The trusted Tool Registry selects a CPython interpreter. Record exact version, executable
identity, platform/ABI and runtime fingerprint. Create a fresh venv without system
site-packages and without pip bootstrap/use. The successful manifest states exactly
`external installed dependency set = empty`. No pip, package download, requirements file,
wheel/sdist, build backend, local/editable install, VCS or URL dependency, or package cache.
No PoC source import, compilation-for-verification or entrypoint execution. Merely creating
an isolated venv is not evidence that source is safe.

## Closed preparation operations

The provider-facing SDK boundary supports only typed operations such as `inspect_interpreter`,
`create_empty_environment`, and `verify_environment`. The provider constructs argv itself;
no caller-supplied arbitrary argv, shell command, README line, ExecutionPlan invocation
tokens, activation script or source-derived command. An internal managed ProcessService may
execute the resulting trusted operations, but the generic `run_tool` is not the capability's
preparation authority. Environment is a fixed allowlist with Node-controlled PATH; remove
ambient PYTHONPATH, user-site and package-manager configuration. Work in a trusted managed
directory, not the source tree. No system-wide installation or root/admin.

## ConfinementBackend acceptance

The E4 backend constructs a closed trusted `python3 -I` probe under rootless bubblewrap:
new user/PID/network namespaces, no whole-root bind, read-only `/usr` and system library
binds where present, minimal `/dev`/`proc`, private `/tmp`, one explicit managed writable
directory, clean environment and closed inherited FDs. A controlled host-loopback listener
must be unreachable from the namespace. The probe has bounded time/output and is killed as
a process group on timeout. It never receives acquired-source argv or filesystem paths.
The evidence records only the E4 properties actually probed (network/FD/host-control and
arbitrary host-path isolation). It **does not** claim process-count, memory, storage quota,
descendant or managed-source runtime enforcement. Those are E5 subprocess admission gates;
E4 does no acquired-code execution and cannot claim full E1 confinement completion.

The typed backend must prove the following properties on the intended Kali Node before a
positive real-environment claim:

- preparation subprocesses have no network or inherited network/host-control sockets;
- read-only managed source visibility and bounded writable area, with no arbitrary host paths;
- bounded child/descendant count, memory, wall time, stdout/stderr and storage;
- cancellation/timeout terminate descendants; failure cannot report READY;
- unprivileged operation is possible on that environment.

A rootless Linux backend such as bubblewrap is a candidate, not the architecture. The Node
must probe actual features and run negative preflight tests (network/host socket access,
out-of-root write, descendant escape, resource limits). Binary presence alone is not proof.
If any required property cannot be enforced, the provider is unavailable and preparation
fails closed. Backend identity, version, confinement profile and verified features are
recorded in the manifest. The existing venv, workspace manager and ProcessService alone do
not enforce these properties.

Core↔Node control and authorized Artifact Import remain permitted infrastructure traffic.
Preparation subprocesses have no package, target, listener or Session network authority.
No target secret grant is issued or resolved; manifests, logs and Results exclude secret
values. The preparation profile and budgets are separate from the plan's future execution
limits (the current D4 positive slice permits zero source filesystem writes). M20-F must
re-establish its own execution gate; E never calls production `execute_plan()`.

Baseline E has no preparation WAITING_INPUT path. Unsupported prerequisites stop explicitly.
Any later preparation-owned Interaction must not reopen a terminal PlanningAttempt or override
DENY, integrity failure, missing confinement, privileged setup, unknown package execution or
unbounded filesystem effects.

Dependency installation, including authenticated registries and any build-step approval,
requires a future versioned profile and architectural review. No installation ADR is needed
for an unsupported operation.
