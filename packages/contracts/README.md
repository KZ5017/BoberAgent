# boberagent-contracts

Transport-independent, machine-readable models for BoberAgent Capability Contract v1. The package
contains only platform language: logical references, capability metadata, invocations, lifecycle
records, results, evidence descriptors, interactions, checkpoints, events, and execution plans.

Import common models from the public package root:

```python
from boberagent_contracts import CapabilityInvocation, CapabilityRunRef, MissionRef
```

Models reject unknown fields and support Pydantic validation, JSON round trips, and JSON Schema
generation. Domain references are stable logical values; they do not perform lookups. Contract
models never expose database, transport, SDK, or runtime implementation objects.

Regenerate the committed Contract v1 schema bundle from the repository root with:

```shell
uv run boberagent-contract-schema packages/contracts/schemas/contract-v1.schema.json
```

The normative semantics remain defined by `docs/02_CAPABILITY_CONTRACT.md`.

Milestone 15's durable human-interaction subset supports immutable confirmation, bounded text, and
single-choice requests. Each request is correlated to one Mission and Capability Run and is
validated against its structured response. This is non-secret input: capability authors must not
ask operators to enter credentials or other sensitive material through these ordinary fields.
