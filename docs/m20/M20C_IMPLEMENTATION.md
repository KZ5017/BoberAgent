# M20-C1 exact source-evidence foundation

**Status:** C1 implemented. C2–C5 remain unimplemented. Inspection is Core-owned and offline;
it reads only retained Core Artifacts from a `COMPLETED` `PoCAcquisition`. It does not import,
extract, compile, execute, re-fetch, or semantically interpret acquired source.

`PoCInspectionRef` is a Core-private logical attempt ID, distinct from acquisition, Artifact,
commit, and content hashes. Creation checks Mission→hypothesis→candidate→acquisition ownership,
the completed receipt, both Artifact catalog descriptors, and the resolved commit. A request
stores exact raw ZIP/manifest refs and hashes, raw size, profile ID/version, explicit C1 limits,
selected structural verification paths, and a SHA-256 fingerprint of those settings. The profile
is `m20-c1-evidence` version `1`; changing profile/version/limits/selected paths creates a new
attempt. For an identical acquisition/source/profile/config, a completed or requested attempt
is reused unless explicit `force_new` is requested. Failed/interrupted attempts are historical
and are not silently retried.

The lifecycle is `REQUESTED → INSPECTING → COMPLETED` or terminal `FAILED`/`INTERRUPTED`.
`COMPLETED` means only that both retained Artifacts rehashed, the strict
`poc-source-manifest-v1` structure and identity validated, the ZIP inventory reconciled,
and explicitly selected entry bytes (if any) passed SHA-256/size verification. It does **not**
assert a source language, entrypoint, dependency, runtime safety, or execution support.
Unselected entries are recorded as unverified structural coverage. A failed exact-byte check
stores only a bounded reason code, not source text. `recover_interrupted()` conservatively
marks unproven `INSPECTING` attempts interrupted after restart; `REQUESTED` survives and may
be inspected later. Completed output is immutable.

Core opens both Artifacts through `CoreArtifactService`, streams and rehashes them before ZIP
parsing, then validates the bounded JSON manifest independently of the acquiring capability.
It checks version, exact raw hash/size, commit, archive representation, root prefix, sorted
unique normalized paths, types, sizes, count and total. A bounded ZIP central-directory
preflight rejects unsupported counts and raw NUL names before `zipfile` constructs entries;
reconciliation rejects missing/extra entries, unsafe paths, unsupported file types, and size
disagreement. A selected regular file is decompressed under C1 limits and its actual bytes are
SHA-256 checked against the manifest. No archive extraction API is used.

The default independent limits are 16 MiB manifest, 10,000 ZIP entries, 64 MiB per verified
entry, 512 MiB total selected-entry verification, 64 KiB per citation, 100 citations, and
30 seconds wall time. Tests can override them. Exceeding a selected-entry or total bound fails
the attempt; unselected entries remain explicit unverified coverage. No oversized entry becomes
citable evidence.

A canonical `SourceCitation` binds both Artifact refs and SHA-256 identities, normalized ZIP
relative path, verified per-entry SHA-256, a **nonempty half-open byte span** `[start, end)` in
the decompressed file, and reader ID/version. Core validates source binding, entry identity,
byte bounds and citation length before returning exact cited bytes. No large excerpt is stored.
Human 1-based line positions are derived only from deterministically decoded UTF-8 (including
BOM), ASCII-compatible bytes, or explicit UTF-16 LE/BE BOM. LF and CRLF each count as one line
separator; an undecodable or binary span has no line display. Byte offsets remain authoritative.

SQLite migration `0012_m20_c1_inspection` adds only the private attempt table and versioned
structural output JSON. It upgrades from `0011_m20_b3_fixture_mode` without rewriting older
rows. The offline manual check is
`uv run python scripts/manual-smoke/m20c1_inspection_evidence_smoke_test.py`.

C2 owns deterministic source-fact extraction, requirements, risks, and semantic coverage;
C3 owns conditional support classification. C4 may inspect the retained real B5 Artifacts only
after deterministic semantic inspection exists. M20-D+ owns plans, policy, preparation, and
execution. None of those is implemented by C1.
