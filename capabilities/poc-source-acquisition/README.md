# `poc.source_acquisition` — M20-B2 fixture provider

This provider is deliberately **loopback-fixture only**. It exercises the normal Node Capability Runtime, managed `curl >=8.4,<9`, Workspace, and Artifact spool without contacting GitHub or executing repository code. Its manifest advertises only `source_kind=loopback_fixture`; `github_repository` inputs fail closed. B4 will own a separately reviewed public GitHub adapter.

The input uses the shared bounded acquisition contract with a synthetic canonical repository claim and an explicit loopback fixture port. The provider requests fixed `/revision` and `/archive.zip` routes on `127.0.0.1:<port>`. It checks the fixture's full-SHA revision claim against the selected repository/ref, preserves the exact ZIP bytes, inventories only structure, and emits a typed receipt plus raw/manifest Artifacts. A rejected ZIP may leave a raw evidence Artifact but never a successful receipt or completion-ready manifest.

See [M20-B implementation notes](../../docs/m20/M20B_IMPLEMENTATION.md) for limits and deferred B3/B4 integration.
