# M20-E5 implementation slices and acceptance

**Architecture specified; E5-A COMPLETE; E5-B–H NOT STARTED.** Parent: [E5 architecture](M20E5_ARCHITECTURE.md).
No active enforcement probe below has been run by E5-A. No new harness or CLI exists yet.
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

Active process/memory/tmpfs/inode/output/runtime/descendant and Node/supervisor-death
enforcement are **NOT YET PROVEN**; E5-C must prove them. `/usr/bin/python3.12` is absent.
CPython 3.13.7 is present but **NOT an approved fallback**. An explicit interpreter-profile
decision is required before E5-D. E5-A changes no profile and selects/installs no interpreter.
The runtime remains UNAVAILABLE.

### Read-only host reconnaissance

Run as the intended ordinary Node user, from a trusted directory, with the explicit approved
interpreter path; do not source a repository `.env`, activate a venv, print environment values,
or probe source. `/usr/bin/python3.12` below is an example configuration, not an installation
step or fallback to Kali's default Python. A missing command/path is an unavailable prerequisite.

```bash
id -u
uname -srmo
E5_PYTHON=/usr/bin/python3.12
test -f "$E5_PYTHON" && test -x "$E5_PYTHON" && test ! -L "$E5_PYTHON"
namei -l -- "$E5_PYTHON"
stat -Lc '%U %G %a %s %n' -- "$E5_PYTHON"
sha256sum -- "$E5_PYTHON"
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 "$E5_PYTHON" -I -S -B -c \
  'import sys,sysconfig,platform,venv; print(sys.implementation.name,sys.version); print(platform.machine(),sysconfig.get_config_var("SOABI")); print(sys.prefix,sys.base_prefix); print(sysconfig.get_path("stdlib")); print(venv.__file__)'
/usr/bin/bwrap --version
/usr/bin/bwrap --help
findmnt -no TARGET,FSTYPE,OPTIONS /sys/fs/cgroup
cat /proc/self/cgroup
cat /sys/fs/cgroup/cgroup.controllers
prlimit --pid "$$" --nproc --as --data --fsize --nofile
readlink /proc/self/ns/user /proc/self/ns/pid /proc/self/ns/mnt /proc/self/ns/net
```

These are trusted metadata checks only, **not E5 evidence**. The Python command imports
trusted stdlib `venv` but creates no environment. Review real ownership, 3.12 implementation,
base-prefix equality and stdlib provenance. Do not use presence of `venv` to imply that pip,
ensurepip or a package installation is permitted. Later repeat the fixed probe within the
approved backend; never replace it with arbitrary caller-supplied `-c` code in production.

An optional disposable namespace check (no mount persists outside its namespace) is:

```bash
unshare --user --map-root-user --mount --pid --fork --mount-proc \
  /usr/bin/env -i PATH=/usr/bin:/bin "$E5_PYTHON" -I -S -B -c \
  'import os; print(os.getpid()); print(os.readlink("/proc/self/ns/user")); print(os.readlink("/proc/self/ns/pid"))'
```

Failure means the backend must report unavailable; no sysctl change or sudo workaround.
This checks namespace support, not bwrap's complete filesystem/network policy.

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
before E5 construction acceptance, not deferred to F. No current script claims to implement
these new probes; E5-C/E5-H below must deliver them. A failed property blocks positive E5
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

## Future real Kali workflow

The future manual harness should separate these **planned, not currently available** modes:

1. `--check-config`: explicit Node/runtime/tool/delegated-parent configuration; read-only
   inspection and opt-in bounded disposable backend probes, no Resource/venv/source run.
2. `--real-runtime-preparation`: fresh synthetic eligible E2/E3/E4 chain through existing
   Router/neutral MCP transport, explicit current permit, real E5 provider; compare exact
   source and runtime evidence. No target/package network, pip, source import or entrypoint.
3. Restart/revalidation: same persistent Node ID and DB; same Resource, source and environment
   digests, immutable construction evidence; append current proof within the permit window.
   Expired permit is expected denial, not grounds to change its timestamps.

Acceptance report includes interpreter closure/backend/kernel identities, delegation/effective
limits, all probe outcomes, ResourceRef, E4 identity, runtime inventory/evidence hashes,
remaining budgets, restart result and all negative-boundary assertions. No secret values or
host paths become cross-boundary identity. No prepared runtime may be called execution-ready.
E5-H real runtime acceptance supplements E4; E9 remains the later full E real acceptance.

## E5 implementation sequence

All slices below are **NOT STARTED**. Their letter order deliberately puts enforcement
before construction. No slice may claim the next one's acceptance.

| Slice | Goal / production behavior added | Contracts and persistence | Tests / acceptance | Explicit non-goals |
| --- | --- | --- | --- | --- |
| E5-A — Typed Resource/evidence boundary (COMPLETE) | Closed operations, bindings, evidence and reasons implemented; runtime still unavailable | Shared Contracts and unwired preparation-runtime-v1 messages; no handles or DB migration | Strict round trips, schemas, immutability/digests/authority/unknown versions and architecture guards | Construction, transport dispatch wiring, F |
| E5-B — Durable ownership/lifecycle | Atomic Resource reservation, provider state, leases, budget ledger, quarantine/cleanup skeleton | Forward Node migration keyed by existing ResourceRef; retain E3/E4; no new Core table by default | Fresh/upgrade/reopen/concurrency/crash tests; one Resource per binding | Venv creation or readiness claim |
| E5-C — Full preparation confinement | RuntimeConfinementBackend, owned supervisor/cgroup, capped scratch/output and trusted probes | Mechanism evidence/operation metadata; no authority expansion | Every live enforcement/death probe; unavailable host fails closed before builder | Acquired code, weaker RLIMIT fallback, privileged host setup |
| E5-D — Interpreter provenance | Tool Registry pinned CPython 3.12 closure and confined fixed inspection | Interpreter fingerprint/sealed binding; no competing registry | Wrong version/layout/venv/startup/PATH/update negatives; exact trusted identity | Source imports, installs, venv construction |
| E5-E — Empty environment construction | Closed accounted fresh venv, bounded publication and read-only same-path verification | Existing ownership/ledger, immutable inventory; no new domain ID | Empty packages/no pip, all writes charged, no source sentinel, partial never READY | Runtime execution, dynamic import checks |
| E5-F — Evidence/revalidation + narrow pump | Seal evidence, READY/current validity, typed same-Run prepare/status/revalidate through existing Core admission/neutral adapters | E5 evidence Artifact; append verification; existing Run/preparation refs; no final manifest/result acceptance | Replay/conflict/expiry/disconnect/Node restart/drift/cleanup tests; current proof required | E6 terminal Result/Core COMPLETED, F authorization |
| E5-G — Synthetic vertical | Real D→E2→E3→E4→E5 chain with production boundaries and controlled source | Migration-backed isolated Core/Node stores | One Resource, restart/reuse, immutable source, no source/package/Secret/target activity | Real target, full E6–E9 acceptance |
| E5-H — Real Kali acceptance | Manual-only preflight/preparation/restart harness and operator record | No new authority or persistence semantics | Actual 3.12/delegation/limits and same-Resource revalidation proven; fail-closed report if host lacks any requirement | PoC entrypoint, host configuration automation, M20-F |

Before each implementation, read this package and existing E1–E4 code. If a platform fact
invalidates a chosen mechanism, stop positive implementation and review the smallest
alternative. Do not quietly change the support profile, weaken a feature, auto-install a
runtime or call generic process execution to make a smoke succeed.
