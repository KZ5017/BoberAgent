# M20-E5-C — Full preparation confinement

**CLOSED on operator-supplied real thirteen-probe Kali acceptance.** E5-A/B are COMPLETE.
E5-D is CLOSED on operator real acceptance; E5-E is implemented offline, real construction
acceptance required; E5-F–H, E6–E9 and M20-F remain
NOT STARTED. Runtime remains UNAVAILABLE / NOT READY. Historical first-run failure and
offline correction below remain retained, not rewritten as successful first acceptance.

The accepted E5-C rerun reported `profile=m20-e5-linux-bwrap-cgroup@1`, `probe_count=13`,
`result=PASS`, `runtime=UNAVAILABLE`, `ready=false`, evidence SHA-256
`3f01339cf9c473004d1b038fa3b6afe9427897d06ec096f354450b4257ce08b8`.
E5-D extends only a separate fixed identity operation; its rebuilt helper must be repinned
and fresh controls rerun before real D acceptance. It does not invalidate retained C history.

## Boundary and trusted deployment

Node `preparation.runtime_confinement.RuntimeConfinementBackend` is separate from E4's
four-feature proof. Its async operations are `check`, `run_closed`, `stop_owned`,
`reconcile_owned`; no caller argv, source path, Python text, mount/cgroup path or ExecutionPlan
is accepted by an operation. `ClosedProbe` has thirteen fixed operations: isolation, pids,
memory, bytes, inodes, output, deadline, descendants, setsid, double_fork, cancel,
requester_death and supervisor_death. These are prerequisites, not Python provider operations.
No SDK/Core/MCP preparation-runtime endpoint is added.

Profile is `m20-e5-linux-bwrap-cgroup@1`. The reviewed native helper
`preparation/native/e5_confinement.c` is explicitly built/provisioned by the operator before
preparation. Production never invokes a compiler or installs tools. Tool Registry supplies
explicit absolute helper/bubblewrap paths, pinned by SHA-256. The helper must be static
x86_64 ELF, with no external loader. Ownership, writable modes, symlink topology and pins are
checked. A malicious same-UID operator/root compromise is outside this local trust model.
Node composition keeps these two reserved tools in a separate private Tool Registry;
they are not exposed through SDK `ProcessService.run_tool` or capability dependencies.
Python is only the existing Node control plane; no Python executable is inspected or invoked.

The manual deployment requires an explicitly installed regular executable (e.g.
`install -m 0755`), with no group/world write or setuid/setgid bits. Every directory in its parent
chain must be non-group/world-writable and non-symlink; a sticky writable ancestor is not
accepted by the manual harness's stricter installation preflight. Use `install -d -m 0755`
for the selected runtime/tools directories; existing higher ancestors must already be trusted.
Compile into a private temporary directory and install the completed binary explicitly; never
rely on operator umask or automatically repair host ancestor permissions. The read-only
harness preflight runs before Node initialization and emits only CONFINEMENT_UNAVAILABLE
with a typed `helper_file_mode` or `helper_parent_trust` stage. `_trusted_tool()` remains
unchanged, authoritative and fail-closed for its existing checks, including hash/ELF/ownership.
See the [operator installation commands](../../scripts/manual-smoke/README.md#m20-e5-c-confinement-only-kali-preflight).

## Mechanisms and closed active probes

The operator explicitly supplies an owned, delegated cgroup-v2 domain parent. Node validates
mount type, ownership, empty direct task set, memory/pids enabled for children, writable
child controls and compatible ancestor ceilings/headroom. It never guesses the parent,
enables controllers, changes host configuration or uses sudo. Each operation has its own
generated group (stable Node identity + operation identity), configured/read back before any payload: pids.max=8, memory.max=64MiB,
memory.swap.max=0, memory.oom.group=1. The blocked trusted launcher is attached and membership
verified before releasing its pipe barrier. Parent-death registration includes a race check.

The external supervisor owns concurrent bounded stdout/stderr draining, a combined 4KiB
cap and a finite monotonic deadline. Supervisor and a separate EOF/deadline guardian stay
outside the payload group. Requester death closes liveness; supervisor death closes the
guardian pipe. Both paths kill the exact group, including during wrapper setup. A private
PID namespace/init and bubblewrap parent-death behavior supplement that ownership model.
The trusted requester-death fixture actually kills its synthetic requester process; the
supervisor-death fixture kills the supervisor only after descendant-start output. They do
not kill the real Node. Cancellation uses the same liveness pipe and also accepts the SDK
cooperative CancellationService. Every positive probe requires populated=0 after teardown.
No persisted PID is used to kill on restart. A colliding pre-existing group is refused,
never killed merely because creation failed. Cancellation/requester-death probes use an
explicit fixture/supervisor readiness handshake, not an assumed wrapper process count.

### Requester-death reporting correction

The first operator run passed the eleven probes from isolation through cancellation, then
failed requester_death: only `ATTACHED` reached the backend. Delegation and trusted helper
prerequisites were verified; this was a report-path defect, not an inferred host failure.
The independent forked supervisor already outlived the deliberately SIGKILLed requester,
but wrote final JSON through buffered stdio before `_exit(0)`, which does not flush it.
The offline native regression reproduced that exact empty-report ValidationError.

The same supervisor now explicitly checks `fflush(stdout)` after its bounded final report;
no broker, new authority, or new execution interface is introduced. Requester PASS requires
the direct requester's actual `-SIGKILL` wait status **and** independently reported OWNER_LOST,
the fixture's child/grandchild readiness marker, expected counters, bounded duration/output,
and both reported and freshly read exact-group `populated=0`. SIGKILL alone is never PASS.
Node-private evidence retains optional `requester_exit_code`, distinct from payload exit;
old immutable JSON records remain readable. Supervisor-death additionally requires the
flushed closed `SUPERVISOR_DEATH_READY` marker before intentional death, empty-group proof,
and expected counters/peak. An unexpected supervisor death during requester testing fails.

Empty, ATTACHED-only, truncated, malformed/schema-invalid or over-limit reports map to
existing typed CONFINEMENT_UNAVAILABLE / DESCENDANT_CONTAINMENT_UNAVAILABLE for lifecycle
probes, suppressing raw Pydantic input/traceback content. Diagnostics use only closed
`probe`, reason and `stage=report_or_cleanup` (or `probe` for a negative valid proof).
The harness prints these fields without raw stderr/environment. Failed incomplete work
remains INTERRUPTED; immutable prior evidence is not rewritten. No migration is needed.

Offline tests exercise real native reporting and finite child/grandchild cleanup with
explicitly simulated kernel files, plus death before readiness, unexpected supervisor death,
intentional supervisor death, malformed reports and all-thirteen check orchestration.
They are wiring regressions, **not real kernel enforcement acceptance**. Rebuild and repin
the helper, then rerun the entire existing Kali harness; all thirteen must pass.

The static fixture binds only the trusted helper and a managed ten-byte synthetic read-only
source. E4 usrmerge topology checks are retained but no host `/usr` content, root, home, run,
Node DB or import store is mounted. Acquired source is never accessed. Three explicitly
size/inode-bounded tmpfs mounts provide `/work/venv` (1MiB/32 inodes), `/work/tmp` and
`/work/home` (4KiB/8 inodes each). These are empty probe scratch mounts, **not a venv**.
The fixed mount helper verifies statvfs ceilings, makes the outer root read-only, drops
capabilities and installs an architecture-checked seccomp filter denying remount, new namespace,
control syscalls and arbitrary exec. `/dev/shm` and all writable host backing are absent.

The mount helper must retain namespace-local SYS_ADMIN until fixed setup completes.
Bubblewrap's `--disable-userns` creates a nested user namespace which cannot administer the
already-created parent-owned mount namespace; it is therefore not combined with this helper.
Instead the fixed post-setup seccomp filter permanently denies unshare/setns/namespace clone,
and negative probes verify this before any positive claim. This implements the accepted
fixed mount-setup-helper option, not a weaker escape fallback. No host namespace permission
is granted. [Bubblewrap implementation](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.0/bubblewrap.c).

A clean network namespace is tested only against a controlled host-loopback listener. A
deliberately seeded inherited socket is removed by close_range before bubblewrap; the fixture
checks descriptors. Host container/DBus/agent/control filesystem visibility is absent.
Environment is fixed; no bearer, proxy, Python environment or Secret grant is inherited.
The pids fixture attempts at most sixteen children; the memory fixture touches at most
96MiB under a 64MiB cap. Byte/inode fixtures are bounded to 2MiB/64 tiny files and expect
ENOSPC. Output, deadline, normal child/grandchild, leader exit, setsid, double fork,
cancellation and both death directions require exact-group empty proof. For leader-exit
fixtures, a clean wrapper exit or supervised deadline is acceptable only with the verified
descendant-start marker and final exact-group cleanup; direct-child success alone is not proof.

## Persistence, evidence and budgets

Node migration `0009_runtime_confinement`, after immutable `0008`, adds only
`runtime_confinement_operations`: logical identity, closed probe/limits, startup/kernel boot
and delegated-parent pins, timestamps, RUNNING/FINISHED/INTERRUPTED and bounded evidence.
Terminal history is immutable. E5-B Resource identity, pins, ownership, accounting and READY
prohibitions remain unchanged. No Core migration or replacement Resource store is added.

Expected OOM/pids/deadline hits can pass dedicated mechanism probes. They are not positive
PythonRuntimeEnforcement construction evidence, which correctly rejects such events.
ProbeEvidence records configured limits, attachment-before-exec, measured memory peak,
kernel events, an explicitly conservative process peak bound, bounded outputs and final
empty state. Unknown/missing counters fail closed, not a measured zero. Failed probe,
unavailable host, expected limit trigger and cleanup failure stay distinguishable.
RuntimeConfinementUnavailable maps narrow process/memory/storage/descendant/time details
to the existing E1/E5-A taxonomy. No runtime readiness/authority is implied by decoding a record.

`run_budgeted_probe` reuses an authenticated E5-B exclusive claim. It reserves before work,
requires remaining permit/lease time for work and teardown, and retains cumulative E3/E4
charges. Measured time/output are settled; other costs, including control overhead,
mechanism writes and synthetic file counts, retain identified conservative charges rather
than fictional exact measurements. Interrupted reservations are fully spent/quarantined by
E5-B. This is trusted bounded accounting, not filesystem-wide protection against unrelated
same-UID processes. Durable venv export/publication does not exist in C.

Startup reconciles only exact owned groups under the same boot/delegation pins. A changed
parent fails closed; changed host boot interrupts history without killing possibly reused
names/PIDs. There is no replay/rebuild. Without explicit recovery configuration, Node surfaces
pending work as degraded. Shutdown signals work and waits before closing the DB. Historical
probe reuse is read-only; `check` always generates fresh identities and probes.

## Validation and remaining gate

Portable tests cover closed configuration, unavailable hosts, typed report rules, accounting,
migration 0008→0009, immutable history/reopen, negative native-supervisor wiring, changed
boot/parent recovery and architecture guards. Synthetic control files/fake backends are
explicitly **not** kernel enforcement evidence. The static helper builds with
`cc -static -O2 -Wall -Wextra -Werror` using a pre-existing toolchain; C's thirteen fixtures
launch no Python. The shared helper now also contains the separately reviewed E5-D fixed
identity operation, requiring a rebuilt binary pin and fresh controls before D acceptance.

`test_runtime_confinement_linux.py` is opt-in with explicit parent, helper and binary pins.
Missing opt-in prerequisites skips honestly; an explicitly opted-in broken configuration
fails. The manual [Kali harness](../../scripts/manual-smoke/README.md#m20-e5-c-confinement-only-kali-preflight)
runs the real kernel probes and must not be run automatically by implementation agents.
No Codex/offline run closes real Kali acceptance. Reconnaissance is retained separately in
M20E5_ACCEPTANCE.md; it is not upgraded to active enforcement evidence.

No Python/venv/runtime is created; acquired source is not executed/imported/compiled.
No target/package/listener network, Session, Secret grant, execution authorization or
M20-F behavior is added. Production execute_plan() remains denied. E5 remains OPEN.
