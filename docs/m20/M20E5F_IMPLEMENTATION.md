# M20-E5-F — Fresh runtime revalidation and intermediate pump

**COMPLETE; operator-supplied real Core↔Kali v9/v10 acceptance PASSED.** E5-E is accepted on
the [operator-supplied v7 record](M20E5E_IMPLEMENTATION.md#operator-supplied-real-kali-v7-acceptance).
That runtime remains untouched. [E5-G](M20E5G_IMPLEMENTATION.md) is CLOSED on
operator real Kali configured-host positive acceptance (2026-10-19).
E5-H CLOSED on separate real Core↔Kali v2 acceptance; E5 CLOSED. At that checkpoint E6–E9
and M20-F were NOT STARTED; [subsequent E6 work](M20E6_IMPLEMENTATION.md) is separate.
M20-E stays OPEN.

## Operator-supplied real v9/v10 acceptance

Recorded from the operator's report, without opening, changing, reusing or rerunning
the accepted Node v9 or Core v10 runtime. Historical failures and E5-E v7 evidence
remain untouched.

| Retained identity | Exact value |
| --- | --- |
| Node runtime | `~/boberagent-runtimes/m20e5f-real-acceptance-v9` |
| Core runtime | `~/boberagent-data/m20e5f-core-acceptance-v10` |
| Node | `node-6202a4f9-9088-46db-bad8-648be5a37218` |
| Preparation | `preparation-8aba221120b84095b55a4a9b637c6953` |
| Run | `run-preparation-4a13d3bed48644aeb891009498dac8bf` |
| Permit | `preparation-permit-6447d15fc3d849da9034a4148a8f8d39` |
| Resource | `resource-13f75c06-8a65-4fe8-87b8-64584896e587` |
| Binding SHA-256 | `f1acdf4034f79450abcb964b66aacce050c23cfe25fdf58582132ee92fd21739` |
| Construction SHA-256 | `b09d84c414acecd8f4c2876f3f9fbc7966caab4e0bee837a0bce6becf84b3baa` |
| Initial fresh evidence | `5522ae51bdb37b18871401b7695f286c4239ce5f5e8b28f7cb4379d9a3f733ec` |
| Initial evidence Artifact | `artifact-8d1e94c5-aa6a-4373-9f19-002075ac2688` |
| Post-restart fresh evidence | `bea84fdf1b63080b2da818bf4025a840e03eb21034acfb730011ea8ba71f2fec` |
| Post-restart evidence Artifact | `artifact-f98df0be-5b40-4b99-a547-9a4ac48f956d` |

Initial revalidation reached READY / PUBLISHED / VALID. Exact acknowledgement replay
preserved Resource, binding, construction, operation and evidence. Restart under the
same persistent Node identity retained READY / PUBLISHED history but reset current
validity to UNCHECKED. A new explicit attempt created a new operation and fresh proof,
restoring VALID on the same Resource/binding/construction. Historical proof was not
treated as current validity. Throughout: execution_authorized=false,
preparation_terminal=false, acquired_source_executed=false. This accepts F, not E6
completion, execution permission or E5-H's broader acceptance.

## Boundary and call flow

The operator confirmed the E5/E6 distinction: Core current admission and Router → neutral
typed exchange → authenticated Node provider → intermediate response and ordinary evidence
Artifact. **No terminal CapabilityResult, final preparation manifest, Core completion or
execution authorization.** The existing preparation Run stays QUEUED on Node and preparation
stays DISPATCHED in Core. Production execute_plan() remains denied.

`CorePythonRuntimeService.exchange()` composes existing preparation dispatch, refreshes Node
registration, validates current D applicability, explicit provider/version, same queued Run
and E4 receipt pins, and rechecks applicability after delivery. Node independently checks
authenticated principal, exact admitted permit/Mission/plan/Run/Node/actions/time and immutable
Resource/request binding. No Core interpreter/helper/storage paths exist.

Preparation-runtime-v1 gains optional logical `attempt_id` and bounded progress/construction
digest. Legacy absent-attempt message hashes remain unchanged; active production requests
require an attempt ID. The same ID denotes acknowledgement replay; a new ID is required for
new explicit revalidation. This is correlation, not authority. PREPARE_RUNTIME delegates
to existing D inspect/E construction on the one Resource; retained construction is passive
reuse. RUNTIME_STATUS is passive. REVALIDATE_RUNTIME performs fresh work. CHECK_RUNTIME and
RELEASE_RUNTIME remain explicitly unsupported by this pump; Node safety cleanup is unchanged.

In-memory and MCP implement the same exchange; MCP only carries JSON/authenticated identity.
Node tasks survive disconnect. Exclusive claims precede acceptance; restart interrupts active
ownership rather than automatically continuing/rebuilding. Explicit Node JSON configuration
selects pinned distribution/confinement assets; no per-request code/path/config authority.

## Fresh proof and promotion

Acquire exclusive generation and reserve remaining budgets before active work. Verify retained
source Artifact hashes and exact read-only E4 tree without extraction. Verify E5-E inventory
(no extra files/packages/.pth/hooks/links), ownership/modes/ancestor trust and construction.
Re-inventory D's projection and compare helper/backend pins. Run all thirteen C controls and
the fixed read-only E verifier; require current Node generation, version/ABI/base-prefix/import
paths/isolation, empty packages, zero OOM/pids events, bounded output/time/memory and empty
descendants. Repeat source/distribution/environment checks before committing evidence.

Only the trusted verifier executes; source is absent from its namespace. No rebuild, package
manager/install/network/Secret/Session/PoC launch. Native and standalone Python helper bytes
are unchanged: **no repin/recompile required**.

Conservative reservations: temporary 160 MiB, writes control allowance + 128 MiB + 256 KiB,
entries 13 × 65 + 2050 + 8 (one verifier, not E's two operations), depth 4,
processes 11, memory 520 MiB, process envelope 38 s,
total 250 s, output 14 × 4096 B. Fixed E @2 limits and C controls are unchanged. Write allowance
is conservative accounting, not a claim to rewrite the environment. Elapsed/output are measured;
unknown failed work stays fully charged. Permits/budgets are never enlarged or reset.

Seal bounded PythonRuntimeEvidence-v1 and ordinary spool Artifact; persist immutable full
control/verification proof and digest; commit completed ownership and availability atomically.
Identity/binding/construction remain unchanged. The guarded transition is
**CREATING / VERIFYING / UNCHECKED → READY / PUBLISHED / VALID**. READY is prepared-runtime
availability only, not generic acquisition/argv execution or execution authorization.

## Persistence and recovery

Forward Node `0012_python_revalidation` follows 0011; no Core migration or new dependency.
It adds immutable python_runtime_revalidations and checked-time/boot/proof pointer. SQLite
guards deny READY without construction/proof and VALID without completed current-generation
ownership. Immutable reservation and VERIFYING guards remain. Upgrades preserve history/FKs.

Restart clears validity to UNCHECKED without rewriting READY history or construction.
Passive history/replay cannot promote. New validation requires current authority/fresh controls.
Replay cannot duplicate Resource/build/charges. Drift, interruption, expiry, exhausted budgets
and failed controls fail closed with bounded typed diagnostics; no repair/chmod/new permit/fallback.

## Acceptance

Portable tests exercise real Core admission/Router/neutral serialization with synthetic
proofs, promotion, replay, disconnect, restart, drift and migration guards. They are not Linux
enforcement attestation. Existing C/D/E/native tests remain required. Manual F uses a fresh
E5-budget E3 import → E4 → E5-E construction/passive replay → F → restart/status UNCHECKED →
new F validation, with ordinary evidence sync only. See scripts/manual-smoke/README.md.

Real Kali F acceptance passed as recorded above. E5-G's configured-host synthetic vertical
subsequently passed and is CLOSED. [E5-H's separate real v2 acceptance](M20E5H_IMPLEMENTATION.md)
subsequently closed H and E5; it is not inferred from F/G. The earlier H v1 expiry
remains failed historical evidence.
