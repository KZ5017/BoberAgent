# `poc.source_acquisition` — bounded source acquisition

The single `acquire` operation supports explicit `loopback_fixture` and public
`github_repository` modes. Core selects one historical research hit; the Node cannot accept an
arbitrary URL. The GitHub adapter freshly validates repository ID and owner/name, resolves the
selected historical branch to a full commit SHA, checks the complete recursive Git tree for
Gitlinks/special objects, and requests a ZIP by that SHA. Only fixed `api.github.com` endpoints
and a validated SHA-bound `codeload.github.com` redirect are allowed. No token, proxy,
automatic redirect, retry, Git checkout, submodule/LFS hydration, extraction, import, build,
install, or repository-code execution occurs.

Both modes use SDK-managed `curl >=8.4,<9`, Workspace, raw ZIP Artifact, and one shared
bounded structural ZIP inventory/manifest. A rejected ZIP may preserve raw evidence but never a
successful receipt. The Node result uses the existing Result and Artifact-sync path; Core
finalization waits for both verified Artifacts. The GitHub implementation is **mock-tested only**;
B5 owns opt-in live public validation.

See [M20-B implementation notes](../../docs/m20/M20B_IMPLEMENTATION.md) for precise limits and
provenance semantics.
