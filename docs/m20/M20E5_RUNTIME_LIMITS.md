# M20-E5 enforcement and runtime confinement backend

**E5-C IMPLEMENTED / REAL KALI ENFORCEMENT ACCEPTANCE PENDING.** Parent: [E5 architecture](M20E5_ARCHITECTURE.md).
E4 acceptance remains four-feature source-materialization evidence, not full runtime proof.

## Mandatory gate

The [E5-C implementation record](M20E5C_IMPLEMENTATION.md) specifies the closed probe
vocabulary, fixed native helper, actual configured enforcement, evidence/accounting and
deployment prerequisites. This does not attest the host or authorize later construction.

Every E1 `ConfinementFeature` is mandatory **before constructing** an E5 Python environment
and before READY. A failed preflight leaves no successful Resource. Limits must apply to
trusted preparation children too; acquired-code containment in F is not proven by E5 alone.

| E1 feature | Required E5 mechanism / verification |
| --- | --- |
| NO_SUBPROCESS_NETWORK | Separate network namespace, no host routes/resolver/control channels; controlled unreachable-host tests |
| NO_INHERITED_SOCKETS | Close fds, inspect passed descriptor allowlist; seeded socket cannot be used |
| NO_HOST_CONTROL_SOCKETS | No host `/run`, D-Bus, agent/container sockets, or inherited socket; negative tests |
| NO_ARBITRARY_HOST_FILESYSTEM | Minimal approved read-only view; no root/home bind; no namespace/remount escape |
| MANAGED_SOURCE_VISIBILITY | Exact E4 pin; absent during Python operations; dedicated trusted probe proves read-only source mount |
| BOUNDED_WRITABLE_FILESYSTEM | Enumerated sized/inode-bounded scratch only; root otherwise read-only, no writable host bind |
| PROCESS_LIMIT | Dedicated cgroup v2 `pids.max` for wrapper and all descendants/threads |
| MEMORY_LIMIT | Dedicated cgroup v2 `memory.max`, `memory.swap.max=0`, group OOM handling |
| RUNTIME_LIMIT | Monotonic per-operation and aggregate deadlines, supervised kill independent of awaiting coroutine |
| OUTPUT_LIMIT | Concurrent bounded pipe drain, combined stdout/stderr cap enforced before durable writes; kill on excess |
| STORAGE_LIMIT | Hard caps on each writable sandbox filesystem plus bounded trusted publisher/evidence writes |
| DESCENDANT_CONTAINMENT | Cgroup ownership before launch, PID namespace, death-aware supervisor and verified empty-group teardown |

The limits concern this exact backend/profile/budget, not "bubblewrap installed". Report
unsupported probes explicitly. Do not substitute mock proof for actual host acceptance.

## Versioned Node boundary

Introduce **`RuntimeConfinementBackend`**, versioned profile
`m20-e5-linux-bwrap-cgroup@1`, beside the E4 `ConfinementBackend`. Reuse reviewed topology
helpers, not an ambiguous widening of E4's proof object. Its closed interface is conceptually:

- `check(requirements, budgets, trusted_tool_identity)` → mechanism-specific proof or denial;
- `run_closed(operation, verified_bindings, remaining_budget, cancellation)` → bounded outcome,
  measured usage, trusted output and containment evidence;
- `stop_owned(operation_identity)` / `reconcile_owned(...)` → empty-group or explicit failure.

`operation` is a closed inspect/create/verify/probe enum, not argv or source code from Core,
SDK callers or plans. Node provider builds the fixed command internally. The backend owns
launch, deadlines, pipes and process-tree termination; Process Manager retains ownership
records. Do not retrofit arbitrary `run_tool` or `execute_plan` into a privileged escape hatch.
Global generic ProcessService behavior is unchanged unless a separately tested narrow shared
primitive is extracted into its owner.

## Cgroup and process supervision

The initial backend **requires** an explicitly configured delegated cgroup-v2 subtree.
Node need not run as root. It must verify delegation, enabled memory/pids controllers,
writable child controls, kill support and effective ancestor ceilings; it never acquires
delegation via sudo, chmod of a system tree or persistent systemd edits. An administrator
may have to provision delegation separately. A user service/`Delegate=` request is not
proof that the required controllers were actually delegated. See
[systemd delegation](https://systemd.io/CGROUP_DELEGATION/).

Reserve an attempt-owned empty child group; configure limits before attaching any constructor.
Use a race-free launch barrier: only a small trusted launcher runs until attachment is
verified, then exec the wrapper/payload. No fork-capable payload may briefly run outside
limits. Include helper/wrapper overhead; if the permit budget cannot accommodate it, fail
without increasing the budget. Keep the Node/control supervisor outside the payload group.
Never expose writable cgroup hierarchy to the child, permit migration out, or use a threaded
cgroup for this profile. CPU rate limiting is not a new requirement; finite walltime remains
mandatory and no CPU entitlement is claimed.

`pids.max` accounts descendants/threads, while `memory.max` and swap controls constrain the
group. `cgroup.kill` kills the subtree and `cgroup.events` supplies empty/populated state.
These are the selected kernel mechanisms, not mere persisted numbers.
[Kernel cgroup-v2 reference](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

Use a private PID namespace/reaper and bwrap parent-death behavior as defense in depth.
An external Node-owned supervisor must detect Node death via pidfd/liveness channel,
enforce finite deadlines and kill the exact cgroup even if the requesting coroutine vanishes.
Tie the wrapper's parent death to that supervisor; supervisor death must also tear down
the namespace rather than leave a constructor alive. Test both directions and races.
Group-empty proof is required even after exit code 0. Retained child/grandchild causes kill
and failure, not success. `setsid`, double fork or process-group changes must not escape.
Do not use PID reuse-prone persisted PIDs to kill unrelated processes after restart.
The [Linux PID namespace model](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)
provides namespace-init death cleanup; it is not a substitute for a tested supervisor.

Evidence records operation/boot identity, wrapper/child status, cgroup limit/event/peak
counters and final empty state. No fabricated peak zero if a counter is unavailable: reject
unsupported measurement or supply an explicitly identified conservative bound within the
budget, not a claimed exact measurement. Any OOM/pids-limit event invalidates success.

## Storage, output and budget accounting

Use explicitly sized **and inode-bounded** private tmpfs for construction and temp. Every
writable mount, including root scratch or `/dev/shm` if present, must be capped or removed.
The outer namespace root is made read-only after setup. Drop capabilities and disallow new
user namespaces/remounts that could bypass caps. Backend startup must establish the configured
mount size/inode properties and prove write denial; bare `--tmpfs` is insufficient.
Bubblewrap 0.11 supports `--size` for the next tmpfs only, so each mount needs deliberate
configuration. Its presence alone does not prove inode/escape limits.
[Bubblewrap 0.11 options](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.0/bwrap.xml).

The backend must establish an explicit inode cap as well as a byte cap. If the selected
bwrap build cannot express it, a fixed trusted mount-setup helper inside the already owned
user/mount namespace sets the bounded tmpfs options before dropping capabilities; no host
mount, caller options or privileged helper. This helper is part of the backend fingerprint
and test surface. If this cannot work unprivileged on the actual host, report unavailable;
do not accept the host-RAM-derived tmpfs defaults as the permit's file budget.

Sum writable capacities against remaining `max_temporary_bytes`; reserve memory headroom
because tmpfs also consumes memory. Bound files/depth and runtime output size before publish.
Tmpfs size/inode limits are kernel filesystem enforcement, not durable storage.
[Kernel tmpfs reference](https://www.kernel.org/doc/html/latest/filesystems/tmpfs.html).
Export only the trusted verified inventory with a Node-side pre-write byte/file limiter.
No child has writable access to durable backing storage. This is sufficient for **closed E5
construction**, not a general quota for future acquired processes writing a host directory.
F must reapply hard scratch limits or review a quota-backed alternative for its writes.

`max_preparation_write_bytes` counts cumulative preparation writes, not just final tree size.
Tmpfs's peak allocation cap alone does not enforce it. Fixed provider construction must
pre-reserve a conservative bound for every trusted file/config/template write (including
replacements), copied executable and publication copy; instrument/precheck writes in the
closed builder. Output/evidence are separately bounded and also charged where written.
No unaccounted package hooks, bytecode cache writes or build subprocess. If the trusted venv
implementation cannot be bounded/accounted this way, fail; do not relabel post-write `du` as
enforcement. E4 usage and import bytes already spent remain charged; E5/revalidation/replay
cannot reset the attempt ledger. Persist reservations before writes, settle actual usage on
success, and retain conservative spent reservations after interruption.

Durable publisher accounting limits Node-owned writes; it does not promise filesystem-wide
quotas against other processes. ENOSPC/quota failure must quarantine, never READY. Atomic
publication/fsync and inventory verification prevent partial availability. Per-attempt caps
are not a platform-wide Mission quota or protection against a malicious same-UID Node admin.

Drain stdout/stderr concurrently into a combined capped buffer/spool; discard no excess
silently: terminate the group and retain bounded diagnostics on overflow. Current generic
ProcessService's file spillover threshold is not an output cap. Stream export bytes through
a separate bounded control channel, not a fake stdout Artifact. Close all channels on
cancel/timeout and verify descendants stopped before publishing anything as successful.

## Fail-closed alternatives

| Property | Primary | Alternative considered | Sufficient in v1? / closure consequence |
| --- | --- | --- | --- |
| Process count | Delegated cgroup `pids.max` | RLIMIT_NPROC or PID namespace alone | No. Shared real-UID/thread accounting and privilege exceptions are not per-attempt containment. Missing cgroup denies positive E5. |
| Memory | cgroup memory+swap caps | RLIMIT_AS/DATA, RSS sampling | No. Address/data limits are per-process and not aggregate tree memory. Missing controller denies positive E5. |
| Storage | Capped scratch + bounded trusted publisher | Plain directory accounting; quota/loop image | Accounting alone no. Pre-provisioned quota/image could be future equivalent backend, but no automatic root mount/quota setup; unavailable hard cap denies E5. |
| Descendants | Owned cgroup kill + supervised PID namespace | killpg, subreaper, pidfd alone, bwrap flag alone | No individually. No demonstrated death/restart cleanup means E5 denied. |
| Delegation supply | Operator-delegated subtree | Properly delegated systemd scope/service | Same kernel proof required, not a weaker fallback. No delegation means no positive E5 or execution readiness. |

[Linux resource-limit semantics](https://man7.org/linux/man-pages/man2/getrlimit.2.html)
explain why RLIMIT_NPROC/AS/DATA may be secondary constraints but cannot replace this
profile's aggregate guarantees. systemd is a possible delegation supplier, not a second
Resource identity or automatic privileged installer. Do not silently shrink the feature set
to close E5; a different equivalent backend requires explicit review and full acceptance.
