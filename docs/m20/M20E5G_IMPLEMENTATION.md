# M20-E5-G — configured production synthetic vertical

**M20-E5-G CLOSED on operator-supplied real Kali configured-host positive acceptance,
2026-10-19, commit `e2a5855`.** The positive opt-in test executed and passed, rather
than skipping. The earlier development-host skips remain historical evidence below;
they are not rewritten as Linux acceptance. E5-F's
[operator v9/v10 acceptance](M20E5F_IMPLEMENTATION.md#operator-supplied-real-v9v10-acceptance)
remains separate. E5-H manual tooling is now implemented with real acceptance PENDING. E6–E9 and
M20-F remain unstarted. M20-E remains OPEN.

## Operator-supplied real Kali configured-host acceptance

Recorded from the operator's report; no real test was rerun for this documentation
closure. Both WSL and Kali were at `e2a5855`, subject
`continuing the BoberAgent M20 unknown-PoC preparation pipeline`.
The ordinary Node user ran the test on the already provisioned Kali host in fresh
transient delegated systemd service `boberagent-m20e5g-v1.service`.
This is the configured synthetic vertical using authenticated **in-memory transport**
on Kali, not a new cross-machine MCP/E5-H acceptance claim.

Observed delegation:

```text
self_cgroup=/user.slice/user-1000.slice/user@1000.service/app.slice/boberagent-m20e5g-v1.service/supervisor
delegated_parent=/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/boberagent-m20e5g-v1.service
parent_procs=
controllers=cpu memory pids
subtree_control=memory pids
```

Previously accepted production assets and unchanged pins:

| Asset | Exact accepted value |
| --- | --- |
| Native helper | `/home/kali/boberagent-trusted/m20e5e-v4/e5-confinement-helper` |
| Helper SHA-256 | `728a39651186232a671e851fb645c600bdb53c55b8a41e253745b1a61a0bb592` |
| Bubblewrap | `/usr/bin/bwrap` |
| Bubblewrap SHA-256 | `c84e1593e672e85f85b280acb8f98993d2c4e37acd7e1c8544d2b330c557346d` |
| Trusted CPython | `/home/kali/boberagent-runtimes/python/cpython-3.12.14-linux-x86_64-gnu` |
| System library root | `/usr/lib/x86_64-linux-gnu` |
| Distribution manifest SHA-256 | `c06d42d636360299e253448ef32a58979fa04e544976e62937799a447774af9d` |
| Interpreter SHA-256 | `f7c6210eb40fadcd3c2889dddd24a15fc2c9f926aec5a03bf9da66e12d581526` |

No helper rebuild or repin was performed. The opt-in test was present, collected and
actually executed:

```text
collected 6 items / 5 deselected / 1 selected
packages/core/tests/test_m20e5g_vertical.py::test_opt_in_actual_linux_vertical_replay_reopen_revalidate PASSED
================== 1 passed, 5 deselected in 60.81s (0:01:00) ==================
```

The pytest process exited 0. Final service state and reported usage:

```text
Result=success
ExecMainStatus=0
ActiveState=inactive
SubState=dead
MemoryMax=infinity
Consumed 57.403s CPU time, 528.2M memory peak.
```

### Four observed OOM events and their interpretation

During that successful test systemd emitted **four** messages:

```text
A process of this unit has been killed by the OOM killer.
```

The repository establishes intentional bounded memory exhaustion as part of the
thirteen-probe confinement check, not as an accepted failure of Python construction:

- `LinuxRuntimeConfinementBackend.check()` runs every `ClosedProbe` with fresh IDs.
- Its `MEMORY` probe uses a child cgroup with `memory.max=64 MiB`, swap disabled and
  `memory.oom.group=1`. The native fixed probe touches up to 96 MiB to exercise that
  limit. `_passed()` requires `oom > 0`, `pids == 0`, attached/empty containment,
  bounded peak memory and `EXITED` for this specific probe.
- The passing G path invokes this full check four times: interpreter inspection,
  empty-environment construction, first fresh revalidation, and fresh revalidation
  after reopen. Exact replay/status do not add fresh checks.
- Trusted Python identity/construction/verification operations instead require zero
  OOM events; revalidation rejects an OOM in its Python verifier.

Thus the four unit messages match the four expected OOM-producing memory probes.
The supplied service summary does not independently correlate each message to its
child cgroup/probe, so no per-message attribution is claimed without that journal.
All four observations are retained here alongside the successful test/exit status.
Outer service `MemoryMax=infinity` does not remove the explicitly enforced child-cgroup
limits, and the service's 528.2M peak is not a per-probe measurement.

### Closure scope and retained evidence

The passing test establishes the sequence and assertions below, not additional
untested failure-path combinations. No previously accepted E5-E/E5-F runtime was
modified, reopened or repurposed. The transient pytest-managed G Resource is not a
reusable production runtime or execution authorization.

Throughout: `execution_authorized=false`; acquired source unexecuted; no package
installation, Secret delivery or target activity; no terminal CapabilityResult;
Core preparation remains DISPATCHED, not COMPLETED. E6 alone owns terminal preparation
Result/Core completion. Production `execute_plan()` remains denied. At G closure E5-H
had not begun; its [manual tooling](M20E5H_IMPLEMENTATION.md) was subsequently implemented
without claiming H acceptance. E6–E9 and M20-F remain untouched.

## Existing path, unchanged production behavior

`m20e5g_fixtures.establish_d` ends after exact retained synthetic acquisition,
C2@2/C3@2, D3/D4 VALID and D5 ALLOW. All subsequent work uses production Core
admission, CapabilityRegistrationClient/Registry/Router, serialized authenticated
InMemoryTransport, ExecutionNode configuration composition, E3 import, E4 publication
and CorePythonRuntimeService prepare/status/revalidate. No private provider operation,
fake READY row, boot edit or direct DB write is a success shortcut. Tests inspect
Node repositories read-only for accounting and identity assertions.

The opt-in test asserts the *exact* LinuxRuntimeConfinementBackend class, that the
configured Node service owns that same backend, and configured distribution identity.
It does not patch native launches, probes, helper trust or filesystem validation.
Portable tests separately assert configuration selection and unavailable-asset denial
at E4 before publication/Resource construction, following real authenticated E3 import.
Existing F tests with GenerationBackend remain useful portable wiring regressions,
but are explicitly not this positive production proof. No new production primitive,
migration, dependency, helper change or permission workaround is introduced.

## Controlled source and forbidden activity

The retained fixture contains checker.py, package/__init__.py, setup.py and
sitecustomize.py, each beginning with the unique E5G_ACQUIRED_SOURCE_EXECUTED output
sentinel. These are acquired bytes, never modules imported by the harness or a package
to install. Unexpected execution would emit the sentinel before normal behavior;
trusted constructor/provenance output is bounded and retained in the native journal,
and is required to validate as the exact fixed JSON proof. The positive test also decodes
retained native stdout/stderr read-only to reject the sentinel. The source remains read-only;
the test snapshots bytes/modes and rejects bytecode or source mutation across restart.

Runtime tripwires reject generic ProcessService calls, Secret resolution/storage,
browser/listener creation and terminal Result persistence. Parent imports of the acquired
module names, pip or ensurepip fail immediately. Native children still use the unchanged
C/D/E closed command vocabulary and confinement; no target, DNS or public research
provider is needed. These guards supplement, never replace, active Linux controls.

## Positive sequence asserted by the accepted test

1. Fresh migration-head Core/Node stores and actual Node handshake.
2. E2 permit → same reserved Run dispatched by Router → both exact E3 imports.
3. E4 immutable publication; wrong raw/tree digest requests rejected before Resource work.
4. First prepare creates one Resource and dependency-empty environment, UNCHECKED.
5. Concurrent exact replay and reconnect preserve Resource/construction/ledger.
6. Fresh revalidation reaches READY / PUBLISHED / VALID; binding conflict rejects.
7. Exact revalidation replay spends nothing and returns the same proof.
8. Close/reopen both components, reconstruct Core services on the new DB, same Node ID.
9. Status retains history/construction but is UNCHECKED, with unchanged ledger.
10. New explicit validation produces a distinct operation/proof on the same Resource,
    binding/construction/environment inventory; cumulative usage increases, never resets.
11. Source and retained raw/manifest bytes remain exact. Run is QUEUED, Core attempt
    DISPATCHED, no terminal result or Session. No execution authority is created.

Identity is composed from authoritative typed objects: Mission, planning context/plan,
PreparationRef, PermitRef, RunRef, Node/provider version, raw/manifest refs/hashes,
E4 materialization/tree, Resource, sealed binding, construction, environment and fresh
attempt/operation/evidence. Content equality is not reconstructed authority.

## Acceptance invocation and coverage limits

See [manual-smoke README](../../scripts/manual-smoke/README.md#m20-e5-g-configured-production-synthetic-vertical).
The configuration opt-in uses already provisioned trusted assets only; it never repairs,
installs, delegates or reuses the v7/v9/v10 accepted runtime. An explicitly supplied invalid
configuration fails, not skips. No skip is a G completion or host-enforcement claim.

Portable new tests cover unknown preparation, expired authority, untrusted principal,
and production backend selection without fallback. Existing E2/E3/E4 and C/D/E/F suites
remain the fail-closed regression matrix for wrong Node/Run/provider/Artifact, stale policy,
source/environment/interpreter/helper drift, budget exhaustion and interrupted ownership.
The positive test passed on the configured Kali host recorded above; future runs still
require a supported configured host. Not every matrix row has a new G end-to-end test.
Do not claim those additional composed cases from unit coverage alone.

E5-H manual tooling is now implemented; real H acceptance remains operator-run and pending.
E6 exclusively owns terminal CapabilityResult/final manifest/Core completion. Generic
execute_plan remains denied; prepared-runtime availability cannot execute acquired code.

## Historical development-host verification (before Kali acceptance)

The implementation host lacked Bubblewrap and writable delegated cgroup-v2 facilities.
Its positive test skipped explicitly without substituting a backend/provider or claiming
READY. The following results remain unchanged and separate from the later Kali PASS:

- New G tests plus the architecture guard: 6 passed, 1 explicit positive-host skip.
- Serial E2/E3/E4, C/D/E/F, native export/FD and architecture regressions: 429 passed,
  8 skips for unavailable Bubblewrap, absent cgroup delegation or G host configuration.
- Full repository suite: 1667 passed, 9 skipped, one expected duplicate-ZIP warning.
- Lock/locked sync, Ruff, formatting (569 files), strict mypy (517 files) and diff
  checks passed. No dependency or migration changed.

Existing local MCP fixtures required approved socket access after the sandbox denied
socket creation. An earlier overlapping focused run encountered an existing F
PREPARATION_AUTHORITY_STALE failure; its isolated rerun, full suite and final serial
focused run passed without changing that test or production authority checks.
These development-host results alone did not prove configured Linux positive acceptance;
the later operator-supplied Kali PASS above closes that acceptance gap.
