# M20-B1 acquisition foundation (offline)

M20-B1 implements the Core decision and cross-machine shape from [ADR 0014](../adr/0014-m20-acquisition-ownership-and-immutable-source-representation.md). It does **not** acquire a repository. The static planned `poc.source_acquisition:acquire` [definition](poc_source_acquisition.definition.json) is inspectable, but has no Node implementation or advertised live provider.

## Selection and durable state

`CorePoCAcquisitionService.create_acquisition()` requires an explicit positive M20-A `ResearchSourceHit.hit_id`. This integer is the existing Core-private historical row identity, not a cross-machine domain ref or the `PoCAcquisitionRef`. Core checks Mission→hypothesis→candidate ownership, the hit's candidate/attempt/provider/admission/source identity, and a supported canonical public GitHub repository plus `branch:<name>` claim. It does not select the latest hit. Every explicit request receives a new stable `PoCAcquisitionRef`; earlier hits and acquisitions remain intact.

`PoCAcquisition` is persisted separately from the candidate, CapabilityRun, and Artifacts. Its allowed states are `REQUESTED → DISPATCHED → AWAITING_ARTIFACT → COMPLETED`, with terminal `FAILED`, `REJECTED`, and `INTERRUPTED`. `DISPATCHED` requires an already persisted normal CapabilityRun and Router decision. B1's `build_invocation()` only builds a typed normal invocation; it neither routes nor submits it. No live acquisition provider is advertised.

## Shared boundary and finalization

`PoCAcquisitionBounds` requires all size, count, path, ratio, request, redirect, and timeout limits explicitly. `PoCSourceAcquisitionInput` carries only the acquisition correlation ref, public GitHub repository claim/ID, selected historical ref, and bounds. The typed `PoCSourceAcquisitionReceipt` is placed under `CapabilityOutcome.details["acquisition_receipt"]` in the existing `CapabilityResult`; it distinguishes the full upstream commit SHA from the exact raw-ZIP SHA-256. Core-private research and acquisition rows do not cross the transport. The receipt is a claim, not completion proof.

Core reconciliation reads a persisted, processed CapabilityResult, validates the receipt against the selected source/Run/Node/bounds, and retains its raw ZIP and JSON manifest ArtifactRefs. It remains `AWAITING_ARTIFACT` while either Artifact lacks verified Core content. Once both descriptors and stored bytes match the receipt's hashes/sizes, it becomes `COMPLETED`. Replaying reconciliation or reopening Core does not dispatch a new Run. Acquisition Results containing target Observations, Findings, or Effects are rejected before World State ingestion. Failure, rejection, and uncertain interruption remain distinct terminal states.

The offline smoke is `uv run python scripts/manual-smoke/m20b1_acquisition_foundation_smoke_test.py`. It uses only a temporary Core database, deterministic research hits, synthetic receipt, and local verified Artifact bytes. No internet, GitHub request, Kali Node, downloader, ZIP inventory, or source execution is used.

B2 still owns downloader feasibility, local fixture acquisition, structural ZIP inventory, and hostile archive tests. B3 owns production Artifact integration/reconciliation; B4 owns real GitHub identity/SHA/archive retrieval. M20-C inspection and later PoC execution remain out of scope.
