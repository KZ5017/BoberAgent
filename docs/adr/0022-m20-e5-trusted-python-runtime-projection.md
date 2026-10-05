# ADR 0022 — E5 trusted Python executable projection

Status: accepted by the operator's E5-D refinement request; implemented offline.
Real Kali provenance acceptance remains required. E5-E and M20-F have not begun.
Refines [ADR 0021](0021-m20-e5-prepared-python-resource-and-enforcement.md).

## Context

The operator's preprovisioned CPython 3.12.14 distribution includes optional Tcl/Tk
libraries with absolute `/tools/deps/lib` RPATHs. The interpreter uses the admissible
`$ORIGIN/../lib`. Missing external directories do not make absolute search safe.
Ignoring optional objects while mounting the full distribution would certify one
runtime and execute another. Removing or patching operator files is not acceptable.

## Decision

`m20-e5-python-runtime-profile@1` defines the CPython 3.12 Linux x86_64,
stdlib-oriented, dependency-empty, non-GUI executable view. Interpreter, core
stdlib, non-GUI extensions, venv and retained shared closure are required/supported.
`TKINTER_TCL_TK` and `PACKAGE_MANAGER` are explicitly unsupported optional features,
not a caller denylist.

The static selector identifies the importable `_tkinter` extension using both its
CPython module location/ABI and exported `PyInit__tkinter` dynamic-symbol identity.
It follows owner-bound DT_NEEDED edges to exact inventoried libraries and excludes
only the feature-private closure. Explicit supported-root reachability, rather
than merely being outside the exclusion set, establishes a retained consumer:
its absolute RPATH then fails normally. The `tkinter` Python package,
including caches, is absent. Version-matched Tcl/Tk data trees are excluded only
with an exclusive library's SONAME (or unambiguous incoming dependency identity
when SONAME is absent) and the `init.tcl`/`tk.tcl` feature sentinel.
Unrecognized data remains inventoried/selected; no speculative stdlib pruning.
Alternative GUI Python modules and an opaque import-visible `python312.zip` overlay
remain unsupported layouts, rejected rather than silently filtered.

### Native dependency ownership correction (offline)

The next Kali trace showed `lib/libtcl9.0.so` still selected after projection. Its
`/tools/deps/lib` RPATH rejection was correct. The old selector dropped exact bare
dependency edges lacking a matching SONAME, then promoted SONAME-less reached
objects and any objects outside its tentative exclusion set to retained consumers.
Those are membership defects, not reasons to relax executable eligibility. The
reported trace does not include library SONAME tags; offline fixtures cover both
present and absent tags without asserting which metadata the host contains.

The selector now computes transitive reachability independently from supported
roots and unsupported Tk/package-manager roots, with explicit four-way ownership:

- `SUPPORTED_ONLY`: retain, subject to unchanged executable eligibility.
- `UNSUPPORTED_ONLY`: exclude with the owning feature, including native aliases.
- `SHARED`: retain only through supported-root reachability; normal eligibility
  still applies. A supported dependency on an excluded entry point/namespace rejects.
- `UNKNOWN`: an unclaimed declared shared library or closed unreachable component
  rejects; ambiguity never silently selects or excludes bytes.

Supported roots are the interpreter, executable/loader-bearing or canonical `bin`
entry objects, native stdlib module identities, CPython core function identities,
and otherwise unclaimed SONAME-less native entry objects/forwarders into the core
API. That last conservative retained-root category applies only outside unsupported
reachability and with no incoming internal edge: absence of SONAME on a reached
feature library is **not** a supported-root claim. Unreachable library cycles remain
unknown. Feature overlap uses deterministic Tk ownership for shared unsupported
closure outside package-manager namespaces; it never grants executable authority.

Bare internal dependencies bind only in the fixed inventoried `/runtime/lib`
namespace; explicit paths remain normalized and owner-bound. Declared SONAME
conflicts reject, absent SONAME cannot erase an exact ELF edge, and a similarly
named nested file is not a match. Selected dependency closure uses the same resolver;
external requirements still use the explicit trusted support root. No recursive
basename matching, host search-path probing, `ldd` or candidate execution is added.

Selected/excluded sets explicitly partition the complete base projection universe.
One-hop aliases into excluded libraries are excluded; selected native hardlinks or
byte-identical copies of excluded objects reject. All excluded bytes still pass
mode/ownership, stable bounded hashing, ELF structural and symlink safety checks.
The offline reported `_tkinter -> libtcl9tk9.0.so + libtcl9.0.so` graph excludes both
libraries, package/caches and matched Tcl/Tk data. Fresh pins are required if
membership changes; historical evidence and manifest schemas remain unchanged.
This is not real Kali acceptance, runtime READY or E5-E construction.

### Approved package-manager refinement (next real-Kali finding)

The trusted uv base contains pip 26.2.1 and launchers. The former rejection of all
nonempty site-packages was incompatible with a provisioning base; it is replaced
by an explicit `PACKAGE_MANAGER` selection. The entire `lib/python3.12/site-packages`
namespace, **including its directory**, packages, metadata, README, caches and any
other contents is excluded, independent of package/version. Every byte still passes
base trust, bounded stable hashing and structural ELF inspection. Excluded native
dependencies/RPATHs supply no executable authority or retained support closure.
A retained ELF depending on excluded material rejects. Malformed ELF still rejects.

Static reading of CPython 3.12's `ensurepip` shows wheel-based pip bootstrapping;
its complete package, `_bundled` wheels, caches and data are also excluded. `venv`
remains required: CPython's construction guards `_setup_pip` with `with_pip`, so
the future reviewed without-pip operation need not import ensurepip. This does not
create an environment now or authorize dependency installation later.

Python launchers are identified by shebang plus bounded AST imports and console
entry-point calls (`sys.exit(imported_callable(...))` or an imported callable under
the literal `__main__` guard). References to a module rooted in the inventoried
excluded site namespace establish package-manager dependency, not executable
filename or installed version. Installed distribution metadata is hash-bound as
excluded evidence, never imported or executed. Recognized wrappers and their
one-hop `bin` aliases are excluded; unresolved/dynamic or unsupported legacy
metadata-based wrappers into excluded material reject rather than remain selected.
Arbitrary retained aliases cannot reach excluded bytes. This is bounded static
classification of trusted provisioning launchers, not a general script-safety proof.

For stdlib GUI launchers, bounded reads follow the referenced module's own family
to explicit Tk imports: the ordinary idle entry point into `idlelib.pyshell` is
excluded under `TKINTER_TCL_TK`, regardless of launcher filename. No speculative
removal of idlelib/turtle as library data. pydoc, 2to3 and shell config tooling remain
selected absent an identified excluded dependency. No supplied source is imported.

The v2 evidence shape already carries typed feature/role membership, so no v3 or
database migration is needed. Profile `@1` now emits the closed feature tuple
`(TKINTER_TCL_TK, PACKAGE_MANAGER)`; its **exact tuple and profile digest** distinguish
it from historical Tk-only `@1` evidence. Old explicit feature tuples and their
serialization/hashes remain readable unchanged, never upgraded. Fresh inventory
always emits both features; exposure compilation rejects historical Tk-only
profiles, and old pins fail current revalidation. New review/repinning is required
even if the selected interpreter bytes did not change.

Every base `bin`/`lib` entry still undergoes filesystem trust, stable bounded
hashing and ELF-structure checks. Exclusion defers only executable RPATH eligibility,
not malformed-ELF rejection. Retained material keeps confined ORIGIN-only search;
absolute RPATH/RUNPATH remains rejected. No host-directory existence exception.

Manifest `m20-e5-python-distribution@2` binds profile identity/digest, complete base
membership, selected/support membership, exclusions with typed roles, and the
combined projection digest. Filesystem/root pins and exact bytes remain bound.
Separate v1 models retain old serialization/digests; old evidence is historical,
not reinterpreted or automatically upgraded. No DB migration/history rewrite.

D's **fixed identity namespace**, not an environment builder, mounts exactly the
certified selection. Fully selected subtrees may be read-only bound; every ancestor
of excluded material is split into empty directories and selected child bindings.
No full `lib` bind when exclusions exist. Node-owned private mount descriptors are
bounded and compiled by the pinned native helper into a sealed NUL-argument file.
Bubblewrap's [`--args FD` implementation](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c)
reads those arguments and closes the FD; the fixed fixture still denies inherited
FDs. The descriptor cannot add arbitrary bubblewrap options or executable code.
Additional bounded descriptor/argument/mount-scaffold costs are charged to the existing
E5-B ledger before work (16 MiB conservative temporary/control allowance, 16 MiB
additional cumulative write allowance, 2,050 extra control entries). An insufficient
permit rejects before probes; no authority ceiling is enlarged automatically.
Unrepresentable views fail closed. All thirteen C controls remain unchanged.

E5-E **must instantiate exactly this certified base projection** alongside its
separately verified empty venv. It must use current ownership/authority, fresh
rehashing and exact membership/pin comparison; extra/excluded/changed material is
a projection mismatch, never an automatic repair. `verify_exposure()` supplies
that exact comparison boundary, not an E5-E constructor. Mounting a whole source
`lib` tree or adding excluded GUI/package-manager bytes under another import path
is prohibited. Exact exposure comparison rejects reintroduced site-packages,
pip launchers, ensurepip/wheels, Tcl/Tk or any other excluded entry. No future
constructor may treat the provisioned base as the certified executable view.

## Consequences and limits

Existing reviewed v1 pins must not be reused as v2 pins. Inventory-only prints the
new projection identity; the operator must review/repin the manifest and rebuild/
repin the native helper before a fresh confined provenance check. Distribution
bytes are never modified. Unknown layouts/features fail closed.

This is local runtime integrity, not vendor attestation, arbitrary-code safety,
runtime READY, execution authorization or a defense against a malicious trusted
same-UID operator/root. No candidate was executed to debug static compatibility;
offline native tests exercise only descriptor formatting and simulated controls.
No venv, package install, source/target/Secret/Session or E5-E/F behavior is added.
Production `execute_plan()` remains denied; runtime remains UNAVAILABLE, ready=false.
