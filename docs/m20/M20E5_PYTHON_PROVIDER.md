# M20-E5 trusted Python provider

**E5-D CLOSED; E5-E implemented offline, real construction acceptance required; E5-F–H not started.** Parent: [E5 architecture](M20E5_ARCHITECTURE.md).
The exact closed EnvBuilder, bounded export/publisher and unready lifecycle are documented
in [E5-E implementation](M20E5E_IMPLEMENTATION.md). These are not E5-F promotion or dispatch.
This is closed preparation of trusted runtime infrastructure, not execution of the plan.

## Interpreter admission and provenance

The approved first source is an operator-preprovisioned uv-managed CPython 3.12 Linux
x86_64 distribution with an explicit absolute root and explicit system-library closure
root. The logical family is `python-runtime-3.12`; backend tools use the Tool Registry.
Neither a uv pathname nor generic availability/version probing proves provenance. No uv
invocation, PATH lookup, active venv, pyenv, installer or system/3.13 fallback. An absent
approved distribution is RUNTIME_UNAVAILABLE. This operator-approved refinement is recorded
in ADR 0021 and [E5-D implementation](M20E5D_IMPLEMENTATION.md).

Before invocation, inspect the path/components without following unapproved links: regular
executable, root or Node-user ownership, no group/other-writable material or parent.
Reject a symlinked interpreter entry; preserve only E4's explicitly
validated system compatibility topology. Pin executable bytes/stat identity before launch
and recheck afterwards. Root/admin compromise and malicious replacement by the trusted
operator are outside this local trust model; detect ordinary package/layout drift and fail.

The approved runtime closure includes the executable, loader/shared-library dependencies,
libpython if used, selected stdlib/extensions and venv templates. It is the explicit
non-GUI `m20-e5-python-runtime-profile@1` projection, not the entire provisioned base.
[ADR 0022](../adr/0022-m20-e5-trusted-python-runtime-projection.md) excludes the structurally
identified Tkinter/Tcl/Tk and package-manager features while preserving trust/hash
checks over excluded base bytes. The full site-packages and ensurepip namespaces,
bundled wheels and structurally identified dependent console launchers are absent.
Selected material still rejects absolute RPATH/RUNPATH. Record a deterministic
bounded inventory fingerprint, not just the executable hash. Host third-party package trees,
user files and startup customizations are excluded from the runtime view. Do not call `ldd`
on acquired bytes or interpret source to discover this closure. The approved host layout is
provider configuration and must be verifiable; an unexpected layout is unsupported.

Closed **confined** interpreter inspection reports CPython implementation, exact 3.12 patch
version, architecture/platform, ABI/SOABI/cache tag, executable identity, stdlib locations
and base prefixes. Reject a virtualenv base, wrong family/platform, missing stdlib/venv,
unapproved import paths or ambiguous provenance. Build identity binds the full runtime
fingerprint. Paths/stat identities stay Node-private; evidence uses logical layout plus
hashes and typed version/ABI facts. An OS Python/library update invalidates current reuse;
no upgrade-in-place of an existing Resource. PROVENANCE_VERIFIED is historical interpreter
evidence, not a constructed/VERIFIED environment, current VALID or READY.

The current Tool Registry's optional `version_args` probe is **not** this inspection. Do
not configure an E5 arbitrary version probe or run it before confinement; Node provider
does the fixed inspection after backend admission, retaining the selected registry key.
E4's closed `/usr/bin/python3` isolation probe remains unchanged and is not E5 provenance.

## Fresh venv, not source validation

E5-D certifies manifest `m20-e5-python-distribution@2` and its exact projection digest;
**E5-E must instantiate exactly that certified base projection**, not mount the complete
operator `lib` tree. Fresh authority/rehashing and exact selected-entry comparison are
mandatory; extra/excluded/missing bytes fail closed. The D fixed identity namespace
already uses the certified read-only view. E5-E's fixed constructor now uses that same view;
no general construction/argv API is implemented.
Fresh profile `@1` evidence binds both unsupported features; historical Tk-only
evidence is readable but cannot authorize current exposure. Reintroducing
site-packages, pip wrappers, ensurepip or Tcl/Tk fails exact membership checks.
The venv stdlib remains available, not its optional pip bootstrap.

The baseline is a fresh environment constructed with semantics equivalent to:

```text
<approved interpreter> -I -S -B -m venv --without-pip --copies /work/venv
```

This is a **provider-built vector**, not a caller API or a command to run now. Only one
new empty destination is allowed. No `--clear`, upgrade, system-site-packages, symlinks-to-host,
upgrade-deps, prompts from source, activation, requirements, wheels, build backend or install.
CPython's `--without-pip` avoids its default pip bootstrap; `--copies` requests copied
executables. A venv still depends on its base runtime and is not generally relocatable.
See [Python 3.12 venv](https://docs.python.org/3.12/library/venv.html).

For explicit write accounting, v1 uses a fixed provider-owned helper
with `venv.EnvBuilder(system_site_packages=False, with_pip=False, symlinks=False,
upgrade=False, upgrade_deps=False)` instead of launching that CLI vector directly.
It must produce the same verified
empty environment and instrument **every** construction write before issuing it. No plugin
hooks, subclass or post-setup script from the request/source. Pin/test the trusted helper and
stdlib venv implementation; an unsupported implementation with unaccounted writes is denied.
This is bounded trusted construction, not an arbitrary-Python endpoint.

E5-E executes the exact provider helper bytes only from an explicitly installed trusted
asset beside the pinned native helper: `environment-<helper_sha256>.py`. The package/source
file identifies reviewed bytes but is never the child execution path. Operator installation
uses explicit 0444 file / 0755 directory modes and trusted non-writable ancestors; no source
checkout chmod or automatic production installation. Create/verify recheck bounded file
bytes, SHA, no-follow trust and parent identity before/after work. Existing immutable
`helper_sha256` evidence binds the asset; no extra domain identity or authority is created.

Verify `pyvenv.cfg`, copied executable hash, entire bounded tree and package locations.
`include-system-site-packages` must be false, external installed set empty, no pip executables,
package metadata, wheel seed, `.pth`, `sitecustomize` or `usercustomize` introduced into the
environment. Finding any of these fails/quarantines; do not silently remove contamination
and claim an originally clean build. Expected stdlib-generated activation scripts may be
retained as inert inventory but are never sourced. Permit only exact provider-known relative
in-tree links (for example `lib64 -> lib`); reject unexpected/external links, devices and sockets.
The Python 3.12 [venv implementation](https://raw.githubusercontent.com/python/cpython/3.12/Lib/venv/__init__.py)
is the behavior reference, not an acquired setup script.

`-I` alone does not suppress all system startup customization. Use `-I -S -B` for base
inspection/construction; no ambient `PYTHON*`, current-source directory or user site.
Python 3.12's site processing participates in venv prefix setup: do not reject a valid venv
merely because a `-S` probe reports base prefixes. First statically verify the environment
and exclude startup hooks from every visible import location; then a fixed verification
probe using the venv interpreter with `-I -B` may check `prefix != base_prefix`, exact
expected prefixes and import path. Only trusted stdlib is imported. This accounts for
[Python site startup](https://docs.python.org/3.12/library/site.html) and
[isolated-mode semantics](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I).

No PoC source is mounted during inspect/create/verify. In particular, do not probe imports,
compile source, run `--help`, execute a setup file or infer success from the entrypoint.
Use authoritative C2/C3/D4 references and the admitted empty external-dependency requirement;
recheck the spec/profile/plan/source bindings. E5 adds **mechanical** integrity validation,
not another semantic inspector. "Apparent stdlib-only" remains conditional: dynamic imports
or actual runtime requirements may still fail in future F and must never trigger an installer.

## Namespace filesystem and durable publication

| Namespace area | Construction | After publication / future use |
| --- | --- | --- |
| Minimal root, approved interpreter/stdlib/loader | Read-only, fixed trusted view; no whole-host root or HOME | Same pinned runtime view required on revalidation |
| `/work/venv` | New tree on size/inode-bounded private scratch | Same namespace path mounted read-only from Resource storage |
| `/work/tmp`, `/work/home` | Private bounded scratch, initially empty | Discarded; never operator HOME |
| `/source` | Absent from Python construction; read-only synthetic mount only for control probe | E4 source referenced logically; any future source mount must be read-only |
| `/proc`, minimal `/dev` | Private PID view and minimal devices; no host fds/control sockets | No writable disk device, host `/sys`, cgroup control or `/run` |
| Future execution working area | Does not exist | F owns fresh allocation under separate constraints |

All writable mounts are enumerated and capped; the namespace root is read-only after setup.
No writable host-directory bind for the child, including temp, output or Node spool. No
unbounded `/dev/shm`; omit it or charge a separately capped mount. No host package/user cache.
Preserve accepted E4 usrmerge link validation rather than binding `/` as a convenience.

Construct inside bounded tmpfs, stop construction descendants, verify, then export only the
closed validated environment inventory through a bounded channel to the trusted Node publisher.
The publisher uses exclusive no-follow confined file creation, enforced byte/file budgets,
fsync and atomic rename into a Resource-owned managed workspace. It does not unpack arbitrary
source or accept an archive/host path supplied by a caller. Verify the published tree again
under a **read-only** mount before READY. Crashes between publish and commit quarantine.

The namespace venv path stays `/work/venv` for construction, published verification and later
revalidation. Changing host backing storage does not change the path seen by Python or its
generated configuration. Do not relocate a venv and patch config/shebangs to hide drift.
Exact layout, link and copied-interpreter behavior must be tested on admitted CPython 3.12;
if it cannot meet this invariant, reject rather than claim portability.

## Fixed environment, tools and non-network guarantee

Start from an empty environment, then set only provider constants: fixed PATH for approved
runtime tools, `LANG`/`LC_ALL`, `HOME=/work/home`, `TMPDIR=/work/tmp`; pass Python isolation
flags explicitly. Set PWD from the trusted cwd, not the caller. No `VIRTUAL_ENV` activation,
PYTHONPATH, LD_PRELOAD, ambient LD_LIBRARY_PATH, proxies, package configuration, MCP bearer,
SSH_AUTH_SOCK, GitHub/cloud tokens or credential environment inheritance. Close all fds
except explicitly bounded stdio/control channels; no socket fd is passed.
The E5-D fixed identity sets only provider-owned `LD_LIBRARY_PATH=/runtime/lib:/support`
to the fully pinned read-only closure; it does not inherit a caller value.

Network namespace has no host interfaces/routes, no resolver files and no mounted host
Unix sockets; additional namespace creation/capability escape is denied. Test loopback,
outbound and host-control access negatively with controlled fixtures. Fixed venv construction
has no network requirement and no package operation; failure never enables host networking.
Core↔Node transport remains outside this sandbox and is not child network authority.
No Secret grant/resolution, target, listener, Session or Reasoner.

Tool Registry owns configured identity for Python and backend binaries. Backend owns the
fixed bwrap arguments, permitted helper identities and cgroup syscalls/files; provider owns
only the fixed Python operations. `prlimit` is optional diagnostic/defense-in-depth, never
the authority for aggregate limits. systemd may supply an operator-delegated subtree, but
no payload sees D-Bus or systemd-run, and no package manager/helper is discovered from PATH.
