# M20-v1 scope and support matrix

This matrix classifies *execution support*, not vulnerability truth, target authorization, or
policy approval. `AUTOMATIC` means eligible **only if every common gate below passes**.
`ASSISTED` means a concrete prerequisite or bounded operator choice must be resolved; it never
overrides a denied policy. `UNSUPPORTED` means inspection/explanation may continue but automatic
M20-v1 execution stops. Classification is intended to become a typed, persisted outcome with
machine-readable reason codes, not an opaque risk score.

## Common gates

- One named Mission and one selected, in-scope Asset/Service. All target and external network
  destinations are explicit; no expansion from PoC source or redirects without validation.
- Acquired source is pinned and hashed; the exact inspected bytes are used in preparation and
  execution. Entry point, runtime, dependencies, parameters, effects, cleanup, and output meaning
  are understood. Unknown risk is not silently interpreted as safe.
- Core deterministic validation and policy authorization precede Node preparation; Node must
  enforce the constraints it can observe. A complete, enforceable isolation profile is required.
  A Python venv alone is **not** confinement.
- The plan has a finite timeout, resource/output limits and cancellation; output is captured as
  evidence. No generic shell string, README instructions, hidden source rewrite, or model tool
  call is an execution authority.

| PoC class / requirement | M20-v1 classification | Reason or prerequisite |
| --- | --- | --- |
| Python, source-visible, one target, user-space, non-interactive | AUTOMATIC | Initial supported runtime if all common gates pass |
| Simple HTTP PoC | AUTOMATIC | Only when it fits the initial Python class and bounded destination/effect rules; HTTP alone grants no trust |
| Read-only checker or validator | AUTOMATIC | Explicit target and verifiable/interpretably negative output still required |
| Single-target authentication-bypass or remote-service/RCE reproduction | AUTOMATIC | Only if it fits the Python class, target effects are bounded/declared, and distinct Core policy authorizes them; otherwise ASSISTED or UNSUPPORTED |
| Shell script | ASSISTED | Shell semantics and command boundaries need explicit inspection/policy; no automatic shell-string adapter |
| Dependency installation | ASSISTED | Exact pinned package/source and install side effects require review; arbitrary README `pip install` is not authorized |
| Compiled user-space source | ASSISTED | Explicit build chain, source provenance, artifacts and side effects need a later reviewed adapter |
| Credential-required PoC | ASSISTED | Mission-owned `CredentialRef`/`SecretRef` grant and declared purpose; no plaintext in plans |
| Listener-required PoC | ASSISTED | Existing listener Resource and expected callback binding must be explicitly provisioned/authorized |
| Interactive shell PoC | ASSISTED | Existing Session and durable Interaction semantics; no private stdin or unattended interaction |
| Browser/session-based multi-step web PoC | ASSISTED | Explicit Session lease and steps; not an automatic Python single-process case |
| Multiple plausible entrypoints/manual parameter | ASSISTED | Operator chooses one bounded option through Interaction; no hidden model guess |
| Explicit build step requiring approval | ASSISTED | Preparation is separately authorized; approval is not an InteractionRequest substitute |
| Source modification required | UNSUPPORTED | No automatic source rewrite/logic repair; operator may review a new immutable Artifact in a later design |
| Target-side local privilege escalation | UNSUPPORTED | No initial target-side runtime or privilege adapter; deferred, not declared impossible forever |
| Kernel/driver exploit | UNSUPPORTED | Privileged, system-wide impact outside M20-v1 runtime |
| Binary-only PoC | UNSUPPORTED | No inspectable source or sufficient behavior bound |
| Obfuscated source | UNSUPPORTED | Side effects and entrypoint cannot be reliably classified |
| Root/admin requirement | UNSUPPORTED | No automatic privileged attacker- or target-side execution |
| Persistent/system configuration change | UNSUPPORTED | Persistent effects and cleanup beyond the initial policy/runtime envelope |
| Firewall/security-control modification | UNSUPPORTED | High-impact side effect; no automatic path |
| Destructive exploit | UNSUPPORTED | Explicitly outside automatic M20-v1 safety boundary |
| Self-modifying installer or unknown system-wide effect | UNSUPPORTED | Inspected bytes/behavior cannot remain bounded |
| Multi-host, mass or worm-like execution | UNSUPPORTED | Violates single-target scope and no-propagation invariant |
| Unexpected external destination or uncontrolled target selection | UNSUPPORTED | Destination/scope cannot be validated; reject before execution |

`ASSISTED` is not a blanket promise that an operator answer makes execution automatic. If the
missing prerequisite requires a new runtime class, unresolved policy approval, or privileges,
the outcome remains blocked or `UNSUPPORTED` for v1. A classification record should contain the
decisive facts, reason codes, source Artifact/revision, reviewer/decision provenance if any, and
the exact profile version used; repeated inspection must not silently change a prior decision.

**OPEN DECISION (M20-C/D ADR):** final reason-code vocabulary and whether a reviewed shell/build
adapter is delivered within M20 or remains a documented assisted stop. The initial `AUTOMATIC`
class does not depend on that choice.
