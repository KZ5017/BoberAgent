# ADR 0009: Core Secrets and run-scoped execution grants

## Status

Accepted for Milestone 16.

## Context

Core must own canonical Secret and Credential state, while a capability running on an Execution
Node sometimes needs the actual bytes. Durable orchestration should carry references, and the Node
must not gain an enumerable persistent replica. The current MCP execution path is Core-initiated;
there is no transport-neutral reverse Core service call during a running capability.

Raw evidence is a separate concern. An Artifact may legitimately contain a discovered password and
must remain byte-for-byte evidence rather than being rewritten by Secret normalization.

## Decision

Core stores a Mission-owned Secret under a stable `SecretRef` and exposes metadata separately from
explicit reveal. A Credential is Core-owned authentication context with safe account metadata and
named `SecretRef` bindings. The `credential.candidate` reducer validates Mission ownership,
materializes a deterministic `CredentialRef`, preserves Observation/Artifact provenance, and
appends one replay-safe `credential.available` Core event.

Capability resolution uses an explicit run-scoped grant in the neutral invocation projection.
Core validates the target `CapabilityRun` and Secret Mission, records non-sensitive grant audit
metadata, and projects only the selected refs and bytes. The Node keeps those grants in the
Execution Context lifetime, exposes them through `ctx.secrets.resolve()`, and does not persist
them. Protocol version 1.4 identifies this projection change. Invocation fingerprints include the
stable SecretRefs and authorization purpose, but not a value-derived hash, avoiding a durable
offline guessing oracle.

Workflow steps may declare explicit CredentialRefs and direct SecretRefs. Only those Credential
snapshots and their bound Secrets are projected. This declaration is authorization data, not
plaintext and not an entity enumeration API.

Core SQLite stores the bytes as a BLOB. SQLAlchemy hides parameter values even with SQL echo
enabled. This milestone does not claim encryption at rest: database file permissions, volume
encryption, backups, and host access remain deployment responsibilities. Vault/KMS integration,
rotation, and multi-user RBAC are deliberately deferred.

Explicit local CLI `reveal` is the operator authorization boundary in the current single-operator
bootstrap. Ordinary list/show/status and JSON models never contain the value. A resolved UTF-8
value is registered with the Run-local capability logger and redacted from subsequent messages and
structured fields. Managed process arguments are not logged or persisted. This is defense in depth,
not a claim that arbitrary third-party tools cannot expose a supplied value in their own output;
such output remains evidence and follows Artifact handling.

## Consequences

- A capability can resolve explicitly granted values across in-memory or MCP transport without
  importing Core or making MCP a domain abstraction.
- Core and Node persistence do not contain duplicate execution-time copies.
- Capability-side creation through `ctx.secrets.store()` remains unavailable until a dedicated,
  durable Node-to-Core secret-deposit protocol exists. Core application services are the canonical
  creation path in M16.
- `credential.validation`, authentication suites, spraying, Vault/KMS, and general policy/RBAC are
  not part of this decision.
