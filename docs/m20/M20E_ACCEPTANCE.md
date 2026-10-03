# M20-E acceptance and stop conditions

**Status:** E1–E4 COMPLETE; real Core↔Kali E3 and E4 acceptance PASSED.
E5–E9 have not begun.
**M20-E4 CLOSED. M20-E remains OPEN. M20-E5 has not begun.**
M20-F has not begun. See [slice plan](M20E_IMPLEMENTATION.md).

E4's synthetic E2→E3→E4 test uses a controlled confinement proof and therefore does not
substitute for the real Kali bubblewrap check. The Linux integration test skips explicitly
when bubblewrap or requisite kernel/socket privileges are unavailable. Operator-run E4
`--check-config` must prove the real Node's imported inputs and trusted confinement probe;
`--real-materialization` is a separate opt-in action on a harmless synthetic ZIP within
the E2 permit window. The operator completed both modes on Kali, including restart/reuse.

The first real Kali E4 `--check-config` failed closed with `CONFINEMENT_UNAVAILABLE` after
E3 succeeded; no source was materialized. Manual reproduction identified usrmerge
`/bin`, `/lib` and `/lib64` links to `/usr` as the omitted ELF-loader topology: a
`--ro-bind /usr /usr`-only probe could not start `/usr/bin/python3` because its loader
resolves through `/lib64/ld-linux-x86-64.so.2`. The Node backend now reconstructs only
allowlisted compatibility links and reports bounded, differentiated confinement failure
codes. It did **not** add a host-root bind. The subsequent real Kali CHECK and explicit
MATERIALIZE passed as recorded below.

The manual E3 script has distinct `--check-config` (no import bytes) and explicit
`--real-artifact-import` modes. It uses a harmless synthetic supported D→E2 chain, not the
retained CERTCC D8 UNSUPPORTED case. Success verifies the two exact ArtifactRefs, hashes and
sizes, reconnect/replay, and leaves the preparation attempt DISPATCHED—not COMPLETED.

## E3 real CoreKali acceptance (PASSED)

The operator ran the opt-in smoke against Node
`node-38195224-06e1-480c-a7f9-fdacd26861d6` and Core runtime
`/home/bober/boberagent-data/m20e3-core-smoke-final`. The durable identities were
Preparation `preparation-7a156e8a25c647b591589689a0d374c3` and Run
`run-preparation-287e2192955a4caf9b92c6fffe55ffda`.

| Exact imported Artifact | SHA-256 | Size |
| --- | --- | ---: |
| `artifact-inspection-raw` | `1b79db425268bcc0d6234358220d9393a178af036065f729d4ab54792fb9c756` | 442 bytes |
| `artifact-inspection-manifest` | `6bb6181e8808aab90a44060012bdde5f98b0f8a5612bf71139b9ed75f9ce6544` | 518 bytes |

The no-byte preflight passed with current E2 authority and available Core bytes. First
real import verified both Artifacts and reused identities across reconnect/replay. The Kali
Node was restarted with the **same persistent runtime** and retained its Node ID; an
identical real import against the **same Core runtime** again verified both Artifacts and
reused identities. No extraction, workspace, Resource, venv, process or PoC execution
occurred. E3 is accepted as opaque import only, not preparation completion or execution
authorization. The 15-minute E2 permit window remains mandatory; a replay after expiry
correctly fails closed and is not an Artifact replay defect.

## E4 real Core↔Kali acceptance (PASSED)

The operator used Node `node-8207f75c-8905-4fc4-ab96-863e52d9d51a` and Core runtime
`/home/bober/boberagent-data/m20e4-core-smoke-final`. The accepted Preparation was
`preparation-128f07e383204665be425c85da36c6f6`; its Run was
`run-preparation-5e05d913809a45e7885294c2753ec44a`.

| Exact E3 imported input | SHA-256 | Size |
| --- | --- | ---: |
| `artifact-inspection-raw` | `1b79db425268bcc0d6234358220d9393a178af036065f729d4ab54792fb9c756` | 442 bytes |
| `artifact-inspection-manifest` | `6bb6181e8808aab90a44060012bdde5f98b0f8a5612bf71139b9ed75f9ce6544` | 518 bytes |

E3 CHECK imported zero bytes; the real E3 import then verified both exact Artifacts, and
reconnect/replay reused their identities. The production E4 CHECK passed with
`linux-bubblewrap` / `bubblewrap 0.11.0`, proving the reported E4 subset:
`NO_SUBPROCESS_NETWORK`, `NO_INHERITED_SOCKETS`, `NO_HOST_CONTROL_SOCKETS`, and
`NO_ARBITRARY_HOST_FILESYSTEM`. It confirmed the imported inputs and trusted confinement
probe **without creating a workspace**.

The explicit real MATERIALIZE published logical materialization
`materialization:93a92832d388166dc92fd53d069fef96d6aaf615d1b57f2562de60aae8683895`:
one file, 336 materialized bytes, tree SHA-256
`3468149cb07e1a4d3058f6a5326758b2b4fa215e53d1c93e784cb4854228a59b`, state
`PUBLISHED`. The harness reported exact retained source publication and no runtime, venv,
or PoC execution.

The Kali Node was stopped and restarted with the **same persistent runtime**, retaining
the same Node ID. While the PreparationPermit remained currently applicable, the operator
repeated the identical real MATERIALIZE command against the **same Core runtime**. The
PreparationRef, RunRef, materialization ID, file/byte counts, tree hash and `PUBLISHED`
state were unchanged. This is real reopen/revalidation and exact reuse, not a second
materialization or execution grant.

E4 proves bounded exact source materialization, manifest reconciliation, read-only
publication, restart revalidation, and only the four reported bubblewrap features. It
does **not** prove a prepared Python runtime/venv, installation, acquired-source import
or execution, arbitrary subprocess execution, process-count or memory enforcement, hard
storage enforcement for PoC execution, full acquired-process descendant containment,
target network, or execution authorization. E5 must fail closed for any runtime profile
requiring properties not yet proven. Production `execute_plan()` remains denied.

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
