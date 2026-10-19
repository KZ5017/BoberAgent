# M20-E5 implementation slices and acceptance

**E5-A–D COMPLETE/CLOSED; E5-E real v7 ACCEPTED; E5-F real v9/v10 ACCEPTED;
E5-G CLOSED on operator real Kali configured-host positive acceptance (2026-10-19);
E5-H CLOSED / real Core↔Kali v2 acceptance PASSED; E5 CLOSED.**
See [H's retained v2 acceptance and expired v1 history](M20E5H_IMPLEMENTATION.md#operator-supplied-real-corekali-v2-acceptance),
reported 2026-10-20: same Resource/construction/binding across Node restart and Core reopen,
old proof did not promote current validity, fresh validation restored READY / PUBLISHED /
VALID, and cumulative accounting was retained. No source executed or execution was authorized.
M20-E remains OPEN; E6–E9 and M20-F remain NOT STARTED.
See [F acceptance](M20E5F_IMPLEMENTATION.md#operator-supplied-real-v9v10-acceptance) and
[G's real configured-host acceptance](M20E5G_IMPLEMENTATION.md#operator-supplied-real-kali-configured-host-acceptance).
At commit `e2a5855`, the positive opt-in executed: **1 passed, 5 deselected in 60.81s**;
systemd Result=success, ExecMainStatus=0. The linked record includes all four observed OOM
messages and the code-backed bounded-memory-probe interpretation, unchanged asset pins,
and separate historical development-host skips. This accepts G only; E6 still owns terminal
preparation completion. Parent: [E5 architecture](M20E5_ARCHITECTURE.md).

The operator-supplied [D acceptance](M20E5D_IMPLEMENTATION.md#operator-supplied-real-d-acceptance)
is PASS/revalidation PASS without a Resource or READY. E5-E's
[local construction procedure](../../scripts/manual-smoke/README.md#m20-e5-e-empty-environment-construction-operator-only)
requires current authenticated E3/E4 authority and sufficient remaining budgets; it does
not fabricate a permit or implement E5-F dispatch. Its final state remains
CREATING / VERIFYING / UNCHECKED, runtime UNAVAILABLE. Historical pending-D statements
below describe the earlier preflight chronology, not the current status.
The first real Kali run passed eleven probes but not the complete thirteen-probe acceptance.
An operator-only E5-C harness exists;
see [implementation and validation status](M20E5C_IMPLEMENTATION.md).
Commands are an operator preflight design, not a request to configure a host automatically.

## Established evidence and remaining host prerequisites

Retain E4's accepted reference point unchanged:

```text
Node: node-8207f75c-8905-4fc4-ab96-863e52d9d51a
Preparation: preparation-128f07e383204665be425c85da36c6f6
Run: run-preparation-5e05d913809a45e7885294c2753ec44a
Materialization: materialization:93a92832d388166dc92fd53d069fef96d6aaf615d1b57f2562de60aae8683895
Tree: 3468149cb07e1a4d3058f6a5326758b2b4fa215e53d1c93e784cb4854228a59b
PUBLISHED; 1 file; 336 bytes
```

This proves E4 publication/restart and its four isolation features, including real bwrap
0.11.0 on Kali, not an unexpired permit today. Do not reuse that expired authority for E5
or rerun retained source. Future E5 acceptance needs a fresh eligible synthetic preparation.

### Operator-supplied reconnaissance (E5-A)

Recorded without reprobes/host changes: Linux 6.12.25-amd64 / x86_64, bubblewrap 0.11.0,
unprivileged user/PID/mount namespaces, cgroup v2 with cpu/memory/pids, and systemd 257.
The dedicated transient service has Delegate=yes, memory/pids delegation and
DelegateSubgroup=supervisor. Its parent is kali-owned, domain-type, direct tasks empty,
with memory/pids enabled for children. Disposable writes to pids.max=8,
memory.max=67108864, memory.swap.max=0, memory.oom.group and cgroup.kill succeeded,
with clean initial events. These support backend viability, not effective enforcement.

The original reconnaissance did not prove active enforcement. Subsequent first-run evidence
and its successful subsequent rerun are recorded below; complete E5-C acceptance is now **CLOSED**.
`/usr/bin/python3.12` is absent.
CPython 3.13.7 is present but **NOT an approved fallback**. An explicit interpreter-profile
decision is approved for E5-D: explicit operator-preprovisioned uv CPython 3.12, not an
automatic installer or system fallback. E5-A itself selected/installed no interpreter.
The runtime remains UNAVAILABLE.

### First real E5-C acceptance and offline correction

The operator confirmed the already provisioned user transient service (Delegate=yes,
DelegateSubgroup=supervisor), kali-owned domain parent with empty direct tasks and enabled
memory/pids, and the static helper's ownership, permissions and SHA-256 pin. No new host
configuration is required by this defect fix.

Real results: isolation EXITED; pids TIMEOUT; memory EXITED; bytes EXITED; inodes EXITED;
output OUTPUT; deadline TIMEOUT; descendants EXITED; setsid EXITED; double_fork EXITED;
cancel CANCELLED — all eleven PASS. requester_death failed with an ATTACHED-only report and
raw JSON validation error. The requester's eventual `-9` was its expected deliberate death,
not containment proof. supervisor_death was not reached in that acceptance run.

The independent supervisor's final buffered JSON was discarded by `_exit(0)` in requester
mode. Offline reproduction and the narrow checked flush/report-validation correction are
recorded in [E5-C implementation](M20E5C_IMPLEMENTATION.md#requester-death-reporting-correction).
Offline simulated controls do not prove enforcement. The operator must rebuild/repin and
rerun the [complete thirteen-probe Kali harness](../../scripts/manual-smoke/README.md#m20-e5-c-confinement-only-kali-preflight).
That first-run failure remains historical. The operator subsequently passed all thirteen
probes under `m20-e5-linux-bwrap-cgroup@1`, result PASS, runtime UNAVAILABLE, ready=false,
digest `3f01339cf9c473004d1b038fa3b6afe9427897d06ec096f354450b4257ce08b8`.
E5-C/D are CLOSED; E5-E real v7 and E5-F real v9/v10 acceptance passed.
E5-G is CLOSED on operator real Kali positive acceptance (2026-10-19);
E5-H subsequently passed real Core↔Kali v2 acceptance, closing H and E5.

### Read-only host reconnaissance

Run as the intended ordinary Node user from a trusted directory. Do not source `.env`,
activate a venv, print environment values or probe source. The old unconstrained Python
reconnaissance is superseded by E5-D's non-executing inventory followed by confined identity.
Never execute a supplied candidate before static trust and reviewed pins.

```bash
id -u
uname -srmo
/usr/bin/bwrap --version
/usr/bin/bwrap --help
findmnt -no TARGET,FSTYPE,OPTIONS /sys/fs/cgroup
cat /proc/self/cgroup
cat /sys/fs/cgroup/cgroup.controllers
prlimit --pid "$$" --nproc --as --data --fsize --nofile
readlink /proc/self/ns/user /proc/self/ns/pid /proc/self/ns/mnt /proc/self/ns/net
```

These host metadata checks alone are **not E5 evidence** or permission to construct a venv.
Use the [D operator preflight](../../scripts/manual-smoke/README.md#m20-e5-d-trusted-cpython-provenance-only-kali-preflight)
for the approved distribution and fresh confinement. Failure reports unavailable;
no sysctl, install, sudo or system-Python workaround.

### Delegation inspection and disposable control-file check

Operator must identify an **explicitly delegated, empty test parent** owned by the intended
Node user, not the root hierarchy, user slice, a live Node group or another service's group.
Set `E5_CGROUP_PARENT` to that exact directory; never guess it from a PID or chmod a system
path. First inspect it:

```bash
test -n "${E5_CGROUP_PARENT:-}" || exit 1
realpath -e -- "$E5_CGROUP_PARENT"
stat -c '%U %G %a %n' -- "$E5_CGROUP_PARENT"
cat "$E5_CGROUP_PARENT/cgroup.type"
cat "$E5_CGROUP_PARENT/cgroup.controllers"
cat "$E5_CGROUP_PARENT/cgroup.subtree_control"
cat "$E5_CGROUP_PARENT/cgroup.procs"
```

Require domain type, memory/pids available **and enabled for children**, no parent tasks,
and write/delegation rights. An empty output from a metadata command is not automatically
success. Missing delegation/controller enablement stops this preflight; ask the operator to
provision it separately. Do not change the parent configuration in these instructions.

Only after that review, this disposable test verifies child creation/control writes, not
resource-limit enforcement. Run in a subshell; it removes only its new empty child:

```bash
(
  set -eu
  e5_parent=$(realpath -e -- "$E5_CGROUP_PARENT")
  case "$e5_parent" in /sys/fs/cgroup/*) ;; *) exit 1 ;; esac
  test -O "$e5_parent" && test -w "$e5_parent"
  test "$(cat "$e5_parent/cgroup.type")" = domain
  test -z "$(cat "$e5_parent/cgroup.procs")"
  e5_probe="$e5_parent/e5-preflight-$$"
  mkdir -- "$e5_probe"
  trap 'rmdir -- "$e5_probe"' EXIT
  test -w "$e5_probe/cgroup.procs"
  test -w "$e5_probe/cgroup.kill"
  printf '8\n' > "$e5_probe/pids.max"
  printf '67108864\n' > "$e5_probe/memory.max"
  printf '0\n' > "$e5_probe/memory.swap.max"
  printf '1\n' > "$e5_probe/memory.oom.group"
  cat "$e5_probe/pids.max" "$e5_probe/memory.max" "$e5_probe/memory.swap.max"
  cat "$e5_probe/pids.events" "$e5_probe/memory.events" "$e5_probe/cgroup.events"
  printf '1\n' > "$e5_probe/cgroup.kill"
)
```

No process is moved into this check group and it has no contents to kill. Never substitute
a live group into this snippet. A parent outside the documented cgroup mount needs an
explicitly reviewed equivalent path, not relaxed containment checks. Actual Node process
attachment permissions and effective enforcement remain mandatory **active** checks below.

### Mandatory active probes for E5 acceptance

The future manual-only backend preflight must provide fixed, versioned trusted fixtures;
no user Python text, PoC, argv or path parameter. Run each within a disposable owned group,
finite supervisor timeout and bounded scratch. Preflight itself has finite host-safe caps;
it must not try a fork/memory bomb if it could not first establish the controller.

| Probe | Exact check and pass criterion |
| --- | --- |
| Attach/limits | Attach blocked trusted launcher to the new group before exec; prove actual membership and effective memory/pids ceilings. No payload in parent group. |
| Pids | Small cap (e.g. eight including wrappers); at most sixteen attempted trusted child creations; expect EAGAIN/pids event, then kill/reap all. No unbounded loop. |
| Memory | Small cap (e.g. 64 MiB with zero swap); trusted child touches at most 96 MiB in chunks; expect allocation failure/OOM event and no READY. Supervisor outside group survives. |
| Tmpfs | Explicit one-MiB scratch plus inode limit; attempt at most two MiB sequential writes and a fixed inode-overflow case; observe ENOSPC and no writable alternative mount. No host-disk fill. |
| Mount policy | Enumerate actual mount flags/caps, attempt writes outside scratch and to read-only synthetic source; deny new namespace/remount escape. Test `/dev/shm`, root and removed host `/run` too. |
| Network/FD | Controlled host loopback listener only; clean namespace cannot reach it or receive seeded socket/agent FD. No public internet/DNS target. |
| Output | Trusted fixture emits a fixed amount just above a tiny configured combined cap; bounded capture and group termination, never unbounded spool. |
| Time/cancel | Fixed sleeping fixture; deadline/cooperative cancellation kill group and finish with appropriate typed reason. |
| Descendants | Child and grandchild, including setsid/double fork, remain after leader exit: supervisor kills them and proves group empty. Repeat timeout and cancellation. |
| Death/restart | Kill synthetic requesting Node process, then separately kill supervisor, while bounded descendants exist. Verify namespace/cgroup empty, no PID-only claim. Restart/reconcile durable identity and quarantine. |
| Interpreter | Within full backend, repeat exact pinned CPython/ABI/closure check; imported-module/path evidence contains only approved trusted runtime. |
| Venv verification | Only in explicit runtime-preparation mode: fresh empty environment, no pip/site contamination or source import; published same-path verification succeeds. |

Read-only reconnaissance can precede implementation. Full active backend proof is required
before E5 construction acceptance, not deferred to F. E5-C's accepted operator harness
established that evidence; H reuses the same backend/probes in its final procedure. A failed property blocks positive E5
closure, never just sets a warning or authorizes a weaker runtime.

## Future synthetic vertical and architecture guards

Use a harmless source fixture with an import/entrypoint sentinel that must never run:
eligible real synthetic D chain → E2 admission → E3 exact import → E4 PUBLISHED → E5
same-Run preparation → same Resource/evidence after restart/current revalidation.
Core is not marked COMPLETED by this E5-only vertical; E6 finalization is still absent.

Required focused coverage:

- strict request/evidence round trips, immutable binding, unknown profile/extra authority;
- same-binding concurrency/lost ack yields one Resource/build; conflicts reject;
- wrong Mission/Node/Run/permit/source/digest, changed policy and expired authority;
- wrong CPython/version/base venv, PATH/pyenv injection, writable tool closure, changing
  symlink/digest/library, pip/site/activation contamination and no dependency fallback;
- runtime source sentinel untouched, source bytes/hash unchanged, no package/target call;
- all active limit/death probes above; budget aggregation does not reset across operations;
- crash before/after publication, evidence write failure, restart/reboot, missing/modified
  runtime/source, backend drift, permit expiry, same-ref successful exact revalidation;
- exclusive cleanup vs construction/revalidation, failed cleanup, no deletion of E4 evidence;
- no Secret grants, sentinel MCP/cloud/proxy/agent values absent from child env/fds/evidence;
- generic Resource API cannot create a prepared environment from caller config;
- neutral transport serialization/replay and Core current-applicability gate remain authoritative.

Extend existing architecture tests without removing their intent: preserve E4's no-venv
rule in E4 modules; E5 provider may import only the reviewed trusted runtime infrastructure.
Forbid acquired import/compile/entrypoint, `ExecutionPlanV2.invocation` execution, README
commands, package installers/downloads, Secret resolution, target sockets/listeners/Sessions,
Reasoner/Knowledge and F launch paths. Contracts/SDK stay infrastructure-independent, Core
has no Node implementation import, transport owns no runtime provider. Test the continued
`execute_plan()` denial. AST checks alone are insufficient: sentinel files, canary secrets,
negative namespace probes and process-tree tests provide behavior evidence.

Portable tests use deterministic fakes for wiring/fail-closed paths. Linux enforcement tests
must report prerequisites honestly and skip unsupported CI hosts explicitly; mocked/omitted
controls cannot count as positive Kali acceptance. Never require real PoC execution or a
public target. Run normal repository quality gates when implementing each slice.

## Final real Kali workflow — H v2 accepted, H and E5 CLOSED

The [H manual harness](M20E5H_IMPLEMENTATION.md) and
[operator commands](../../scripts/manual-smoke/README.md#m20-e5-h--final-real-corekali-acceptance)
implement the three planned modes without new production semantics:

1. `--check-config`: explicit Node/runtime/tool/delegated-parent configuration; read-only
   inspection and opt-in bounded disposable backend probes, no Resource/venv/source run.
2. `--real-runtime-preparation`: fresh synthetic eligible E2/E3/E4 chain through existing
   Router/neutral MCP transport, explicit current permit, real E5 provider; compare exact
   source and runtime evidence. No target/package network, pip, source import or entrypoint.
3. `--restart-revalidation`: same persistent Node ID and DB; same Resource, source and environment
   digests, immutable construction evidence; append current proof within the permit window.
   Expired permit is expected denial, not grounds to change its timestamps.

Paired `--node-report` calls are passive companion evidence collection, not a fourth
preparation phase: SQLite query-only, no startup recovery, exact source/environment
verification, one Resource/constructor and full ledger comparison with Core's evidence.
The operator keeps the already delegated service/parent alive while restarting only
the Node process. Do not rerun preflight on that admitted runtime. H portable tests
use synthetic enforcement; they did not close H. The separately reported real H v2
PASS now closes H and E5. The expired v1 remains failed evidence, not acceptance.
The commands below describe explicit reproduction only, not a request to rerun accepted state.

Acceptance report includes interpreter closure/backend/kernel identities, delegation/effective
limits, all probe outcomes, ResourceRef, E4 identity, runtime inventory/evidence hashes,
remaining budgets, restart result and all negative-boundary assertions. No secret values or
host paths become cross-boundary identity. No prepared runtime may be called execution-ready.
E5-H real runtime acceptance supplements E4; E9 remains the later full E real acceptance.

## E5 implementation sequence

E5-A–D are **COMPLETE/CLOSED**; E5-E is **ACCEPTED on operator real Kali v7 evidence**;
E5-F is **ACCEPTED on operator real v9/v10 evidence**;
E5-G is **CLOSED on operator real Kali configured-host positive acceptance (2026-10-19)**;
E5-H is **CLOSED / real Core↔Kali v2 acceptance PASSED**; **E5 is CLOSED**.
M20-E remains OPEN; E6–E9 and M20-F remain NOT STARTED.
Their letter order deliberately puts enforcement
before construction. No slice may claim the next one's acceptance.

| Slice | Goal / production behavior added | Contracts and persistence | Tests / acceptance | Explicit non-goals |
| --- | --- | --- | --- | --- |
| E5-A — Typed Resource/evidence boundary (COMPLETE) | Closed operations, bindings, evidence and reasons implemented; runtime still unavailable | Shared Contracts and unwired preparation-runtime-v1 messages; no handles or DB migration | Strict round trips, schemas, immutability/digests/authority/unknown versions and architecture guards | Construction, transport dispatch wiring, F |
| E5-B — Durable ownership/lifecycle (COMPLETE) | Atomic Resource reservation, provider state, leases, budget ledger, quarantine/cleanup skeleton | Forward Node migration keyed by existing ResourceRef; retain E3/E4; no new Core table | Fresh/upgrade/reopen/concurrency/crash tests; one Resource per binding | Venv creation or readiness claim |
| E5-C — Full preparation confinement (CLOSED) | RuntimeConfinementBackend, supervisor/guardian/cgroup, capped scratch/output and trusted probes | Node migration 0009 journal; no authority expansion | Real thirteen-probe Kali PASS retained | Acquired code, weaker RLIMIT fallback, privileged host setup |
| E5-D — Interpreter provenance (CLOSED) | Explicit pinned uv CPython 3.12 closure and confined fixed inspection | Node migration 0010 immutable existing Resource-bound evidence; no READY | Operator real PASS/revalidation PASS and exact retained pins | Source imports, installs, venv construction |
| E5-E — Empty environment construction (ACCEPTED, real v7) | Closed accounted fresh venv, bounded publication and read-only same-path verification | Node migration 0011, existing ownership/ledger, immutable inventory; no new domain ID | Real construction and same-identity passive replay PASS, still UNCHECKED/unready | Runtime execution, READY promotion, dynamic source imports |
| E5-F — Evidence/revalidation + narrow pump | Seal evidence, READY/current validity, typed same-Run prepare/status/revalidate through existing Core admission/neutral adapters | E5 evidence Artifact; append verification; existing Run/preparation refs; no final manifest/result acceptance | Replay/conflict/expiry/disconnect/Node restart/drift/cleanup tests; current proof required | E6 terminal Result/Core COMPLETED, F authorization |
| E5-G — Synthetic vertical (CLOSED, real Kali 2026-10-19) | D→E2→E3→E4→E5 through configured production composition, no provider substitution | Migration-backed isolated Core/Node stores; no new schema | Opt-in Linux positive PASSED: one Resource, replay/accounting, reopen/revalidation, immutable source and non-execution assertions; historical portable results retained separately | Real target, reusable production runtime, execution authorization, full E6–E9 acceptance |
| E5-H — Real Kali acceptance (CLOSED, real v2 PASS reported 2026-10-20) | One manual harness: resource-free preflight, Core/Router/MCP preparation, restart/fresh revalidation; paired passive Node reports | No new authority/persistence/schema/provider semantics | Real Core↔Kali preflight/preparation/restart and both passive reports PASS; one Resource, same construction/binding, current validity freshly restored, accounting retained; expired v1 remains failed history | PoC entrypoint, host provisioning, execution authorization, E6 terminal completion, M20-F |

Before each implementation, read this package and existing E1–E4 code. If a platform fact
invalidates a chosen mechanism, stop positive implementation and review the smallest
alternative. Do not quietly change the support profile, weaken a feature, auto-install a
runtime or call generic process execution to make a smoke succeed.

### E5-B automated acceptance

`packages/execution-node/tests/test_python_resource_ownership.py` verifies fresh/upgrade
SQLite schema, retained E3/E4 metadata, stable ResourceRef/reopen, real threaded identical
and conflicting reservations/claims, immutable binding, exclusive generation/expiry,
all eleven E1 budget categories, settlement replay/conflict and conservative interruption
accounting. Injected transaction failures cover reservation/claim commits, BUILDING,
quarantine and cleanup transitions; completion-before-ack replay is durable. Node startup
recovery is exercised without a runtime provider or Resource workspace.

`packages/core/tests/test_python_resource_e5b_integration.py` passes through the existing
synthetic C/D→E2→E3→E4 chain, then reserves E5-B metadata locally. It creates no second Run,
no WorkspaceRow and no new files or transport operation at the E5-B boundary.
Architecture guards prohibit runtime/OS/filesystem/network/dispatch/evidence-sealing
operations. E5-B does not satisfy any live enforcement, runtime-construction or Kali
preflight/acceptance oracle above. The runtime remains UNAVAILABLE and not READY.
