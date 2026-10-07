# M20-E5-E — empty environment construction

**IMPLEMENTED OFFLINE; real Kali construction acceptance remains required.** E5-D is
CLOSED on the operator's real provenance acceptance. E5-F–H, E6–E9 and M20-F have not
begun; M20-E remains OPEN. This implements the already approved
[provider](M20E5_PYTHON_PROVIDER.md), [limits](M20E5_RUNTIME_LIMITS.md), and
[Resource](M20E5_RUNTIME_RESOURCE.md) design, not a new execution architecture.

## Closed construction and verification

The Node-private `PythonEnvironmentProvider.create_empty_environment()` accepts only an
existing authenticated `ResourceOperation` and optional cancellation service. E5-B checks
the exact admitted E3 Run, E4 metadata, Mission/plan/permit/Node binding, allowed action,
lease/generation and remaining budget. No caller executable, argv, code, package, mount,
environment variable or network destination exists in this API. No source bytes are read
or mounted. No SDK, Core, MCP or neutral-transport dispatch wiring is added.

Before construction the provider rehashes the complete D distribution and compares the
exact `m20-e5-python-distribution@2` / `m20-e5-python-runtime-profile@1` projection and
backend pins with the immutable owned D evidence. Both `TKINTER_TCL_TK` and
`PACKAGE_MANAGER` remain excluded. The thirteen existing C controls run freshly; their
limits and D's identity operation are unchanged. The constructor runs only the certified
selection, never the full provisioning `lib` tree.

The pinned native helper invokes a pinned, read-only provider-owned Python program:

```text
construction: /runtime/bin/python3.12 -I -S -B /trusted/environment.py create
verification: /work/venv/bin/python3.12 -I -B /trusted/environment.py verify
```

### Installed trusted provider asset (real-host compatibility correction)

The package's `_environment_helper.py` supplies the exact reviewed **bytes**, not the
execution path. The operator explicitly installs those bytes as
`environment-<SHA-256>.py` beside the configured pinned native confinement helper, with
mode **0444** (native helper 0755; directories 0755). Every ancestor must be trusted,
non-symlinked and non-group/world-writable. Production derives this path internally;
there is no caller helper-path/code option, PATH search, automatic copy, installer,
download or permission normalization. A normal group-writable Git checkout can remain
unchanged: it is not mounted as trusted executable material.

Both create and verify require exact agreement between the installed bounded regular
file, the bundled reviewed bytes and the existing `helper_sha256` evidence binding.
Checks use no-follow/stable reads and parent-chain checks before execution, again before
journaling/launch and after completion. The namespace mounts only this installed asset
read-only at `/trusted/environment.py`. No new identity, schema or migration is needed;
historical evidence and passive replay semantics are unchanged. Missing/unsafe assets
fail with `CONFINEMENT_UNAVAILABLE` and bounded helper trust diagnostics, not the unrelated
prepared-content mismatch previously propagated from the distribution trust utility.
The strict `_trust()` and native C/D `_trusted_tool()` checks remain unchanged.

The first real Kali E attempt passed the C probes and D identity but failed before an
environment-construction journal row: its former executable helper path was inside a
664/775 checkout, correctly rejected by filesystem trust. This correction separates
installation from source data; it does not weaken trust or change the accepted D pins.
The quarantined runtime remains forensic history only: do not repair/reuse it. The next
real attempt requires fresh E3/E4 admission and a fresh Node runtime. Real E acceptance
is still pending; no readiness or acceptance status is promoted by this correction.

The fixed builder uses CPython `venv.EnvBuilder(system_site_packages=False, with_pip=False,
symlinks=False, upgrade=False, upgrade_deps=False)`. Its file/config/template copies are
intercepted and charged **before** each write. An audit gate rejects unaccounted mutation,
unexpected links, process/network calls and package bootstrap. This gate is for a fixed
trusted stdlib builder, not a general hostile-Python sandbox. Kernel syscall restrictions
also deny new processes and sockets. No pip/ensurepip, install, download, source import or
target credential resolution occurs; inert activation templates are retained but never run.

CPython 3.12 requires site initialization to establish the venv prefix: verification
deliberately uses `-I -B`, not `-S`. Before it runs, the publisher has verified the exact
empty site-packages tree and absence of `.pth`, startup hooks and unexpected files. The
fixed verifier must report `/work/venv` prefix, `/runtime` base prefix, exact version/ABI,
isolated mode, bytecode disabled and user-site disabled. The only four import paths are
the D base's zip sentinel, stdlib, lib-dynload and the empty venv site-packages. No acquired
module is imported to establish this proof.

The final audit found a genuine E-only admission gap: D's `-S` proof need not execute a
base `sitecustomize`, but E's site-enabled verification would. E now rejects hook modules,
packages/caches and top-level `.pth` material at the visible base stdlib/lib-dynload locations
**before** controls or construction. It does not filter, repin or broaden D's view and does
not change D's historical acceptance. Six regressions certify a synthetic hook-bearing base
through the unchanged D path, then prove E rejects it before invoking the backend.

## Storage, export and ledger

Construction runs under the existing delegated cgroup-v2 + bubblewrap + static native
supervisor/guardian. Both E operations have a **separate fixed** limit profile: pids 8,
512 MiB cgroup memory with zero swap, 30 seconds and 4 KiB combined output. Construction
uses a 144 MiB / 256-inode private `/work/venv` tmpfs; tmp/home each remain 4 KiB / 8 inodes.
The E-only fixed limit profile is `m20-e5-empty-environment-limits@2`: cumulative logical
writes remain bounded separately at 128 MiB, with 16 MiB filesystem-allocation slack.
No child has a writable host bind. All twelve required controls still apply.

The builder exports a length-framed, bounded typed manifest plus file bytes into an
anonymous regular memfd (maximum 128 MiB + 64 KiB), not stdout. After child/guardian cleanup
and empty-group proof, the native supervisor seals and streams it through a bounded pipe
with requester-liveness and deadline checks. A secondary `RLIMIT_FSIZE` bounds the anonymous
export; it does not replace cgroup, tmpfs or pre-write accounting enforcement.

The supervisor creates this export memfd with `MFD_CLOEXEC | MFD_ALLOW_SEALING`.
Only the fixed construction child duplicates it to **FD 3**, explicitly clears
`FD_CLOEXEC` (including the `dup2(3, 3)` case), and closes **all** FDs above 3 with
`close_range`. Verification and C/D operations retain the original close-all rule.
Bubblewrap inherits the ordinary non-CLOEXEC FD into its command; its separate sealed
`--args` descriptor is consumed and closed before the command. The fixed native fixture
checks FD 3 is an unsealed regular memfd with CLOEXEC clear, then the isolated Python
constructor writes only to that FD. The Node destination pipe, cgroup/control descriptors
and unrelated sockets do not enter the constructor. The supervisor's private copy remains
available for the existing post-cleanup seal/bounded stream; no caller FD API is introduced.

There is **no `--preserve-fds` option in Bubblewrap** and no `--sync-fd` substitution.
The latter is a lifetime synchronization descriptor, not generic export preservation.
This follows the [Bubblewrap 0.11 command/FD implementation](https://github.com/containers/bubblewrap/blob/v0.11.0/bubblewrap.c).

`EnvironmentStorage` writes an exclusive export file, then publishes only a closed
whitelist: six directories, three exact copied interpreter files, config, four activation
templates and `lib64 -> lib`. No archive extraction or general path API. It checks framing,
size, modes, hashes, single-link regular files and exact config. Traversal uses no-follow
directory/file descriptors. Files and directories are fsynced, then `publishing` is atomically
renamed to `venv` beneath the Resource-owned private directory. Verification mounts that
publication **read-only at the same `/work/venv` path**. The distribution and environment
are rehashed again before successful commit.

Storage is under the configured workspace root's private `python-environments/<hashed-ref>`;
paths are Node implementation metadata, not Resource identity. Startup does not create
this storage. A held constructor creates it only after persistent budget reservation.
No group/world-writable non-sticky ancestor or symlink is accepted. A sticky shared ancestor
may support isolated test storage, but the installed trusted helper/runtime chains remain
subject to the unchanged stricter trust checks.

E5-B reserves all categories before work. For E alone, minimum peak reservations are
temporary `544 MiB + 139,264 bytes` (570,564,608 bytes), memory 520 MiB, processes 11, per-process envelope
38 seconds and depth 4. Cumulative ceilings reserve 300 seconds, 61,440 output bytes,
5,465 entries and 597,991,424 write bytes. These are **additional to existing D/E3/E4 spent
usage**, not a proposal to enlarge a permit. Successful environment accounting records
`2 * actual environment bytes + 2 * actual export bytes` (scratch, anonymous export,
Node export and publication), and twice the actual created entries. Control/descriptor/
evidence overhead is explicitly conservatively charged, not presented as measured zero.
Elapsed time and captured output are measured. Failed/interrupted reservations stay fully
spent; no refund, reset, hidden repair or automatic rebuild. Retained export/partial bytes
remain private and attributable; byte-retention cleanup is not implemented by this slice.

The temporary reservation is `scratch + 2 * export_limit + write_limit + 16 MiB + 8 KiB`:
private tmpfs, anonymous export, Node export, durable publication, retained conservative
control allowance and the two small tmp/home mounts. It includes **both** 64 KiB export
headers. The write reservation is `control_writes + 2 * write_limit + 2 * export_limit +
64 KiB evidence`. Memory reserves the fixed 512 MiB group ceiling plus 8 MiB supervisor
headroom. Capacities are never inferred from executable size or enlarged by caller input.

### Real Kali v3 fixed-capacity correction

The operator's fresh `m20e5e-real-acceptance-v3` passed owned interpreter inspection,
fresh C controls, trusted helper checks and Bubblewrap launch. Construction finished with
exit 95 / `EMPTY_ENVIRONMENT_OPERATION_FAILED`, memory peak 102,580,224 bytes and no
OOM/pids-limit events; provider failure remained `RUNTIME_UNAVAILABLE / VENV_CREATION_FAILED`.
The accepted uv CPython 3.12.14 executable is **30,913,848 bytes**. CPython's unchanged
`symlinks=False` builder copies `python3.12`, `python`, and `python3`: **92,741,544 bytes**
before config/activation templates. The former 32 MiB cumulative write gate rejected the
second copy, and the former 32 MiB scratch could not hold the final tree either.

The correction selects one fixed conservative E `@2` contract: 128 MiB logical writes,
144 MiB physical scratch, 256 entries, 128 MiB + 64 KiB export, 512 MiB aggregate memory
with zero swap; processes/time/output are unchanged. The supported three-copy workload
leaves over 35 MiB for configuration/templates inside the logical bound. Memory also
allows tmpfs, anonymous export and the trusted helper's copy/read buffers; this is still
a hard cap, not a claim that all arbitrary bases fit or that real E acceptance has passed.

Provider constants, summary/manifest validation, standalone helper literals, native tmpfs,
native cgroup/RLIMIT checks and durable reservations agree. The standalone `-I -S` helper
imports no provider module. Regressions exercise real EnvBuilder using a generated sparse
30,913,848-byte test source copied three times (never executed), then fill the remaining
write allowance through the production gate and reject the next byte. No large fixture is
committed. Compiled native constants are checked against provider/helper capacities; a real
Bubblewrap mechanical test invokes production mount setup and allocates all 128 MiB on its
144 MiB tmpfs. These are mechanics checks, not cgroup/provenance/Kali acceptance.

Historical `@1` reports remain immutable/readable at their original 32/128 MiB limits.
No new operation may use that historical profile; current constructors require `@2` proof.
No public Contract or SQLite schema change/migration is needed. Python helper bytes and
native binary bytes change, so **both** require explicit fresh installation/SHA pins.
D interpreter/distribution/projection pins, copy semantics and all security controls remain
unchanged. The v3 runtime stays quarantined forensic evidence; no repair or reuse.
The next real acceptance requires a fresh Core-approved budget/admission and fresh Node
runtime. It is not run automatically. E5-F and readiness promotion have not begun.

## Lifecycle, immutable evidence and recovery

### Real Kali v4 workspace-composition correction

The operator's fresh `m20e5e-real-acceptance-v4` applied all exact E `@2` construction
reservations, then failed before a `python_environment_create` confinement row or environment
storage directory existed. `EnvironmentStorage.reserve()` correctly rejected a non-sticky
0775 `workspaces` ancestor; its `ValueError` reached the generic interrupted-operation path
(`PREPARATION_INTERRUPTED`, no runtime reason). This was not another capacity/helper failure.

`NodeConfiguration.prepare_directories()` and the SDK workspace service's fallback root
creation formerly used `mkdir(parents=True, exist_ok=True)` with default 0777. A normal
0002 umask therefore created 0775 roots. E4's recursive child creation also implicitly made
`preparation-source` with that default mode. The corrected production composition creates
each missing runtime/workspace ancestor explicitly at **0700**, traverses without following
symlinks, and checks existing ancestor ownership/non-writability. Sticky shared ancestors
remain permitted under the existing storage rule; the owned leaf cannot be group/world
writable. Existing trusted modes are preserved, never normalized. An untrusted existing
chain fails with bounded `WorkspaceDirectoryError / WORKSPACE_STORAGE_UNTRUSTED`, with no
chmod repair. An excessively restrictive umask can deny access, never broaden permissions.

`preparation-source` is an E4 sibling, not an ancestor of `python-environments`. E4 now
explicitly creates that missing intermediate root as 0700 at its existing materialization
boundary; staging/published/quarantine policy is unchanged. Node startup still creates no
environment store or Resource directory. Only the held, budget-reserved constructor creates
those, with the unchanged `EnvironmentStorage` no-follow and permission checks. Regressions
exercise 0000/0002/0022/0077 umasks, unsafe existing ancestors/symlinks/no-repair, and the
complete synthetic budgeted E constructor under production-created workspace roots.

No helper bytes, pin, compilation, limit profile, schema, migration or dependency changes
are required for this correction. Keep v4 quarantined and untouched; the next operator test
uses a fresh admission/runtime under a trust-compatible existing parent chain. No smoke-only
chmod workaround or automatic Kali acceptance is added. E5-E remains implemented offline,
not real-accepted/READY; E5-F remains unstarted.

```text
CREATING / RESERVED / UNCHECKED
  -> exclusive CREATE_EMPTY_ENVIRONMENT + reserved ledger
CREATING / BUILDING / UNCHECKED
  -> verified confined construction, publication and read-only verification
CREATING / VERIFYING / UNCHECKED + immutable EmptyEnvironmentEvidence
```

Successful E5-E is **not READY**, current VALID, a final preparation receipt, or execution
authority. E5-F owns fresh final evidence/revalidation and the narrow READY/current-validity
promotion path. Production `execute_plan()` remains denied; runtime remains UNAVAILABLE.

`EmptyEnvironmentEvidence` binds Resource/operation/generation, immutable D evidence and
distribution/projection/interpreter/backend pins, builder hash/mechanism/version, exact
manifest/inventory, actual environment byte/file accounting, both confinement reports,
timestamps, attachment and descendant-empty facts, and the unready lifecycle. It is typed,
frozen and stored with a digest. Physical paths do not enter that evidence.

Node migration **0011_empty_python_environment**, after immutable 0010, adds the immutable
`python_environment_constructions` table and permits VERIFYING only with retained evidence.
Evidence, settled operation and Resource-owned Workspace metadata commit atomically. Existing
READY guards and UNCHECKED-only validity checks remain. SQLite CHECK rebuilding uses a
dedicated migration connection with FK checking restored and verified before/after; normal
sessions keep FK enforcement. No shared Contracts, generated schemas, Core schema or
dependencies change. Downgrade is explicitly forward-only to preserve retained history.

Identical completed replay inspects exact history/bytes and spends nothing; it does not
rerun a constructor or turn old confinement evidence into current proof. A wrong owner
cannot poison another Resource; a duplicate active caller cannot quarantine the active
constructor. Stale ownership, expiry, missing/mutated provenance, malformed export, limit
failure, cancellation, missing files or extra import-visible payload fail closed. Active
old-boot construction is interrupted/quarantined; held reservations become spent. A publish
before DB-commit crash leaves private orphan bytes, not evidence inferred from files.
Startup passively verifies retained inventory and quarantines drift, with no subprocess,
storage creation, repair or READY promotion. Historical evidence remains immutable even
when current Resource state is LOST/QUARANTINED. Passive inspection is not a usable lease.

## Offline validation and real acceptance boundary

Tests cover actual local CPython EnvBuilder interception, byte/inode/audit denial, native
sealed/bounded export and requester liveness, exact namespace argument construction,
all-proof enforcement negatives, metadata-backed construction/replay, wrong-owner and active
duplicate protection, crash/reopen/quarantine, integrity/missing/extra-file cases, populated
0010 upgrades, immutable evidence and readiness guards. Synthetic interpreter/probe fixtures
are portable mechanics tests, **not real Kali confinement/provenance acceptance**.

`test_python_projection_native.py` additionally validates generated C/D/E options with
the real Bubblewrap parser (`--args` followed by `--help`), including an intentionally
unsupported-option control. `test_environment_fd_native.py` exercises same/different-FD
duplication, explicit CLOEXEC clearing, closure of unrelated sockets and high FDs, and
close-all verification. Its real Bubblewrap case runs the reviewed constructor using a
local test interpreter/read-only closure and private namespace scratch; it checks the
sealed options FD is gone and only export FD 3 survives. This is FD/EnvBuilder mechanics,
not production projection, cgroup, readiness or real Kali acceptance.

These real CLI cases use installed `bwrap` or explicit `BOBERAGENT_E5_BWRAP`, with optional
`BOBERAGENT_E5_BWRAP_SHA256` verification. They skip only when no binary is available;
an explicitly configured missing/mismatched binary or namespace failure fails the test.
Tests do not install/download tools. The compatibility fix does not change the required
Bubblewrap version, D projection/pins or E5 acceptance/readiness. The later v3 capacity
correction above does change Python helper bytes and the E-only fixed limit profile.

The manual-only [E5-E procedure](../../scripts/manual-smoke/README.md#m20-e5-e-empty-environment-construction-operator-only)
requires a stopped Node with an existing **current authenticated Core E3/E4 admission**,
adequate remaining budgets, a fresh native helper pin and the explicitly installed Python
helper asset. The harness checks that asset before Resource claims/budget spend.
It creates no permit, modifies no
authority and implements no E5-F transport pump. It has not been run automatically.
Reopen/replay output is explicitly passive history, not fresh readiness proof. A small or
expired historic permit must fail; creating eligible authority is an explicit Core/operator
prerequisite, not a hidden harness bypass.

Unsupported: other Python/platform profiles, third-party packages, writable source, shared
venvs, arbitrary commands, automatic authority renewal, package provisioning, final READY
promotion, E5-F transport integration, E6 completion, and all M20-F acquired-code execution.

## Changed-file inventory (WIP plus continuation)

Under `packages/execution-node/src/boberagent_execution_node/`:

- `node.py`;
- `persistence/orm.py`, `persistence/migrations/__init__.py`, and
  `persistence/migrations/versions/0011_empty_python_environment.py`;
- `preparation/_environment_helper.py`, `environment_models.py`, `environment_storage.py`,
  `python_environment.py`, `resources.py`, `runtime_confinement.py`,
  `runtime_confinement_models.py`, `runtime_confinement_store.py`, and `native/e5_confinement.c`.

Under `packages/execution-node/tests/`:

- `test_python_environment.py`, `test_environment_helper.py`, `test_environment_export_native.py`;
- `test_python_projection_native.py`, `test_python_provenance.py`,
  `test_python_resource_ownership.py`, `test_runtime_confinement.py`,
  `test_database_identity_lifecycle.py`;
- `fixtures/environment_export_test.c` and `fixtures/projection_descriptor_test.c`.

Other code/tests:

- `packages/core/tests/test_runtime_preparation_e3.py` (Node migration-head assertion only);
- `tests/architecture/test_m20e5a_boundaries.py`, `test_m20e5d_boundaries.py`,
  `test_m20e5e_boundaries.py`;
- `scripts/manual-smoke/m20e5e_empty_environment_smoke_test.py`.

Documentation:

- this implementation record and `docs/m20/M20E5_ARCHITECTURE.md`,
  `M20E5_PYTHON_PROVIDER.md`, `M20E5_RUNTIME_RESOURCE.md`, `M20E5_RUNTIME_LIMITS.md`,
  `M20E5_RECOVERY_AND_REVALIDATION.md`, `M20E5_ACCEPTANCE.md`, `M20E5C_IMPLEMENTATION.md`,
  `M20E5D_IMPLEMENTATION.md`, `M20E_IMPLEMENTATION.md`, `M20E_ACCEPTANCE.md`;
- `docs/10_M20_UNKNOWN_POC_PIPELINE.md`, ADR 0021/0022 (status references, decisions unchanged),
  and `scripts/manual-smoke/README.md`.

The resumed WIP commit already contained the provider, migration, journal/native extensions,
48 provider/persistence tests, 10 real-stdlib helper tests, namespace argument tests and
readiness/startup guards. The continuation adds six native export mechanics regressions,
six base-startup-hook admission regressions (54 provider/persistence cases total), finishes
type-safe/manual-state reporting and documentation, and runs the complete gates.
