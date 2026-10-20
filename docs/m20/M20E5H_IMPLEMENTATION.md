# M20-E5-H — final real Kali E5 acceptance

**M20-E5-H CLOSED / real Core↔Kali acceptance PASSED. M20-E5 CLOSED.**
Recorded from the operator's successful v2 acceptance report on 2026-10-20;
no accepted runtime was opened, mutated or rerun for this documentation closure.
E5-G remains CLOSED on its separately recorded 2026-10-19 configured-host synthetic
acceptance. This slice adds manual acceptance tooling only, not a new provider,
transport, authority, persistence model or acquired-code executor. At this H closure checkpoint,
E6–E9 and M20-F were NOT STARTED. [Subsequent E6 work](M20E6_IMPLEMENTATION.md) is recorded
separately; the acceptance history below is unchanged. M20-E remains OPEN.

## Operator-supplied real Core↔Kali v2 acceptance

The successful **v2** run, not the expired v1 attempt, closes H and E5:

| Retained acceptance identity | Value |
| --- | --- |
| Kali Node runtime | `~/boberagent-runtimes/m20e5h-real-acceptance-v2` |
| WSL Core runtime | `~/boberagent-data/m20e5h-core-acceptance-v2` |
| Node ID | `node-ac6331a1-ecdb-47ef-aa9c-d44dd539b615` |
| ResourceRef | `resource-ad6b7821-af17-439c-a706-95b1adf75499` |
| PreparationPermitRef | `preparation-permit-c89f2cdc72274c7b9e8d78e6d18a1137` |
| CapabilityRunRef | `run-preparation-7a35929b35aa4ccaab136c380601b534` |
| Construction SHA-256 | `74efa984590f4da547d8f1a128a3962978db7c067e3ad53b30183b891ec1ea79` |
| Binding SHA-256 | `bb09639e824737bfa1fd835755a05ded9162b801900810d71780a3d3590a6f09` |

Paths above are operator diagnostics on the respective machines, not logical identity.
No additional refs, hashes or asset pins are inferred beyond the supplied evidence.

Observed acceptance sequence:

1. Fresh real Kali preflight **PASS**: `resource_created=false`, `ready=false`,
   `execution_authorized=false`.
2. Real Core → Router → MCP → Kali preparation **PASS**: fresh verification produced
   **READY / PUBLISHED / VALID**. Acquired source did not execute; no package installation,
   target activity, execution authorization or terminal preparation occurred.
3. Passive `before-restart` report **PASS**: exactly one Resource; retained construction,
   accounting and source verification matched Core evidence.
4. Only the Node process stopped/restarted. The same delegated systemd service/parent,
   persistent runtime, DB, Node identity and configuration were preserved.
5. Core reopen and restart revalidation **PASS**: `core_reopened=true` and
   `historical_replay_did_not_promote=true`. Historical proof remained retained while
   current validity was UNCHECKED; old-ID replay did not silently restore validity.
   A new explicit validation under a new Node boot generation produced fresh evidence
   and restored **READY / PUBLISHED / VALID** on the same ResourceRef, construction and
   binding digests. Cumulative budgets/accounting were retained, not reset.
6. Passive `after-revalidation` report **PASS**: `resource_count=1`, the same ResourceRef,
   `source_verified=true`, `secret_delivery=false`, `target_activity=false`,
   `stage=after-revalidation`.

Throughout successful preparation/revalidation: `execution_authorized=false`,
`acquired_source_executed=false`, `package_installation=false`,
`preparation_terminal=false`, `target_activity=false`; no Secret delivery, execution
Session/listener, acquired-source import or entrypoint execution occurred.

### Historical expired H v1 — preserved failure

The earlier v1 attempt expired during the original **15-minute** preparation-authority
window and correctly failed closed with `CURRENT_PREPARATION_AUTHORITY_REQUIRED`.
It remains failed historical evidence: it was not rewritten as PASS, repaired, renewed
or reused. The accepted v2 used fresh state. E5-A–G acceptance history, including E5-E
v7, E5-F v9/v10 and G's separate configured-host record, remains unchanged.

### Closure authority boundary

This is historical evidence of a prepared/currently valid Resource at acceptance,
not permanent current availability, renewed preparation authority or permission to execute.
**`PREPARED != EXECUTION_READY != EXECUTION_AUTHORIZED`.** E5 produced the Resource
and intermediate runtime evidence only; Core preparation remained nonterminal.
Ordinary E5 evidence Artifacts use the existing synchronization path, but **E6 alone**
owns the final `RuntimePreparationManifest`, normal terminal CapabilityResult/receipt,
final preparation Artifact synchronization completion and Core preparation completion.
Production `execute_plan()` remains denied throughout M20-E. E6–E9 and M20-F remain
NOT STARTED; this closure neither implements nor redesigns them.

## One harness, three acceptance modes

Entry point: `scripts/manual-smoke/m20e5h_acceptance_smoke_test.py`. See the
[exact operator commands](../../scripts/manual-smoke/README.md#m20-e5-h--final-real-corekali-acceptance).
Its two private helper modules contain bounded record I/O and Kali evidence adapters;
they are manual tooling, not new platform APIs.

1. **Kali `--check-config`:** require explicit existing pins/configuration and a fresh
   Node runtime. Compose the actual configured ExecutionNode/Linux backend. Reuse C's
   helper-installation trust check and all thirteen bounded controls, D's static
   inventory/identity validation and rehash, and E's installed environment-helper gate.
   Save persistent Node identity, production configuration, exact interpreter/projection,
   kernel/delegation, all probe outcomes/limits and helper/bwrap/asset hashes. No
   preparation permit, Resource or venv is created. Readiness stays false. Stop the
   preflight Node cleanly before starting the real MCP Node with that same fresh runtime.
2. **WSL `--real-runtime-preparation`:** require the copied typed preflight and exact
   explicit Node ID, existing MCP TLS/bearer conventions and a fresh Core runtime.
   Reuse G's harmless sentinel-bearing authoritative C/D fixture and already reviewed
   E5 budget ceilings; fixture setup ends at D. Actual Core admission → Registry/Router
   → MCP → E3 exact import/reconnect/replay → E4 immutable publication → E5 prepare
   and exact replay → fresh validation and exact replay. Check the preflight's exact
   interpreter/projection/helper/bwrap identities against the returned sealed binding.
   Synchronize ordinary evidence Artifacts using M6, verify their typed content and
   retain the initial checkpoint, complete intermediate runtime response and report.
3. **After operator restart, WSL `--restart-revalidation`:** reopen the same Core DB;
   do not issue a new permit or redispatch. Reuse/reverify the exact E4 receipt. Require
   current UNCHECKED and the original historical proof/construction. Replay the old
   validation ID and require that it does not promote validity. Only a new explicit
   validation ID may restore READY / PUBLISHED / VALID. Require the same Resource,
   binding/construction/environment, a different Node generation/operation/evidence,
   monotonically accumulated usage and a genuine new charge. Sync the new evidence
   Artifact and preserve both proof generations and the UNCHECKED status record.

The operator stops/restarts only the Node process, not its delegated service or parent
cgroup. Identity, DB, runtime directory, tools, configuration and parent binding must
remain identical. All active steps must fit the original fifteen-minute permit and
cumulative budgets. Expiry/staleness is denial, never a reason to edit time or limits.

## Passive paired Node reports, not a fourth preparation phase

After each VALID response, copy its bounded `e5h-first-runtime.json` / `e5h-second.json`
to Kali and run `--node-report` with the same ResourceRef, expected response and explicit
stage. This is companion evidence collection, not another H sub-slice or active operation.

The existing neutral response carries aggregate usage, not the full Node budget ledger
or Resource count. No protocol extension is needed: the local report uses existing Node
read repositories and pure verification functions under SQLite `PRAGMA query_only=ON`.
It never initializes ExecutionNode or invokes service startup recovery. It verifies
exact retained raw/manifest hashes, E4 read-only tree, construction binding and closed
environment inventory; checks exactly one Resource and no Session or terminal Result;
decodes bounded native history to reject source sentinels; and reports all probe outcomes
without raw stdout/stderr or lease-owner tokens. It compares current committed budgets
to the Core-visible evidence, rejects duplicate construction and, after restart,
compares immutable identities, unchanged ceilings and monotonically spent ledger entries
against its first saved snapshot. Reports cannot grant availability or renew authority.

Report files are private, bounded to 2 MiB and exclusively created. Input files must be
regular, no-follow and bounded. No accepted/quarantined directory is adopted or repaired.
Fresh runtime creation is private; existing files/reports are never overwritten. Failed
fresh attempts remain evidence: choose new acceptance state rather than repair/reuse them.
The selected source, paths and command vocabulary cannot be supplied by capability input.

## Evidence package and interpretation

Retain without editing:

- Kali `e5h-preflight.json`: Node/configuration, assets/pins, kernel/delegation,
  interpreter/projection, fourteen bounded C/D probe records, no Resource/readiness.
- Core `e5h-selection.json`, `e5h-first.json`, `e5h-first-runtime.json`,
  `e5h-first-validation-report.json`: exact planning/Mission/preparation/permit/Run,
  raw/manifest/E4, Resource, binding/construction/environment, first validation and
  admitted limits/usage. These JSON files are harness records, not new authority.
- Core `e5h-restart-status.json`, `e5h-second.json`,
  `e5h-post-restart-validation-report.json`: historical proof retained while UNCHECKED,
  new generation/operation/evidence, same identities, no accounting reset.
- Kali `e5h-ledger-before.json`, `e5h-node-before-restart.json`,
  `e5h-node-after-revalidation.json`: one Resource, exact byte verification, complete
  Node ledger/operations and bounded native probe summaries. No database archaeology
  is required of the operator.
- Ordinary synchronized runtime evidence Artifacts remain in the Core Artifact catalog.
  They are not an E6 final manifest or terminal CapabilityResult.

Active memory controls intentionally induce a bounded child-cgroup OOM once per full
thirteen-control check; Python identity/construction/verifier operations require zero OOM.
Preserve any systemd OOM observations, exit statuses and usage; do not infer failure of
the pytest/Node process or successful confinement from a unit-level message alone.
Use the per-probe outcomes/limits and final process result. The service's outer
MemoryMax does not replace child limits. Disposable loopback/FD canaries used by C
are confinement controls, not target activity or an execution Session/listener.

## Stop boundary and historical evidence

Successful preparation/audit stages report `execution_authorized=false`,
`preparation_terminal=false`, `acquired_source_executed=false`; preflight reports no
Resource/readiness. Failure records never claim unproven non-execution or lifecycle
state: they expose a bounded reason and no execution authorization. No acquired import/entrypoint, package manager,
installation, Secret resolution/delivery, target/public-network/DNS dependency,
Session/listener, generic ProcessService/execute_plan call or E6 completion is added.
Core preparation stays DISPATCHED and the preparation CapabilityRun stays QUEUED.
E6 alone owns the final manifest/terminal Result/Core reconciliation.

No production code, helper bytes, dependencies, schema or migration changed. Existing
Core/Node migration heads and all admission/Router/transport/recovery logic are reused.
Previously accepted E5-E v7, E5-F v9/v10 and E5-G records/runtimes are untouched and not
working inputs. Host paths are operator diagnostics, never cross-boundary identities.
No host provisioning, package installation, chmod repair, controller delegation or
service management is performed. Missing controls produce bounded failure, not fallback.

## Historical implementation verification versus real closure

Focused tests cover parser/config/error handling, private/exclusive/bounded records,
absence of startup recovery during passive audit, denial without a real restart or
after expiry, changed-source rejection without mutation, and the full manual Core
driver against local MCP with **explicit synthetic enforcement fixtures**. They do
not establish Linux enforcement or close H. Existing F/G and architecture guards
remain required. The manual script is outside normal pytest collection.

Implementation validation passed:

- focused H/F/G and architecture regressions: **85 passed, 1 skipped**;
- full repository suite: **1,676 passed, 9 skipped**, one existing duplicate-ZIP
  fixture warning; no configured-host positive test was substituted for real H;
- Ruff check and formatting (574 files), canonical strict mypy (519 source files),
  separate strict mypy for all three new manual modules, lock/sync, standalone
  `--help`, and `git diff --check`: PASS. Lockfile/dependencies are unchanged.

Local MCP/socket fixtures required the approved sandbox network-permission escalation;
no Kali, public target or remote acceptance was contacted by these checks.

Those portable checks established implementation readiness, not real-host acceptance.
The separately supplied real v2 evidence above now closes **M20-E5-H and M20-E5**.
The historical implementation check counts are preserved, not presented as newly run
closure checks. M20-E remains OPEN; E6–E9 and M20-F remain NOT STARTED.

## Documentation-only closure verification (2026-10-20)

- Architecture suite: **70 passed**.
- Ruff check, formatting (574 files), strict mypy (519 source files), exact supplied
  acceptance-ref/hash checks, stale-status scan, Markdown-only diff scope and
  `git diff --check`: PASS.
- No production code, tests, dependencies, migrations or helper bytes changed.
  No real smoke, runtime or retained evidence was accessed/rerun. The full repository
  suite was not repeated for this Markdown-only closure; the earlier implementation
  suite counts above remain explicitly historical.
