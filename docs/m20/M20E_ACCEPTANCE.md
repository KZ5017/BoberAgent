# M20-E acceptance and stop conditions

**Status:** Specified test plan; E1 typed and E2 Core admission tests pass, but no preparation
has run. E3–E9 have not begun. See [slice plan](M20E_IMPLEMENTATION.md).

## Automated acceptance layers

1. **Typed/authority:** current strict V2, VALID validation and current non-DENY D5 are
   required; REQUIRES_APPROVAL needs exact current APPROVED D6. DENY, stale/mismatched
   context, forged/expired permit, wrong Node/provider/Run/plan/source/limits and conflicting
   replay reject before any import/workspace. PlanningAttempt stays terminal.
2. **Transport/import:** same exact raw/manifest refs survive Core→Node; bounded chunks and
   offsets/resume, duplicate/lost ack, corrupted hash/size, conflicting ArtifactRef,
   out-of-order/oversize chunk, disconnect and both-side restart fail safely. No caller path is
   used; imported bytes are not re-uploaded as Node evidence. Existing Node→Core path remains
   independent.
3. **Materialization:** reject absolute/traversal/links/devices/FIFOs/collisions, limits,
   manifest mismatch and hash drift. Do not use unrestricted extraction. Partial trees are
   unavailable; complete source is read-only and exact. No GitHub contact or source rewrite.
4. **Runtime/confinement:** trusted CPython 3.12 and exact version recorded; fresh venv with
   empty external package set and fixed environment. Every closed provider operation uses its
   own argv; no source import, entrypoint, pip/build/install or target network. Tests prove
   absence of subprocess network, host-socket access, out-of-root writes, escaping descendants
   and resource-limit bypass on a supported backend; unsupported backend fails closed.
5. **Lifecycle/evidence:** normal Router→Run→Node→Result→Node outbox→Core path; receipt and
   synchronized manifest match permit/source/Resource. Result-first goes AWAITING_ARTIFACT,
   not COMPLETED. Reopen/replay does not duplicate Runs or mutate immutable history. Node
   restart during staging/venv creation quarantines partials. Current Resource availability
   is separate from historical completion. No secrets or raw paths leak into routine output.
6. **Boundary:** no `execute_plan`, PoC entrypoint, target packet, listener, Session or F
   authorization; D records, acquisition and inspection history unchanged. Architecture tests
   keep Core independent of Node/capability implementations and transport neutral.

Use migration-backed isolated databases and harmless synthetic retained source. Deliberately
inject network/filesystem/process failures and controlled disconnects rather than relying on
timing. E8 must traverse a valid synthetic D7-style A/B/C/D chain, issue a permit, import exact
Artifacts, prepare, sync manifest, reconcile Core completion, reopen and prove identical reuse.
It must also prove a historical D8-like UNSUPPORTED chain cannot obtain any E side effect.

## E9 real Kali, preparation only

Before positive E9, test the proposed rootless confinement backend on the actual intended
Kali Node for every required property, including unavailable-feature fail-closed behavior.
Use one harmless supported fixture with a valid acquisition/inspection/plan/validation/policy
chain and explicit authorized Mission. Verify exact retained bytes, no preparation network or
source execution, Resource/manifest identity, Core Artifact synchronization, restart/reopen
and current availability. This is *preparation-only*, not a PoC run or vulnerability claim.

The retained real CERTCC acquisition `poc-acquisition-2f6a3658a57c42f5ae2252edf1736352`
remains the negative case. Its C2@2/C3@2 D8 admission is `COMPLETED / UNSUPPORTED /
REJECTED_UNSUPPORTED` with **zero ExecutionPlans**. It must receive no PreparationPermit,
Artifact Import, workspace, Resource or preparation Run. Do not reinterpret its source or
re-run it to manufacture a positive case. M20-F remains unstarted; production
`execute_plan()` stays denied through E9.
