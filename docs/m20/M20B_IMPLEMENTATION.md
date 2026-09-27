# M20-B1 acquisition foundation (offline)

M20-B1 implements the Core decision and cross-machine shape from [ADR 0014](../adr/0014-m20-acquisition-ownership-and-immutable-source-representation.md). It does **not** acquire a repository. The static planned `poc.source_acquisition:acquire` [definition](poc_source_acquisition.definition.json) is inspectable, but has no Node implementation or advertised live provider.

## Selection and durable state

`CorePoCAcquisitionService.create_acquisition()` requires an explicit positive M20-A `ResearchSourceHit.hit_id`. This integer is the existing Core-private historical row identity, not a cross-machine domain ref or the `PoCAcquisitionRef`. Core checks Mission→hypothesis→candidate ownership, the hit's candidate/attempt/provider/admission/source identity, and a supported canonical public GitHub repository plus `branch:<name>` claim. It does not select the latest hit. Every explicit request receives a new stable `PoCAcquisitionRef`; earlier hits and acquisitions remain intact.

`PoCAcquisition` is persisted separately from the candidate, CapabilityRun, and Artifacts. Its allowed states are `REQUESTED → DISPATCHED → AWAITING_ARTIFACT → COMPLETED`, with terminal `FAILED`, `REJECTED`, and `INTERRUPTED`. `DISPATCHED` requires an already persisted normal CapabilityRun and Router decision. B1's `build_invocation()` only builds a typed normal invocation; it neither routes nor submits it. No live acquisition provider is advertised.

## Shared boundary and finalization

`PoCAcquisitionBounds` requires all size, count, path, ratio, request, redirect, and timeout limits explicitly. `PoCSourceAcquisitionInput` carries only the acquisition correlation ref, public GitHub repository claim/ID, selected historical ref, and bounds. The typed `PoCSourceAcquisitionReceipt` is placed under `CapabilityOutcome.details["acquisition_receipt"]` in the existing `CapabilityResult`; it distinguishes the full upstream commit SHA from the exact raw-ZIP SHA-256. Core-private research and acquisition rows do not cross the transport. The receipt is a claim, not completion proof.

Core reconciliation reads a persisted, processed CapabilityResult, validates the receipt against the selected source/Run/Node/bounds, and retains its raw ZIP and JSON manifest ArtifactRefs. It remains `AWAITING_ARTIFACT` while either Artifact lacks verified Core content. Once both descriptors and stored bytes match the receipt's hashes/sizes, it becomes `COMPLETED`. Replaying reconciliation or reopening Core does not dispatch a new Run. Acquisition Results containing target Observations, Findings, or Effects are rejected before World State ingestion. Failure, rejection, and uncertain interruption remain distinct terminal states.

The offline smoke is `uv run python scripts/manual-smoke/m20b1_acquisition_foundation_smoke_test.py`. It uses only a temporary Core database, deterministic research hits, synthetic receipt, and local verified Artifact bytes. No internet, GitHub request, Kali Node, downloader, ZIP inventory, or source execution is used.

B2's downloader feasibility, local fixture acquisition, structural ZIP inventory, and hostile archive tests are described below. B3 adds Artifact integration/reconciliation; B4 adds offline-tested GitHub identity/SHA/tree/archive retrieval. M20-C inspection and later PoC execution remain out of scope.

## B2 local bounded-acquisition proof

At B2, the installable `poc.source_acquisition:acquire` provider was **fixture-only** and rejected GitHub/public inputs. B4 extends that same provider and static manifest to public GitHub mode. The shared input/receipt retain the source-kind-discriminated loopback fixture variant with explicit port and truthful loopback provenance URIs. Core's B3 fixture integration remains separate from the historical GitHub research claim.

The selected downloader is curl 8.4+ because `--max-filesize` enforces a ceiling **during** an unknown-length transfer in that version. The local proof used curl 8.5.0 and observed an exact-boundary response succeed and an oversized response stop with exit 63 after exactly the allowed bytes. The adapter invokes only SDK `ProcessService.run_tool(tool="curl", args=...)`, never shell or direct HTTP. The Node's ProcessService sanitizes environment; `-q` first disables .curlrc, `--proxy "" --noproxy "*"` disables ambient proxy routing, `--proto =http` restricts this fixture route, `--max-time` plus ProcessService timeout bounds each request, `--max-filesize` bounds arriving bytes, and `--output` writes only under a managed Workspace. No `--location` is used. The adapter validates each curl-reported redirect before issuing the next request; scheme, literal 127.0.0.1 host, same port, credentials, query/fragment, control characters, path traversal, redirect count, total request count, remaining aggregate byte budget, and total elapsed deadline are checked. The revision response has an additional 4 KiB in-transfer ceiling. Only fixed `/revision` and `/archive.zip` initial routes exist. The fixture revision JSON must repeat the authorized repository URI, provider repository ID, and historical ref, and supplies a synthetic full 40-hex SHA. That SHA is not the archive SHA-256.

The raw response is copied unchanged to a `poc.source.raw` ZIP Artifact **before** inventory. Trusted code inventories the ZIP without extraction. It preflights the central directory/count/raw NUL names, then accepts only regular files and directories. Names use POSIX separators, NFC normalization and case-fold collision detection (including implicit parent directories); one unambiguous common archive root is recorded and stripped once from manifest paths. Entry count includes the archive's root directory and all other explicit entries; manifest `entry_count` excludes only the stripped root. Each file is streamed under actual per-file/total decompressed byte and compression-ratio bounds, CRC checked, and SHA-256 hashed. Paths are bounded by UTF-8 byte length and component depth. A hard 16 MiB structural-manifest ceiling is enforced before and after JSON serialization. A versioned, sorted, canonical JSON `poc.source.manifest` Artifact contains structural paths, types, size/hash, mode/executable when reliable, root prefix, revision, and raw hash/size. It contains no semantic source interpretation.

Traversal, absolute/drive/UNC-like/backslash paths, duplicate/case/Unicode collisions, special entries and symlinks, encrypted/unsupported compression, unreviewed ZIP extra fields, corruption, limits, and canonical Git LFS pointers reject completion. Fixture mode rejects `.gitmodules` because it has no complete Gitlink check; B4 GitHub mode accepts that file only after a complete Gitlink-free tree check and never fetches its references. A rejected archive may leave only the raw Artifact as evidence and yields `COMPLETED + UNKNOWN` with a bounded reason code; no successful receipt or manifest is produced. Managed Workspace files are cleaned after success and rejection; spooled Artifacts remain. An uncertain Node crash still follows existing conservative Run recovery, with no automatic reacquisition.

Run `uv run python scripts/manual-smoke/m20b2_bounded_acquisition_smoke_test.py` for the entirely offline loopback proof. It exercises real Node loading, managed curl, exact-byte raw Artifact, manifest, and a traversal rejection. B4's fixed-host GitHub adapter is documented below. No M20-C inspection or PoC execution exists.

## B3 Artifact synchronization and Core finalization

B3 persists an explicit `source_kind=loopback_fixture` and fixture port on a Core `PoCAcquisition` only when deliberately selected; existing B1 rows migrate to `github_repository` with no fixture port. The selected historical GitHub research hit remains the **claim**, not proof of a public download. The normal Core Registry/Router dispatches the fixture-mode invocation to the advertised Node provider. No Core path imports the capability or contacts the fixture server.

The normal Core transport receiver durably accepts and processes the Result. A successful typed receipt binds the selected acquisition, Run, source claim, fixture port, raw ZIP descriptor, and manifest descriptor. `AWAITING_ARTIFACT` is durable even when the Result arrives first; neither Artifact alone suffices. Existing Node `ArtifactSyncCoordinator` and Core `CoreArtifactReceiver` transfer each Artifact independently with chunked offset resume, SHA-256/size verification, and unchanged `ArtifactRef`. Core finalization reads the Artifact catalog and verified bytes through `CoreArtifactService`; it never reads Node Workspace/spool paths. Reconciliation can run again after Core restart without redispatch, redownload, or a new Run. Generic Node restart recovery leaves unproven in-flight Runs interrupted and retains spooled Artifact metadata for pending sync.

The offline integration and `uv run python scripts/manual-smoke/m20b3_acquisition_sync_smoke_test.py` use the in-memory **neutral protocol** with a real Node runtime, managed curl, loopback HTTP fixture, normal Result ingestion, partial transfer/reconnect, Node/Core reopen, and both arrival orders. This is not a real MCP cross-machine test; generic MCP Artifact transport remains unchanged. Hostile ZIPs produce no successful receipt or completion-ready manifest. B4's GitHub identity/SHA/tree/archive adapter is offline-tested below; B5 owns live-service validation. No semantic source inspection or repository execution is added.

## B4 fixed-host GitHub mode (offline/mock validated)

The production `poc.source_acquisition` manifest now advertises both `github_repository` and
`loopback_fixture`; required `curl >=8.4,<9` is unchanged. Core still selects one historical
hit, persists a normal acquisition, and routes a normal Run. The Node validates public repository
ID/owner/name/URL, resolves only the selected historical branch to a full commit SHA, obtains its
tree SHA, and rejects incomplete trees, Gitlinks, symlinks and unsupported Git modes. A
`.gitmodules` file with a complete Gitlink-free tree remains inert evidence; no submodule URL is
fetched. Canonical LFS pointers are rejected by the shared ZIP inventory without LFS hydration.

Exactly constructed endpoints use `api.github.com` for repository, branch, commit, recursive
tree, and SHA-addressed zipball metadata; only a validated `codeload.github.com` legacy.zip/zip
redirect for the same owner/repo/full SHA may deliver bytes. No arbitrary URL, generic web fetch,
ambient proxy/config, automatic redirect, retry, private-repository token, or public request in
tests. Managed curl enforces streaming size and timeout; one acquisition-wide request, byte,
redirect and deadline budget covers metadata and archive. GitHub response bodies are never copied
into Diagnostics. The receipt records fresh identity and endpoints separately from the unchanged
historical claim, plus the exact ZIP hash and both Artifact descriptors. The ZIP is a GitHub
archive export, not proof of native Git object-byte equivalence.

The offline Core→Router→Node integration test uses a test-owned curl executable that only writes
scripted local responses. It exercises real Node runtime, B2 Artifacts/inventory, B3 neutral
in-memory Result delivery, Artifact synchronization, and Core finalization. No public GitHub call
has been made; B5 must opt in to live public validation. M20-C semantic source inspection and
repository-controlled execution remain deferred.

The ordinary MCP Node startup must configure both `--tool curl=/path/to/curl` and
`--tool-version-arg curl=--version`; otherwise the version-gated capability is correctly
advertised unavailable. B5 additionally needs explicit public egress to `api.github.com` and
`codeload.github.com`, a persisted M20-A candidate plus selected historical hit, bounds large
enough for the five API/archive requests and one codeload redirect, and Core Artifact sync.
B4 did not include a B5 live-smoke command or public repository selection; the separately
opted-in B5 harness below adds that validation surface without changing the B4 adapter.

## B5 live validation harness (prepared; public run pending)

The manual-only B5 script consumes a previously persisted M20-A GitHub candidate plus one
operator-selected historical source-hit ID. It never reruns research or selects a latest hit.
An offline `--check-config` validates the explicit Core database, selection, MCP settings and
fixed bounds without dispatch or network. `--live-network` uses the normal Core Registry/Router,
real MCP, Node acquisition provider, Result inbox/ingestion, and chunked Artifact sync. It
requires `AWAITING_ARTIFACT` after the Result, then `COMPLETED` only after both verified Core
Artifacts arrive. A durable reopen verifies source/Run/provider/revision identity and exact
Artifact hashes without re-fetch. The operator procedure, Kali startup, egress and failure
categories are in `scripts/manual-smoke/README.md`. No completed live public run is
claimed by this implementation note; M20-B remains open until one such run passes.

### First real B5 compatibility finding

The first opt-in public run selected historical hit 4 for
`https://github.com/CERTCC/CVE-2021-44228_scanner` and resolved commit
`042e5d9c15fe8312492d2f08063631be58486830`. Real GitHub acquisition retained the
305,188-byte raw ZIP Artifact before inventory, but produced `ARCHIVE_UNSUPPORTED` because
every observed entry carried the standard 9-byte `0x5455` Extended Timestamp ZIP extra
record. That first acquisition (`poc-acquisition-23c700c90f304899ae306dbf4361425f`)
remains `REJECTED` historical evidence; it was not modified or replayed.

Inventory now accepts only one structurally valid `0x5455` modification-time record per
entry (flags `0x01`, exactly four timestamp bytes), without using the timestamp in
manifest paths, content hashes, or source identity. Unknown, duplicate, oversized, or
malformed extra records remain fail-closed. The B4 mocked GitHub archive and B5 offline
mock smoke now carry this exact field and pass through Core finalization. A **new** explicit
PoCAcquisition/Run and real public smoke are still required before M20-B can be closed.
