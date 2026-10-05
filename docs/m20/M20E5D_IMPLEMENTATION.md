# M20-E5-D — trusted CPython interpreter provenance

**IMPLEMENTED OFFLINE; REAL KALI PROVENANCE ACCEPTANCE REQUIRED.** E5-C is CLOSED
on operator-supplied real acceptance. E5-E–H, E6–E9 and M20-F have not begun.
Runtime remains UNAVAILABLE / NOT READY; production `execute_plan()` remains denied.

## Approved source and trust transition

The first source is an **operator-preprovisioned uv-managed CPython 3.12 Linux x86_64
distribution**. This refines the original system-installation-only assumption; uv is
not a trust anchor or a production dependency. Nothing discovers, downloads, installs,
builds, invokes uv/apt/pip/pyenv, falls back to PATH/system Python/3.13, or contacts a
research/source/target endpoint. No host-wide Python changes are required.

Node-private `PythonDistributionConfiguration` takes explicit absolute distribution and
system-library roots and reviewed expected interpreter/manifest SHA-256 pins. There is no
executable/code/argv/environment parameter. Backend binaries still use the existing Tool
Registry and unchanged `_trusted_tool()` checks. Logical `python-runtime-3.12` identifies
the closed runtime family; generic Registry availability/version probes are not provenance.

1. Check roots and **every** substitution parent: real directories, root or Node-user UID,
   no symlink components, no group/world write, no setuid/setgid material. Sticky `/tmp`
   is not a trusted distribution location. Same-UID malicious operator and root compromise
   are outside this model; there is no remote vendor attestation or signature claim.
2. Before executing any candidate, inventory regular runtime files and approved links,
   checking modes/owners and bounded reads. Build deterministic sorted canonical JSON
   using the existing canonical serializer (UTF-8, sorted keys, compact encoding); SHA-256
   binds the entire manifest, including root/ancestor path-device-inode-mode/UID/GID pins.
   Paths appear only in the private hash input, not semantic evidence or diagnostics.
3. Require both reviewed expected hashes. An inventory-only operator command reports
   observed pins but **does not authorize execution or prove vendor origin**.
4. Run fresh E5-C controls, then the single reviewed identity under the same supervised
   cgroup/namespace/scratch/output/death-cleanup boundary. Rehash fully before/after.
5. Validate the fixed bounded identity report and append Resource-bound evidence under
   an authenticated, unexpired E5-B inspect claim. Never set READY/current VALID.

## Exactly what is fingerprinted

The base `bin` and `lib` trees are fully inventoried; only their versioned selected
projection is mounted into `/runtime`. Every file/directory/link is checked, including
the interpreter, stdlib, venv templates, extensions, libpython,
and **import-visible caches**. `-B` prevents cache writes, not reads: `.pyc`/`__pycache__`
cannot be silently excluded from an import-visible tree. Unrelated root/include/share
operator noise is both excluded and unmounted. Optional bounded `PYTHON.json` must be a
JSON object; its exact hash is retained as metadata identity, not trusted self-attestation.
The bounded metadata file is included in the selected read-only view when present.

### Approved non-GUI projection refinement

The third real-Kali finding localized absolute RPATHs to the optional Tcl/Tk branch:
`libtcl9.0.so` and `libtcl9tk9.0.so` use `/tools/deps/lib`; `_tkinter` needs them.
The path's absence does not authorize it. [ADR 0022](../adr/0022-m20-e5-trusted-python-runtime-projection.md)
defines `m20-e5-python-runtime-profile@1`, retaining interpreter/core stdlib/non-GUI
extensions/venv/shared closure and excluding the explicit `TKINTER_TCL_TK` feature
and, after the next real-Kali finding, `PACKAGE_MANAGER`.

Selection uses the native exported `PyInit__tkinter` identity plus module/ABI location,
DT_NEEDED graph and explicit supported/unsupported root reachability. It is not a broad
filename denylist. `_tkinter`, the `tkinter` package/caches, feature-private libraries
and dependency-identity/version/sentinel-matched Tcl/Tk data are excluded. Unrecognized data and
unrelated stdlib remain selected; `turtle`/`idlelib` are not speculatively removed,
but their GUI imports cannot work in this non-GUI profile. Alternative GUI module
overlays and packed `python312.zip` layouts remain rejected. Required venv/stdlib
material cannot be removed.

The subsequent membership correction replaces the tentative-exclusion/retained-consumer
heuristic with `SUPPORTED_ONLY`, `UNSUPPORTED_ONLY`, `SHARED` and fail-closed `UNKNOWN`
ownership. Exact inventoried `/runtime/lib` bare bindings and owner-bound path edges
are traversed transitively; absent SONAME does not discard an edge, and a conflicting
declared SONAME rejects. No nested-basename guessing. Reached unsupported libraries
without SONAME cannot become supported roots merely because that tag is missing.
Genuinely shared libraries remain selected and undergo unchanged RPATH eligibility.
Unreachable declared libraries/cycles and ambiguous entry points fail closed.
The exact base partition is checked; excluded native aliases remain excluded and
selected hardlinks/byte-identical native copies into excluded bytes reject.

Offline fixtures reproduce the reported `_tkinter` dependency vector, including
`libtcl9tk9.0.so` and `libtcl9.0.so`, with both present and absent SONAME metadata.
Both are excluded when unsupported-only, while their original absolute RPATH bytes
remain hashed evidence. The supplied real trace did not report their SONAME tags;
these fixtures are not a claim of real-host provenance acceptance. Tk feature data,
package-manager exclusion, required venv, split-PT_LOAD and `$ORIGIN` checks remain.
Diagnostics remain bounded `RUNTIME_INTEGRITY_FAILURE`, stage `distribution_inventory`.
See ADR 0022 for exact supported-root criteria and membership authority boundaries.
No distribution bytes are patched/deleted, schemas/history are not rewritten, and
E5-E/F remain unimplemented; runtime stays UNAVAILABLE, not READY.

The next real-Kali finding was trusted uv provisioned pip 26.2.1 in nonempty
site-packages. Base presence is no longer rejected: the complete
`lib/python3.12/site-packages` namespace (directory, pip/other packages, dist-info,
README, caches, native files) is excluded as `PACKAGE_MANAGER`. All excluded bytes
remain bounded, trusted and hash-bound. They cannot contribute executable RPATH
eligibility or support authority, and malformed ELF still rejects. The selected
namespace has **zero site-packages entries**; the manifest validator enforces this.

The complete stdlib `ensurepip` package, caches and bundled wheels are also excluded:
static CPython 3.12 inspection confirms that it bootstraps pip from wheels. Required
`venv` stays selected; its `with_pip=False` construction does not call `_setup_pip`.
No venv, pip, installation or E5-E constructor is implemented by this refinement.
Alternative ensurepip module overlays fail closed.

Bounded Python-script/shebang and AST console-entry-point facts connect launchers
to modules in the excluded namespace. pip, pip3, pip3.12 and renamed equivalent
wrappers are excluded without a filename/version blacklist. Distribution metadata
is hashed evidence, not executable discovery. Unknown/dependent wrappers reject;
only proven launcher aliases under bin are deliberately excluded. Retained links
cannot reach package-manager files. Static stdlib-family/Tk imports identify the
idle launcher under the GUI feature. pydoc, 2to3 and python-config remain selected
when they do not depend on excluded material. Launcher inspection is bounded to
256 KiB per script, 20,000 AST nodes, 128 inspected records, 2 MiB cumulative reads
and 64 dependency-family records; it is not arbitrary program analysis.

All excluded base material still needs trusted owners/modes/parents, approved links,
stable bounded reads and structurally valid ELF. Unknown/malformed ELF is not exempt.
Only search-path executable eligibility is deferred until membership is known.
Every retained ELF still rejects absolute RPATH/RUNPATH; interpreter
`$ORIGIN/../lib` remains accepted when confined. A shared Tcl library stays retained
and must pass that policy. Distribution bytes are never patched/deleted.

Manifest `m20-e5-python-distribution@2` and `PythonProjectedDistributionIdentity`
bind exact profile/base/selected+support/excluded hashes and a combined projection
digest. Typed exclusions preserve feature and native/package/library/data roles,
plus provisioning-namespace, stdlib-bootstrap and launcher roles.
Old `@1` manifest/identity shapes and hashes remain immutable/readable; a v1 manifest
cannot be reinterpreted as a v2 projection or reused against newly inventoried pins.
Existing JSON evidence columns need no migration; schema exports are regenerated.
The existing profile `@1` has an exact hash-bound feature list: fresh evidence always
uses `(TKINTER_TCL_TK, PACKAGE_MANAGER)`. Historical explicit Tk-only v2 evidence
keeps its exact bytes/hashes and remains readable, but is rejected for current
exposure/repinning. Nothing silently reinterprets sealed history. The feature list
and changed profile digest unambiguously bind this refinement within the v2 shape.

D's fixed identity now uses a bounded Node-private read-only mount descriptor with
exact selected membership. Complete selected subtrees may be bound; ancestors of
exclusions are split, never bound wholesale. The native helper validates closed
directory/bind/relative-link records, then passes sealed NUL arguments to bubblewrap.
Descriptor bounds are 1 MiB/2,046 mount records; native arguments are capped at 2 MiB/
8,500. The existing E5-B ledger additionally reserves conservative descriptor/argument/
mount-scaffold costs: temporary/control maximum 16 MiB + 12,288 bytes, 16 MiB extra
cumulative writes, and 2,050 extra control entries. Insufficient authority rejects
before inventory/probes; the permit's limits are never enlarged. Inability to
represent a view fails during inventory, before candidate execution. No environment
construction, workspace Resource or general-purpose command interface is introduced.

**E5-D certifies a versioned executable runtime projection. E5-E must instantiate
exactly that certified projection.** `verify_exposure()` rejects extra, missing,
excluded or changed selected entries, including site-packages, pip wrappers,
ensurepip/wheels and Tcl/Tk. Historical Tk-only profiles cannot authorize current
exposure. This is a future constructor obligation, not
a claim that E5-E exists. Whole-tree exposure is forbidden. Rebuild/repin the helper,
review fresh v2 manifest/projection pins, then rerun real Kali provenance acceptance.
The offline change does not close D or set READY.

Bounded non-executing ELF64 inspection validates x86_64 and collects DT_NEEDED across all
runtime ELF material. Bare SONAME closure uses the explicit library root; no ldd,
PATH or implicit host search. The loader is pinned as well. Only selected library files,
not the whole library directory or `/usr`, are mounted into `/support`. No arbitrary
external RPATH/RUNPATH is admitted; only origin-relative entries inside the runtime view.
The initial layout supports `/lib64/ld-linux-x86-64.so.2`, not every Linux ABI.

The operator's real-Kali inventory exposed a static parser compatibility defect:
CPython 3.12.14's `DT_STRTAB=0x3ff5d8`, `DT_STRSZ=0xa51a` crosses adjacent
file-backed `PT_LOAD` ranges. The former single-segment assumption was invalid.
The bounded static reader now resolves each virtual portion through its own file
offset (not necessarily contiguous on disk), using only `p_filesz`, never BSS/
`p_memsz` zero-fill. Gaps, conflicting overlapping bytes, malformed mappings,
64-bit range overflow and out-of-file reads fail closed; the 4 MiB string-table
limit remains. Overlapping mappings are accepted only when requested bytes agree.
ELF64/little-endian/x86_64, loader, dependency closure, normalized in-root `$ORIGIN`,
filesystem trust and link policies remain unchanged. Synthetic offline regressions
cover the reported layout; no candidate or external ELF tool was executed to debug
it. This fix is **not real Kali provenance acceptance**: operator inventory and the
existing confined provenance preflight still must pass. Runtime remains unavailable.

A second real-Kali static failure was `lib/libpython3.so` declaring
`DT_NEEDED=$ORIGIN/../lib/libpython3.12.so.1.0`. A SONAME-only regex and basename-only
internal-library shortcut were insufficient. Node-private dependency records now retain
the declaring ELF path, raw string, BARE_SONAME/PATH_DEPENDENCY kind and normalized
resolved path for pathname dependencies. Bare names keep the existing 128-character
basename grammar and resolve through the explicit support root; an unrelated internal
file with the same basename no longer suppresses that closure.

Pathname dependencies admit only `$ORIGIN/…` or `${ORIGIN}/…`, bounded to 1024
characters with bounded nonempty components. ORIGIN is the **declaring object's**
directory, not the interpreter's directory or current working directory. Normalization
must stay within the object's trusted root, traversing inventoried real directories;
the exact final target must be an inventoried ELF regular file or the existing approved
one-hop link to one. Missing/unmounted paths, special/untrusted material, absolute/plain
relative paths, other tokens, shell/environment syntax and backslash tricks fail closed.
Distribution pathname dependencies use exact bin/lib inventory records, not basename
matching, extra traversal or duplicate hashing. Support-object ORIGIN paths are limited
to the existing flat `/support/<name>` view; nested support layouts remain unsupported.
This is DT_NEEDED resolution, **not** RPATH/RUNPATH search or a general loader emulator.

For the preceding DT_NEEDED fix, the historical v1 canonical format was unchanged:
sorted file/link records and content hashes
already bind declaring ELF bytes (including raw dependencies), exact target material and
root identity. Repeated edges do not duplicate distribution records; support closure
remains sorted, bounded and deterministic. Existing sealed evidence is not rewritten;
changed closure/pins fail revalidation rather than being automatically repaired. This
compatibility fix is offline only and does not change the real acceptance/readiness gate.
Owner-bound dependency records also obey the existing configured aggregate entry cap;
retaining owner identity does not introduce an unbounded edge collection.

Links must be relative, exactly one hop to an inventoried regular file within their own
approved root. No directory symlinks, external links, chains, devices, sockets or FIFOs.
File modes, owners, targets, sizes and bytes participate; mtimes do not supply identity.
Default inventory caps: 25,000 entries, 1 GiB total, 64 MiB/file, 128 KiB metadata,
32 external libraries, 60 seconds per full traversal. Operator configuration may reduce
or boundedly adjust aggregate limits; no unbounded traversal is supported.

## Fixed identity and confinement

The reviewed native helper now has a separate closed `python_identity` operation; the
thirteen `ClosedProbe` values and E5-C semantics are unchanged. Its only candidate launch
is `/runtime/bin/python3.12 -I -S -B -c <constant BoberAgent identity program>`.
The program imports only trusted stdlib sys/os/json/sysconfig; no source, site, venv,
package manager or caller code. The environment is empty except fixed LANG, scratch HOME/
TMPDIR and provider-owned `LD_LIBRARY_PATH=/runtime/lib:/support`. No inherited PYTHONPATH,
LD_PRELOAD, user site, activation, cwd import, control FD or secret enters the payload.

Bubblewrap binds only the verified selected projection/support files and reviewed helper. Source is
absent, network namespace empty, `/proc` read-only, root read-only, three private capped
scratch mounts, capabilities dropped, namespace/control syscalls denied. The native
supervisor attaches the blocked launcher before execution, bounds both output streams,
uses monotonic deadlines and an independent guardian, kills the exact group and proves
it empty. The initial fixed execve has a pointer-bound seccomp exception; ordinary later
execve and execveat are denied. This is **not** a hostile-interpreter/code sandbox or a
claim against a trusted interpreter deliberately recreating that pointer/address.

Fixed decoded facts must be CPython, numeric exact `3.12.patch`, Linux/x86_64, approved
SOABI/cache tag, `/runtime` prefixes, fixed executable and exact three stdlib search paths,
isolated/no-site/no-bytecode flags. Provider family is >=3.12,<3.13, not forever 3.12.14;
each dossier pins its actual patch, binary and full closure. Unexpected paths/facts/output
fail with bounded existing E5 runtime reasons; raw environment/stderr is never exposed.

## Evidence, accounting and durability

Existing `PythonInterpreterIdentity` now admits the approved uv layout and contains
historical `PythonDistributionIdentity` or current `PythonProjectedDistributionIdentity`:
logical relative executable, manifest/support/root/metadata and projection digests,
count/size and provisioning label. Existing `PythonRuntimeEvidence-v1` gains
`PROVENANCE_VERIFIED`, restricted to interpreter inspection, complete enforcement and
**no environment**. This is historical provenance, not VERIFIED environment/readiness.
Old system-layout/VERIFIED dossiers still decode; unknown layouts/versions fail closed.

Node migration `0010_python_provenance` appends `python_runtime_evidence`, keyed by the
existing exclusive Resource operation with restrictive foreign keys and immutable update/
delete triggers. It retains the sealed binding/evidence hashes, typed evidence and private
canonical manifest. It also binds confinement journal operations to the inspected input
digest, preventing conflicting operation-ID replay. No Core migration or competing Resource
identity/store. Existing READY/phase/validity guards remain unchanged.

`inspect_owned_interpreter()` consumes only an E5-B INSPECT_TRUSTED_INTERPRETER claim.
It reserves all fourteen bounded operations, conservative control/storage overhead and
full hashing time **before** work. It requires at least 214 seconds of remaining permit/
lease, 11 processes including supervisor/guardian overhead and the configured ledger
ceilings. Actual total time/output settle; unmeasured write/file/memory costs remain
explicit conservative charges, not invented measurements. Budget exhaustion rejects.
Persistence/claim completion is atomic. Replay reads immutable evidence; it does not grant
fresh applicability. Changed interpreter/backend/request cannot replace a sealed binding.

Failure/ambiguity quarantines and retains a typed failure in the existing operation history,
with conservative spent reservations. E5-B startup ownership recovery and E5-C owned-group
reconciliation handle interrupted work; restart never infers success. Completed history
survives reopen unchanged, still CREATING/RESERVED/UNCHECKED, never READY.

`revalidate()` fully rehashes and compares all retained distribution pins. Changed binary,
stdlib, extension/library, link/mode/owner, root/parent binding or schema fails closed, not
mtime-only validation or automatic repair. Historical identity is not current authority.
Future E5-E must also obtain current ownership/authority and fresh confinement; that
constructor and any optimized revalidation are deliberately absent.

## Validation and remaining gate

Portable tests use synthetic ELF material and a fake fixed identity backend, plus real
native-helper regression wiring with **simulated** kernel controls. They prove deterministic
inventory/validation, trust-before-execute, family/path/environment rejection, mutation and
revalidation failures, immutable evidence, migration upgrade/reopen and interruption. They
do not prove real Kali identity/enforcement. The [operator preflight](../../scripts/manual-smoke/README.md#m20-e5-d-trusted-cpython-provenance-only-kali-preflight)
must be run explicitly using already provisioned 3.12 material.

The standalone preflight has no current preparation permit. It retains the same typed
interpreter/enforcement facts and journal refs in a dedicated runtime, **without fabricating
a Resource, PreparationPermit or Resource-bound evidence**. Resource-bound production
inspection is exercised with real E5-B authority/ledger persistence in automated tests.
Do not reuse an expired E4 permit for later construction. No E5-E work or final E6 receipt,
source bytes/import, workspace allocation, target, Secret, Session or execution occurs.
