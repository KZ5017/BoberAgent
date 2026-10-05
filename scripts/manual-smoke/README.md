Manual smoke tests only.

These scripts are not part of the automated pytest suite.
Most require an explicitly running Kali Execution Node and lab configuration;
the M20-A research smoke below is completely offline.
Do not execute them automatically from CI or normal test runs.

## M20-A deterministic research smoke (offline)

It creates a temporary Core database and verifies bounded hypothesis research, two candidates,
a duplicate revision hit, no-match, and provider-error history. No internet, token, LM Studio,
Kali Node, PoC download, or execution is used. From the repository root:

```shell
uv run python scripts/manual-smoke/m20a_research_smoke_test.py
```

## M20-A2 live GitHub repository metadata smoke (opt-in)

This is the only M20-A smoke that contacts the public internet. Choose an explicit public CVE
identifier for a harmless research query; the synthetic Mission Asset uses a reserved
documentation address and is never contacted. The script makes one bounded GitHub repository
search, admits only metadata-supported leads through Core, closes/reopens a fresh Core database,
and prints safe attempt/hit/candidate provenance. It never clones or downloads source.

From the repository root, choose a new database path whose parent already exists. Set
`PUBLIC_CVE_ID` to a public CVE identifier you choose; no target or PoC is selected by the
repository.

```shell
uv run python scripts/manual-smoke/m20a_live_github_smoke_test.py \
  --live-network --database /tmp/boberagent-m20a-live.sqlite3 \
  --cve-id "$PUBLIC_CVE_ID" --result-limit 5
```

Optional: set `GITHUB_TOKEN` in process environment or the ignored project-local `.env.local`.
Unauthenticated public search works at a lower rate limit. No token is placed on the command
line or printed. A previously existing database path is rejected; use a new path for each run.
Expected results include FOUND, NO_MATCH or PARTIAL. Safe environmental failures are reported
as PROVIDER_ERROR without upstream bodies; malformed provider data or unsupported queries fail
the smoke. Research is not vulnerability proof, acquisition authorization, or execution.

## M16 Secret resolution smoke test

This harmless fixture proves a Core-owned Secret can be granted to one Run, resolved through
`ctx.secrets` on Kali, and verified without placing the value in a CapabilityResult. It creates no
Credential: candidate Credential reduction is already covered by automated Core tests.

From the repository root on Kali, start a dedicated Node runtime with the manual fixture:

```shell
export PYTHONPATH="$PWD/scripts/manual-smoke/secret-resolution-capability/src"
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-secret-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path scripts/manual-smoke/secret-resolution-capability
```

From WSL, use the Node ID printed at startup and an explicit temporary Core directory:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run python scripts/manual-smoke/secret_resolution_smoke_test.py \
  --endpoint https://<kali-host>:8443/mcp \
  --node-id <node-id> \
  --core-runtime-directory /tmp/boberagent-secret-smoke-core \
  --ca-file /path/to/lab-ca.pem
```

For an isolated plaintext lab, replace `--ca-file` with
`--allow-insecure-remote-transport` and use an `http://` endpoint. The script prints its Core
database path, MissionRef, SecretRef, and RunRef, then checks the remote Result, Core ingestion,
and the `CAPABILITY_GRANT` audit. It never prints the synthetic value.

Afterward, substitute the printed database path and refs to compare ordinary metadata with an
explicit operator reveal:

```shell
uv run boberagent --database <printed-core-database> secret show <printed-secret-ref> \
  --mission <printed-mission-ref>
uv run boberagent --database <printed-core-database> secret reveal <printed-secret-ref> \
  --mission <printed-mission-ref>
```

The reveal command intentionally exposes the harmless test value. This harness does not create a
CredentialRef. If one exists from a separate Core-local candidate flow, its equivalent checks are:

```shell
uv run boberagent --database <core-database> credential show <credential-ref> \
  --mission <mission-ref>
uv run boberagent --database <core-database> credential reveal <credential-ref> \
  --mission <mission-ref> --role password
```

Ordinary `show` output remains metadata-only; `reveal` output is sensitive by design.

## Durable human-interaction smoke test

This harmless fixture proves `CONFIRMATION → TEXT → SINGLE_CHOICE` across WSL Core and a live Kali
Node. It collects no credentials or secrets. The CLI is intentionally a new process for every
command, so the sequence also proves Core restart/reopen while the Node remains `WAITING_INPUT`.

On Kali, make the manual fixture importable and start the Node:

```shell
export PYTHONPATH="$PWD/scripts/manual-smoke/interaction-capability/src"
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-hitl-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path scripts/manual-smoke/interaction-capability
```

On WSL, initialize explicit Core state and start the test Workflow. Set `NODE_ARGS` to the repeated
transport arguments shown here (shell arrays are recommended in an interactive Bash session):

```shell
export BOBERAGENT_MCP_BEARER_TOKEN='<dedicated-test-token>'
CORE=/tmp/boberagent-hitl-core.sqlite3
NODE_ARGS="--node-url https://<kali-host>:8443/mcp --node-id <node-id>"
uv run boberagent --database "$CORE" core init
uv run boberagent --database "$CORE" mission create --mission-ref mission-hitl-smoke
uv run boberagent --database "$CORE" $NODE_ARGS workflow start \
  --mission mission-hitl-smoke \
  --definition scripts/manual-smoke/interaction-workflow.json \
  --workflow-ref workflow-hitl-smoke
uv run boberagent --database "$CORE" $NODE_ARGS workflow advance workflow-hitl-smoke
uv run boberagent --database "$CORE" interaction list
```

Copy each stable `interaction_id` shown by `interaction list`. Answer the confirmation, then pull the
next durable Event and repeat for text and choice:

```shell
uv run boberagent --database "$CORE" $NODE_ARGS interaction respond <confirmation-id> --yes
uv run boberagent --database "$CORE" $NODE_ARGS workflow advance workflow-hitl-smoke
uv run boberagent --database "$CORE" interaction list
uv run boberagent --database "$CORE" $NODE_ARGS interaction respond <text-id> --text lab-check
uv run boberagent --database "$CORE" $NODE_ARGS workflow advance workflow-hitl-smoke
uv run boberagent --database "$CORE" interaction list
uv run boberagent --database "$CORE" $NODE_ARGS interaction respond <choice-id> --choice normal
uv run boberagent --database "$CORE" $NODE_ARGS workflow advance workflow-hitl-smoke
uv run boberagent --database "$CORE" workflow status workflow-hitl-smoke
```

For a private lab using plaintext HTTP, add `--allow-insecure-remote-transport`; for a private CA,
use the repository's existing trusted TLS setup. Do not put bearer tokens or secret values in the
workflow, request text, command history, or responses.

## Stateful browser smoke test

This procedure proves that one browser Session retains a cookie across separate MCP-delivered
Capability Runs. Use only an authorized lab. The HTTP fixture must be reachable from Kali and expose
two URLs on the same host:

- a `set` URL that responds with `Set-Cookie: browser_state=preserved; Path=/`;
- a `check` URL whose page title is `cookie-preserved` only when that cookie is received.

On Kali, install Chromium and the Python dependencies from the locked workspace, then run the Node
with the production capability and an explicit logical tool mapping:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-browser-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path capabilities/browser-interaction \
  --tool chromium=/usr/bin/chromium
```

From Core/WSL, use the Node ID printed by the listener and an explicit Core runtime directory:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run python scripts/manual-smoke/browser_state_smoke_test.py \
  --endpoint https://<kali-host>:8443/mcp \
  --node-id <node-id> \
  --core-runtime-directory /tmp/boberagent-browser-core \
  --asset-ref asset-browser-smoke \
  --set-url http://<fixture-host>:8080/set \
  --check-url http://<fixture-host>:8080/check \
  --ca-file /path/to/lab-ca.pem
```

For an isolated plaintext lab only, replace `--ca-file` with
`--allow-insecure-remote-transport`. The script performs `open → navigate(set) →
navigate(check) → close`, verifies `cookie-preserved`, and confirms a post-close navigation fails.
It never prints the bearer token. This is manual validation only; deterministic automated tests use
a controlled loopback server and do not require Kali or network access.

## Incoming TCP Session smoke test

This procedure proves asynchronous Session creation across real MCP without shell or payload
semantics. Choose an uncommon high port, bind the Kali interface explicitly, and authorize only
the controlled client's source IP. Ensure the lab firewall permits that single TCP path; these
scripts never change firewall configuration.

On Kali, start the Node with the production listener capability:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-listener-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path capabilities/network-listener
```

From Core/WSL, start the orchestration script. `--allowed-peer-address` must be the source address
Kali will actually observe for the controlled client:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run python scripts/manual-smoke/listener_session_smoke_test.py \
  --endpoint https://<kali-host>:8443/mcp \
  --node-id <node-id> \
  --core-runtime-directory /tmp/boberagent-listener-core \
  --bind-address <kali-interface-address> \
  --allowed-peer-address <controlled-client-source-address> \
  --port 45873 \
  --ca-file /path/to/lab-ca.pem
```

When it reports that the Listener is ready, run the bounded fixture client from the authorized
machine:

```shell
uv run python scripts/manual-smoke/listener_test_client.py \
  --host <kali-interface-address> --port 45873
```

The client sends only `hello-boberagent` and expects `pong-boberagent`. Core waits for the normal
`session.created` Event, performs separate `receive`, `send`, `close_session`, and `close_listener`
Capability Runs, then exits. No command interpreter, PTY, payload generation, or received-byte
execution is involved. For an isolated plaintext lab only, the Core script also accepts
`--allow-insecure-remote-transport` instead of `--ca-file`.


## M18 semantic retrieval smoke test (local LM Studio)

This is manual validation of the existing M17 loader and M18 provider/index/router path. It does not
use Kali, MCP, a Qdrant server, model discovery, or an LLM chat endpoint. Start LM Studio's
OpenAI-compatible server locally, load the already-verified `text-embedding-bge-m3` embedding
model, and ensure its bearer-authenticated `POST /v1/embeddings` endpoint is reachable at
`http://127.0.0.1:1234/v1`. The script calls only that embedding endpoint.

Three small, harmless M17-compatible reference fixtures are in
`scripts/manual-smoke/fixtures/semantic-retrieval/reference/`: LDAP signing (with multiple
headings), HTTP service response inspection, and DNS resolution. The script **never copies**
them or scans outside `--knowledge-root`. To include them in the real authored Knowledge root,
the operator may explicitly check for conflicting filenames and then copy without overwriting:

```bash
KNOWLEDGE_ROOT=/mnt/d/hack/OBSIDIAN/my_notes_v2/BOBER_AGENT
cp -n scripts/manual-smoke/fixtures/semantic-retrieval/reference/*.md "$KNOWLEDGE_ROOT/reference/"
```

The Windows equivalent Knowledge root is
`D:\hack\OBSIDIAN\my_notes_v2\BOBER_AGENT`. Keep any existing authored notes under that root
curated; the script indexes only canonical `reference/` and `procedures/` there. It never
walks the parent Obsidian vault. If the real root has other canonical notes, they may also appear
in ranked results.

From the repository root in WSL, copy the safe template once, then privately edit
`.env.local` to set `LM_API_TOKEN`. The file is Git-ignored; do not commit it. The script reads
that file at startup, so no shell export is required. Use an explicit, separate on-disk derived-index
directory:

```bash
cp -n .env.example .env.local
# Privately edit .env.local and set LM_API_TOKEN before running the command below.
uv run python scripts/manual-smoke/semantic_retrieval_smoke_test.py \
  --knowledge-root /mnt/d/hack/OBSIDIAN/my_notes_v2/BOBER_AGENT \
  --index-directory /tmp/boberagent-m18-semantic-smoke \
  --base-url http://127.0.0.1:1234/v1 \
  --model text-embedding-bge-m3 \
  --api-key-env LM_API_TOKEN \
  --query "authentication is rejected because the directory service requires signed communication"
```

An existing process `LM_API_TOKEN` overrides `.env.local`. Set `BOBERAGENT_ENV_FILE` to
explicitly select another private env file if needed. Do not place the token in Knowledge Markdown,
Qdrant payloads, logs, screenshots, command-line arguments, or committed files. The script does not
print or persist the token or vectors. `--timeout`, `--limit`, `--domain`, `--protocol`, and
`--tool` are optional; filters narrow the real candidate set.

The script explicitly refreshes the derived Qdrant-local generation, queries the production
KnowledgeRouter, checks that hits are canonical source-faithful reference chunks, and verifies
an independent exact-ID lookup of the top hit. It prints rebuilt/reused generation state and
ranked score, Knowledge ID/version, title, heading path, section/chunk/document ordinals,
root-relative provenance path, and a bounded JSON-escaped **source** excerpt—not synthesized
embedding input. The LDAP-signing fixture should rank ahead of the unrelated HTTP/DNS fixtures
for the example query; inspect the printed scores and order. Scores are cosine relevance, not
calibrated probabilities. Qdrant local permits one process/client on the index directory at a
time; close other users before rerunning. The index is derived data and may be discarded when not
in use. Automated tests continue to use fake embeddings and require no LM Studio, token, network,
GPU, or Qdrant server.

## M19 advisory Reasoner (manual, local model)

With an OpenAI-compatible chat model running in LM Studio, use the same private
`LM_API_TOKEN` convention described above. From the repository root:

```bash
uv run python scripts/manual-smoke/reasoner_smoke_test.py \
  --base-url http://127.0.0.1:1234/v1 \
  --model qwen/qwen3.5-9b \
  --api-key-env LM_API_TOKEN
```

`--model` is operator-selectable: `qwen3.8-9b-distill` has also been used with the same
command. Neither model name is a Core default. The Reasoner now receives the selected
operation's input schema through normal ContextBuilder projection, not a smoke-only hint.

The script upgrades a temporary Core database, creates synthetic Mission/Asset/Goal/service
evidence, loads the repository's curated Knowledge and Procedure, advertises one *synthetic*
provider definition, builds a bounded context, asks the real chat model for structured output,
then validates any proposed action. It prints the structured assessment, source provenance, and
budget; it never dispatches the proposal or creates a Run for it. A model's invented
reference, unsupported operation, or invalid inputs cause an explicit validation failure. This
smoke is not collected by pytest and requires no Kali Node or network target.
## M20-B1 acquisition foundation (offline)

From the repository root:

```bash
uv run python scripts/manual-smoke/m20b1_acquisition_foundation_smoke_test.py
```

This uses a disposable Core SQLite database and local synthetic bytes. It explicitly chooses
one of two historical research hits, persists a bounded acquisition request, builds the normal
invocation shape, reconciles a synthetic receipt before and after both verified Artifacts become
available, and reopens Core to confirm provenance. The provider registration is an offline
fixture, not an advertised live acquisition capability. No GitHub request, download, ZIP
inventory, Kali Node, API token, or target interaction occurs. See
[the B1 implementation note](../../docs/m20/M20B_IMPLEMENTATION.md).

## M20-B2 bounded acquisition smoke (offline)

From the repository root, with managed `curl >=8.4,<9` installed:

```bash
uv run python scripts/manual-smoke/m20b2_bounded_acquisition_smoke_test.py
```

The script creates a disposable Execution Node and a loopback-only HTTP fixture. The fixture
serves one deterministic synthetic revision and one GitHub-style ZIP. The real Node Capability
Runtime loads the `poc.source_acquisition` manifest with explicit fixture-mode input, runs curl through
`ProcessService`, preserves exact raw ZIP bytes in its Artifact spool, inventories the ZIP
without extraction, and prints the synthetic revision, raw/manifest ArtifactRefs, hashes, size,
entry count, and uncompressed total. It then serves a traversal ZIP and verifies rejection with
raw evidence only. All Workspace files are cleaned; no repository code runs. This smoke uses no
Core→Node transport, no public network, no GitHub token, and no Kali VM. The separate B3
cross-component Artifact/finalization proof is described below.

## M20-B3 acquisition sync and finalization smoke (offline)

From the repository root, with managed `curl >=8.4,<9` installed:

```bash
uv run python scripts/manual-smoke/m20b3_acquisition_sync_smoke_test.py
```

This validation-only runner reuses the automated B3 integration harness. It creates disposable
Core and Node databases, a loopback fixture, selected historical research hit, and a normal
Router-dispatched acquisition Run. The Result is ingested first; a deliberately interrupted
chunk transfer resumes, both real Node-produced Artifacts synchronize to Core, and durable
`PoCAcquisition` finalization is replayed after Core and Node reopen. It prints only refs, hashes,
selected hit, revision, provider/Node, and status. Transport is in-memory across the existing
neutral protocol—not MCP. No public network, GitHub acquisition, or source execution occurs.

## M20-B4 GitHub acquisition smoke (fully offline)

From the repository root:

```bash
uv run python scripts/manual-smoke/m20b4_github_acquisition_mock_smoke_test.py
```

This reuses the B4 integration harness and creates disposable Core/Node stores. A test-owned
executable substitutes for managed curl and maps the **production fixed GitHub URLs** to local
metadata and a small ZIP; it has no network code. The normal Router, Node Capability Runtime,
Result ingestion, Artifact synchronization and Core finalization run. Output includes historical
and fresh repository identities, the historical branch, resolved full SHA, raw/manifest
ArtifactRefs and hashes, and terminal status. No GitHub token, Internet, Kali VM, repository
execution, or M20-C inspection is involved. B5 live validation is a separate opt-in step.

## M20-B5 real public GitHub acquisition (opt-in, not automated)

This is the final **live validation**, not another acquisition implementation. It requires a
previous M20-A **persisted, admitted public GitHub** candidate and an explicit historical hit
ID. The M20-A2 live smoke above prints both (`Candidates:` and `Hit: id=...`). Choose a small,
harmless public research repository yourself; a search lead is not vulnerability proof. B5
does not select the first/latest hit, contact a target, inspect source meaning, or execute source.

On Kali, from the repository root, use a **dedicated fresh Node runtime** (so the pending
Artifact list contains only this smoke's Artifacts). Ensure `/usr/bin/curl` is version 8.4–8.x
and only `api.github.com` and `codeload.github.com` are permitted public egress. The two hosts
are enforced by the production adapter; no GitHub token/private-repository support is added.

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
uv run boberagent-node-mcp \
  --runtime-directory /var/lib/boberagent-m20b5-smoke \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key \
  --capability-path capabilities/poc-source-acquisition \
  --tool curl=/usr/bin/curl --tool-version-arg curl=--version
```

Use the Node ID printed at startup. On WSL/Core, first run the **offline, read-only** preflight
with your actual persisted M20-A database, selected candidate/hit, explicit Core Artifact root,
and MCP endpoint. The script reads `BOBERAGENT_MCP_TOKEN` from the process or ignored
`.env.local` using the normal operator loader; it never prints it. The token must match Kali.

```shell
export BOBERAGENT_MCP_TOKEN='<same-dedicated-test-token>'
export BOBERAGENT_MCP_ENDPOINT='https://kali.example.test:8443/mcp'
export BOBERAGENT_NODE_ID='node-from-Kali-startup'
export POC_CANDIDATE_REF='poc-candidate-from-M20-A'
export SOURCE_HIT_ID='positive-hit-id-from-M20-A'
uv run python scripts/manual-smoke/m20b5_live_github_acquisition_smoke_test.py \
  --check-config \
  --database /absolute/path/to/m20a-core.sqlite3 \
  --artifact-root /absolute/path/to/m20b5-core-artifacts \
  --candidate-ref "$POC_CANDIDATE_REF" --hit-id "$SOURCE_HIT_ID" \
  --endpoint "$BOBERAGENT_MCP_ENDPOINT" --node-id "$BOBERAGENT_NODE_ID" \
  --ca-file /absolute/path/to/lab-ca.pem
```

After reviewing the printed repository, historical branch and explicit bounds, repeat the
command replacing `--check-config` with `--live-network`. No public request is made without
that flag. For an isolated plaintext lab only, replace `--ca-file` with
`--allow-insecure-remote-transport` and use an `http://` endpoint. Do not use plaintext MCP
over an untrusted network.

The fixed bounds are 32 MiB total downloaded bytes, 128 MiB uncompressed ZIP content, 32 MiB
per file, 2,500 entries, depth 32, 512-byte paths, 200:1 compression ratio, eight outbound
requests, one redirect, and 180 seconds acquisition time. This covers the five GitHub API/
archive requests plus one codeload request without allowing unbounded retrieval. The script
uses a 240-second Result wait and a 64 KiB Artifact transfer chunk. Choose a repository that
fits these limits; do not bypass them. A successful run must show real MCP registration/routing,
`DISPATCHED → AWAITING_ARTIFACT → COMPLETED`, both Artifacts synchronized, SHA-256/size
verification through Core storage, and `COMPLETED` after Core database reopen. Reopen does not
contact GitHub again.

Provider unavailability, API rate limits, repository identity changes, missing branches,
truncated trees, Gitlinks, LFS pointers, unsafe/oversized ZIPs, and Artifact sync failure are
**non-successful safe stops**. Inspect the retained Core database and Node diagnostics; do not
automatically retry a possibly state-changing Run. This manual smoke is not collected by pytest.
M20-C semantic inspection is not part of this B5 smoke; its separate phase is now CLOSED.
Repository execution and private GitHub authentication remain deferred.

The first real public B5 run against `CERTCC/CVE-2021-44228_scanner` reached a retained
raw ZIP but stopped as `ARCHIVE_UNSUPPORTED`: normal GitHub ZIP entries contained the
standard `0x5455` Extended Timestamp extra field. The original
`poc-acquisition-23c700c90f304899ae306dbf4361425f` remains rejected and must not
be changed or retried as the same Run. The inventory parser now accepts only a
structurally valid 5-byte UT modification-time payload; unknown/malformed extras
still stop. Offline mocks with that field pass. The subsequent opt-in real run used a **new**
PoCAcquisitionRef and CapabilityRunRef and acquired the exact same raw ZIP SHA-256
`033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6`, showing
parser compatibility changed without changing source identity. Both raw and manifest Artifacts
synchronized over TLS/MCP; Core reached `COMPLETED` and retained it after reopen without
re-fetch. **M20-B — Acquisition + Immutable Provenance is CLOSED.** See the
[B5 validation record](../../docs/m20/M20B_IMPLEMENTATION.md) for identifiers and hashes.

## M20-C1 exact source-evidence smoke (offline)

Run from the repository root:

```bash
uv run python scripts/manual-smoke/m20c1_inspection_evidence_smoke_test.py
```

This manual wrapper runs the focused migration-backed synthetic integration scenario: a fresh
Core DB and managed Artifact root, a completed synthetic acquisition with raw ZIP and
`poc-source-manifest-v1` Artifacts, independent rehash/reconciliation, one verified file-byte
citation, and Core reopen. It needs no GitHub, Kali, MCP, or network. It does **not** inspect
the real B5 Artifact, infer source semantics, classify execution support, extract or execute
repository code, or build an ExecutionPlan. See
[the C1 implementation note](../../docs/m20/M20C_IMPLEMENTATION.md).

## M20-C2 offline deterministic inspection

From the repository root with the dev environment synced:

```bash
uv run python scripts/manual-smoke/m20c2_deterministic_inspection_smoke_test.py
```

This thin runner reuses the migration-backed synthetic fixture suite: README, Python,
PowerShell, shell, pyproject/requirements and binary entries are retained as Core ZIP/manifest
Artifacts. C1 validates exact evidence, C2 records bounded typed observations/citations, then
Core reopens. Output is safe metadata/counts/indicator codes only, not source or string defaults.
No Internet, GitHub, Node, MCP or real B5 Artifact access is required. This is not a classification,
plan or execution smoke; classification uses the separate C3 smoke below.


## M20-C3 offline conditional support classification

From the repository root with the dev environment synced:

```bash
uv run python scripts/manual-smoke/m20c3_support_classification_smoke_test.py
```

This small pytest-backed manual runner completes three migration-backed synthetic
C1 → C2 → C3 histories, then reopens Core to verify persisted AUTOMATIC, ASSISTED
(credential prerequisite), and UNSUPPORTED (unbounded filesystem effect) results.
It prints bounded refs, classifier profile/version, status, reason codes and evidence counts;
no source excerpts or sensitive values. Classification is conditional compatibility only,
**not authorization, runtime readiness, an ExecutionPlan or permission to execute**.

No Internet/GitHub, Kali, MCP, live B5 Artifacts, LLM or Knowledge is used. No source executes,
dependencies install, parameters bind or Resources/Secrets resolve. C4 separately validated
retained real source; C5 and M20-D+ are not part of this smoke.

## M20-C4 real retained-source inspection (offline, opt-in)

This manual harness inspects **only already-retained Core evidence**, not GitHub or Kali.
It needs no MCP endpoint, Node ID, token, TLS configuration, Internet, LLM or Knowledge.
It writes inspection history, not source bytes, only after the explicit real-data opt-in.
**M20-C — Source Inspection + Conditional Support Classification is CLOSED.**
The operator completed the calibrated real C4 rerun with C1@1/C2@2/C3@2: all COMPLETED,
classification UNSUPPORTED, Core reopen PASS and identical-invocation reuse PASS.
See the [immutable acceptance record](../../docs/m20/M20C_IMPLEMENTATION.md#m20-c-closed-real-retained-source-acceptance).
C5 is optional advisory future work, deferred and not required for closure. At C4 closure,
M20-D had not begun; it is now CLOSED after D8 acceptance.
The @1 run completed C1/C2/C3, reopened Core and reused history without fetch/execution/LLM/plan.
Its honest UNSUPPORTED outcome exposed primitive-only filesystem overclassification.
C4.1 preserves observed writes/deletes, requires stronger evidence for destructive/broad scope,
and keeps unresolved scope explicit and fail-closed. The accepted @2 run retained file-mutation
observations and removed false destructive/unbounded reasons where scope was not proven.
Remaining blockers include insufficient coverage, material unknowns and target boundary;
assistance includes entrypoint selection, manual parameters, runtime confirmation and dependency
review. The real UNSUPPORTED result is not safety or authorization.

The commands below are retained for explicit operator reproduction only; no further real run
is required for closure, and none was run during the documentation update.
Set `DB` and `ARTIFACT_ROOT` to the actual **existing absolute** retained Core SQLite file and
managed Core Artifact directory. Do not guess stale `/tmp` paths. If either has disappeared,
stop: C4 does not re-fetch or reconstruct acquisitions. From the repository root in Bash:

```bash
DB=/absolute/path/to/retained-m20b5-core.sqlite3
ARTIFACT_ROOT=/absolute/path/to/retained-m20b5-core-artifacts
C4_ARGS=(
  --database "$DB"
  --artifact-root "$ARTIFACT_ROOT"
  --acquisition-ref 'poc-acquisition-2f6a3658a57c42f5ae2252edf1736352'
  --expected-raw-artifact-ref 'artifact-032c7c87-c1c2-402a-ba2e-269545766f3a'
  --expected-raw-sha256 '033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6'
  --expected-manifest-artifact-ref 'artifact-463d3e1b-e38a-41ed-afb9-b59fc33bee56'
  --expected-manifest-sha256 'e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0'
  --expected-commit '042e5d9c15fe8312492d2f08063631be58486830'
)
uv run python scripts/manual-smoke/m20c4_real_retained_source_inspection_smoke_test.py \
  --check-config "${C4_ARGS[@]}"
```

Preflight checks acquisition/Mission/hypothesis/candidate identity, COMPLETED status, Artifact
catalog/receipt metadata, explicit expected bindings and root existence. SQLite is opened
`mode=ro`; storage is not initialized, bytes/ZIP entries are not opened, and no attempts or
migrations are written. Expect `OFFLINE RETAINED-SOURCE CONFIGURATION VALID`.
This is metadata validation, not yet an Artifact integrity/availability proof.

After reviewing that identity, authorize the fully offline C1→C2→C3 run:

```bash
uv run python scripts/manual-smoke/m20c4_real_retained_source_inspection_smoke_test.py \
  --real-retained-source "${C4_ARGS[@]}"
```

It upgrades **existing** Core migrations if needed, rehashes both retained Artifacts, and
uses production C1@1 manifest/ZIP verification, C2@2 deterministic inspection and C3@2 classification.
New document versions are `m20-c2-deterministic-v2` and `m20-c3-support-classifier-v2`.
C1 has empty selected-entry verification; C2 independently verifies bounded selected files
before interpreting them. Source is never extracted, imported, executed, repaired or installed.

Output includes coverage/counts/per-file reasons, entrypoint/parameter/dependency candidates,
typed requirements/behaviors/risks, unknowns/conflicts, and evidence-linked C3 reasons.
CODE/metadata/documentation and OBSERVED/INFERRED/UNKNOWN stay distinct. String defaults and
non-identifier names are redacted. Citation spot checks across available extractors show exact
byte spans, derived lines, length and SHA-256 only; no raw source/secret excerpts are displayed.

**Do not expect a predetermined classification.** AUTOMATIC, ASSISTED and UNSUPPORTED are all
valid completed inspection outcomes. Classification is conditional support, not safety,
authorization, runtime readiness or permission to execute. Missing state, integrity failures,
inconsistent output or reopen/reuse failure return a nonzero safe stop, not successful validation.

The run closes/reopens Core, compares acquisition and C1/C2/C3 histories including source hashes,
profile versions, semantic digest and class, then repeats production APIs to prove history reuse.
Repeat the exact `--real-retained-source` command to check cross-invocation reuse too; the refs
must remain the same. New @2 profiles create/reuse separate history; existing completed @1 records
are readable and immutable, not reinterpreted. No automatic force-new/retry mode is added.
Historical C1 `poc-inspection-e3bad26d882449e196d9146b841d42e8`, C2@1
`poc-inspection-f4613eced4a64d339367582978d2ae57` and C3@1
`poc-inspection-5897302e458a4514a29039b26e6e71fc` must remain unchanged.
Review scope reasons and citations, especially ordinary mutation vs broad destructive proof;
UNKNOWN is not safe and unchanged target/runtime/coverage gates may still block support.
The operator-reported calibrated acceptance is recorded and closes M20-C. Neither calibration
implementation nor this documentation closure automatically re-inspected the retained source.
The accepted run involved no network, source execution, extraction, install, Secret resolution,
LLM, Knowledge/RAG, ExecutionPlan, staging, authorization or runtime preparation.

Offline automated tests use temporary synthetic retained data:
`uv run pytest packages/core/tests/test_m20c4_manual_smoke_offline.py`.
They do not require these real paths. See [C4 implementation/acceptance](../../docs/m20/M20C_IMPLEMENTATION.md#c4-real-retained-source-validation-harness).
C4 stops here: no C5, chosen executable/argv, target/Secret binding, ExecutionPlan, policy approval,
Node restaging, runtime preparation or execution.

## M20-D7 offline synthetic planning vertical smoke

From the repository root, run the six test-only D3→D6 cases in isolated temporary
Core SQLite databases and synthetic Artifact roots (automatically removed afterward):

```shell
uv run python scripts/manual-smoke/m20d7_synthetic_planning_vertical_smoke_test.py
```

To retain the six isolated databases for manual inspection, supply a **new or empty**
directory; this script refuses a nonempty location:

```shell
uv run python scripts/manual-smoke/m20d7_synthetic_planning_vertical_smoke_test.py \
  --runtime-directory /tmp/boberagent-m20d7-acceptance
```

The smoke prints safe Mission/Attempt/Interaction/Plan refs, proposal revision counts,
intent digests, validation/policy/approval decision refs and policy context fingerprints.
It checks automatic ALLOW, assisted entrypoint choice, operator APPROVE and DENY,
hard policy DENY, material UNKNOWN rejection, reopen/reuse, and absence of new
execution-side records. It reuses the same offline synthetic fixtures and assertions
as the automated D7 tests; it needs no Kali, internet, MCP, model, source execution or
target connection. A synthetic acquisition fixture creates baseline Run/Artifact records;
D3–D6 create **no additional execution Run or Artifact**. The smoke stops at D6:
authorization NONE, readiness NOT_ASSESSED, production `execute_plan()` denied.
The six D7 synthetic cases passed; M20-D later closed after the real D8 negative acceptance.

## M20-D8 real retained-source negative planning (offline, opt-in)

From the repository root, select the **existing** completed CERTCC acquisition and
calibrated C1@1/C2@2/C3@2 history. This script does not fetch, re-inspect, open ZIP
bytes, stage or execute source. It requires the current Core schema; it never migrates
the selected database. Run `--check-config` first. Only the second command writes a
Core PlanningAttempt, and only through D3 admission. These commands are manual-only;
normal pytest uses isolated synthetic evidence.

```bash
D8_ARGS=(
  --database /home/bober/boberagent-data/m20-live/core.sqlite3
  --artifact-root /home/bober/boberagent-data/m20-live/artifacts
  --mission-ref mission-m20a-live-b1feccbe94eb483ea3b7a8608d48fa73
  --candidate-ref poc-candidate-1b200c6e7f9b4876bc91131ca505df46
  --acquisition-ref poc-acquisition-2f6a3658a57c42f5ae2252edf1736352
  --c1-inspection-ref poc-inspection-e3bad26d882449e196d9146b841d42e8
  --c2-inspection-ref poc-inspection-c3420f5b09d6450dae2fc10d8b4d230b
  --c3-inspection-ref poc-inspection-b97d53fab5e14b4d953a7671791399fa
  --raw-artifact-ref artifact-032c7c87-c1c2-402a-ba2e-269545766f3a
  --raw-sha256 033fc4b983cff57b9a0debb3491e2638e6598800eb8ae96802021ef7edb232d6
  --manifest-artifact-ref artifact-463d3e1b-e38a-41ed-afb9-b59fc33bee56
  --manifest-sha256 e9e517244eecdedfdb5df9dce43f4792ea5eb1fb763f3e7d48ba5611d229cfe0
  --commit 042e5d9c15fe8312492d2f08063631be58486830
)
uv run python scripts/manual-smoke/m20d8_real_retained_negative_planning_smoke_test.py \
  --check-config "${D8_ARGS[@]}"
```

The operator previously ran the following real mode after read-only preflight:

```bash
uv run python scripts/manual-smoke/m20d8_real_retained_negative_planning_smoke_test.py \
  --real-retained-source "${D8_ARGS[@]}"
```

The operator-reported real run passed with PlanningAttempt
`planning-attempt-f0d274ff3b414e3d8080485a622792af` and request fingerprint
`1fa7adcb92483ab24bb0f2950bb5236700a4ef8761b987b24410b67940a364db`:
`COMPLETED / UNSUPPORTED / REJECTED_UNSUPPORTED`. Plan, decision and Interaction counts
were all zero. Core reopen and identical admission reuse passed; retained upstream
history remained unchanged. The three known blocker categories and further authoritative
C3 reasons were preserved. See the [M20-D closure record](../../docs/m20/M20D_IMPLEMENTATION.md#m20-d-closed-real-retained-source-negative-acceptance)
for exact C2/C3 refs and digests. This negative result is neither safety nor authorization.
**M20-D CLOSED. M20-E1–E3 COMPLETE; real E3 acceptance PASSED.** Production
`execute_plan()` remains denied.

## M20-E5-C confinement-only Kali preflight

**E5-C CLOSED on operator real thirteen-probe acceptance.** The first failed run and
offline correction remain historical; the successful rerun retained digest
`3f01339cf9c473004d1b038fa3b6afe9427897d06ec096f354450b4257ce08b8`.
Rebuild/repin the helper after reviewed native changes, including E5-D, and run fresh
controls for the new operation. This operator-only check is
not E5-H Python preparation and is never invoked by normal pytest or automatically by Codex.
It executes only fixed native synthetic probes. No Python runtime/interpreter probe, venv,
acquired source, package install, target/public network, Core/MCP traffic or execution authority.
Python is only the existing Node/harness control plane. Use a **dedicated confinement-only
Node runtime**, not the running Node's database. Existing non-harness databases are rejected.

Run as the ordinary Node user **inside the already operator-provisioned transient delegated
service**. Its explicitly identified cgroup-v2 parent must be owned/domain, direct tasks empty,
memory/pids enabled and children writable. Do not guess a user slice/root/parent from a PID,
run sudo, change systemd persistently or enable controllers through this harness. The recorded
reconnaissance in M20E5_ACCEPTANCE.md is not proof that the active probes pass.

From the repository root on Kali, choose an explicit absolute dedicated runtime and the exact
existing delegated parent. Build only the repository-owned trusted helper using a pre-existing
static C toolchain; do not install missing prerequisites. Example operator commands:

The installed helper must be a regular executable with an explicit mode such as **0755**,
never group/world-writable or setuid/setgid. **Every ancestor directory**, including the
runtime and tools directories, must be non-group/world-writable and not a symlink. Existing
ancestors must already satisfy this prerequisite; do not automatically chmod host directories.
A sticky writable parent such as `/tmp` is not a suitable installed-helper location for this
manual harness. The preflight enforces this before creating runtime state or launching probes;
production `_trusted_tool()` remains unchanged and still checks all its existing prerequisites.
Use explicit installation modes rather than relying on the shell's umask. Compile in a private
temporary build directory, then install the finished binary into the trusted parent chain:

For the requester-death fix, reuse the operator's already verified runtime/delegated parent
inside the existing transient service; rebuild the helper and recompute its pin with the
commands below. Do not reuse its old SHA-256 or change host-wide delegation. The first run
passed eleven probes, then lost requester-death JSON because the independent supervisor
returned through `_exit` without flushing. SIGKILL alone is not proof. The subsequent
operator rerun closed C with **all thirteen**, including supervisor_death.

```bash
set -eu
E5_RUNTIME=/absolute/operator-selected/e5c-preflight-runtime
E5_CGROUP_PARENT=/sys/fs/cgroup/explicitly-delegated-empty-parent
E5_HELPER="$E5_RUNTIME/tools/e5-confinement-helper"
install -d -m 0755 -- "$E5_RUNTIME" "$E5_RUNTIME/tools"
E5_BUILD_DIR=$(mktemp -d)
cc -static -O2 -Wall -Wextra -Werror \
  -o "$E5_BUILD_DIR/e5-confinement-helper" \
  packages/execution-node/src/boberagent_execution_node/preparation/native/e5_confinement.c
install -m 0755 -- "$E5_BUILD_DIR/e5-confinement-helper" "$E5_HELPER"
rm -- "$E5_BUILD_DIR/e5-confinement-helper"
rmdir -- "$E5_BUILD_DIR"
E5_HELPER_SHA256=$(sha256sum -- "$E5_HELPER" | cut -d ' ' -f 1)
E5_BWRAP_SHA256=$(sha256sum -- /usr/bin/bwrap | cut -d ' ' -f 1)

uv run python scripts/manual-smoke/m20e5c_confinement_smoke_test.py \
  --check-confinement \
  --node-runtime-directory "$E5_RUNTIME" \
  --delegated-cgroup-parent "$E5_CGROUP_PARENT" \
  --trusted-helper "$E5_HELPER" \
  --helper-sha256 "$E5_HELPER_SHA256" \
  --bubblewrap /usr/bin/bwrap \
  --bubblewrap-sha256 "$E5_BWRAP_SHA256"
```

Replace both placeholder directories before running. This command performs no systemd/delegation
provisioning. Missing static toolchain, bubblewrap, delegated controls, writable child kill,
memory.peak or a failed active property stops acceptance. Keep the JSON PASS/FAIL summary and
the dedicated Node journal; output includes logical probe identities via persisted evidence,
profile, event/peak facts and empty-group results, never raw environment/credentials/host stderr.
Failures identify closed `probe`, reason and `stage` (e.g. `requester_death`,
`DESCENDANT_CONTAINMENT_UNAVAILABLE`, `report_or_cleanup`) instead of raw validation input.
Helper filesystem failures use `reason=CONFINEMENT_UNAVAILABLE`, `probe=null` and typed
`stage=helper_file_mode` or `helper_parent_trust`; no raw path, environment or stderr is printed.
Every probe must PASS with attachment-before-exec and group-empty proof. Expected tiny pids/OOM/
output/deadline hits are intentional mechanism tests, not runtime construction failures.

Optional real Linux pytest (same explicitly provisioned environment, not portable CI):

```bash
BOBERAGENT_E5_CGROUP_PARENT="$E5_CGROUP_PARENT" \
BOBERAGENT_E5_HELPER="$E5_HELPER" \
BOBERAGENT_E5_HELPER_SHA256="$E5_HELPER_SHA256" \
BOBERAGENT_E5_BWRAP_SHA256="$E5_BWRAP_SHA256" \
uv run pytest packages/execution-node/tests/test_runtime_confinement_linux.py
```

Without opt-in delegation that test skips; a skip is not enforcement proof. Supplying an
invalid/broken opt-in configuration fails, not skips. Do not run either real mode automatically
during implementation. After even a successful check the runtime remains UNAVAILABLE / NOT READY;
E5-D is now implemented offline, real provenance acceptance required; E5-E–H and M20-F
have not begun. No production execute_plan() authorization is created.

## M20-E5-D trusted CPython provenance-only Kali preflight

**IMPLEMENTED OFFLINE; real Kali acceptance REQUIRED.** Use the operator's already
preprovisioned uv-managed CPython **3.12** distribution, not Kali's system 3.13 and not
an install/download/discovery operation. No venv/source preparation, Secret, target access,
Core/MCP traffic, new authority, Resource or READY state. This is manual-only; portable
pytest uses synthetic material, never automatically invokes a real candidate.

Use the existing repository control-plane `.venv/bin/python -B`; it is not the candidate.
The control plane must not create caches in the selected base distribution during proof.
Keep other writers quiescent; concurrent legitimate cache/library changes also invalidate
the full manifest. Do not exclude import-visible caches to mask that drift.
Run as the intended ordinary Node user in the already delegated service. Supply explicit
canonical absolute roots: no `/lib` alias, writable/symlink substitution parent, `/tmp`,
PATH or active-venv interpreter selection. Root/Node-owned files and ancestors must be
non-group/world-writable. A typical candidate is an already provisioned
`cpython-3.12.14-linux-x86_64-gnu` directory, but its name proves nothing and is not hardcoded.
Do not install `/usr/bin/python3.12` or replace host Python.

First run **non-executing** inventory and independently review that this is the operator's
trusted distribution before approving its observed pins. Inventory is not vendor attestation
or a success/readiness result. It checks/hashes all base bin/lib bytes and bounded
metadata, then selects the typed non-GUI projection and complete retained support closure.
Optional Tkinter/Tcl/Tk is excluded structurally, not by accepting its external RPATH.
Native ownership is determined by independent supported/unsupported-root reachability.
The offline membership correction excludes both reported internal Tcl/Tk libraries
when unsupported-only; a genuinely shared library remains selected and its absolute
RPATH still rejects. Exact internal bindings, unknown ownership, aliases and complete
base partition checks stay fail-closed. This is not real Kali acceptance: rerun the
inventory command below, review fresh pins, and report any further genuine rejection.
The complete site-packages and ensurepip namespaces (including bundled wheels,
metadata and caches) are excluded as PACKAGE_MANAGER. Structurally identified pip
console launchers/aliases and Tk-dependent idle launchers are also absent; normal
pydoc/2to3/config tooling remains selected. Excluded files still undergo full trust,
bounded hashing and ELF validation. Do not delete or modify the provisioned base.
Unknown/malformed native material remains fail-closed. Unsupported layout,
unknown/missing library, metadata, mode or ownership fails closed. Do not chmod host-wide
parents automatically; a provisioned runtime with unsafe modes needs explicit operator review.

```bash
set -eu
E5_PYTHON_ROOT=/absolute/operator-selected/uv-cpython-3.12-distribution
E5_LIBRARY_ROOT=/usr/lib/x86_64-linux-gnu  # explicit canonical trusted library root
.venv/bin/python -B scripts/manual-smoke/m20e5d_python_provenance_smoke_test.py \
  --inventory-only \
  --distribution-root "$E5_PYTHON_ROOT" \
  --system-library-root "$E5_LIBRARY_ROOT"
```

Copy the **reviewed** `manifest_sha256` and `interpreter_sha256` into the variables below.
Output also includes `manifest_version=m20-e5-python-distribution@2`, the profile and
profile/base/selected/excluded/projection digests, and an excluded-entry count. Keep those
pins with the acceptance record. Historical v1 pins are not v2 pins and must not be
silently reused. [ADR 0022](../../docs/adr/0022-m20-e5-trusted-python-runtime-projection.md)
explains the exact view; E5-E must later expose the same view, not the whole `lib` tree.
Fresh profile `@1` pins bind both TKINTER_TCL_TK and PACKAGE_MANAGER. Historical
Tk-only profile evidence remains readable unchanged, but cannot authorize the
current view. Review fresh pins even when the interpreter hash is unchanged.
This offline package-manager compatibility change is not real Kali acceptance,
does not begin E5-E and does not make the runtime READY.
Do not use the digest of bin/python alone as the distribution pin. Any runtime/owner/mode/
parent-root drift after inventory causes check/revalidation to reject, not silently repin.

Choose a dedicated absolute provenance runtime, distinct from a live Node or C-only DB.
Every helper ancestor must already be non-group/world-writable; installation uses explicit
0755, not umask. Rebuild the reviewed native helper because D now has a v2 projection mount operation
and the fixed `bwrap --args FD -- /trusted/helper identity-fixture` command-boundary correction;
the previous C helper hash is **not** the new pin. No toolchain/install/delegation provisioning
is performed by the harness:

`--args FD` now carries only options/mounts, not the command. The offline fix prevents
bubblewrap 0.11.0 from treating the outer argv as commandless. Use a newly reviewed
helper SHA-256, not the previously compiled binary/pin. Real Kali provenance must
still be rerun; runtime remains UNAVAILABLE / not READY. Failed fixed-operation
evidence reports bounded `PYTHON_RUNTIME_UNAVAILABLE` rather than a version/ABI mismatch.

```bash
E5_RUNTIME=/absolute/operator-selected/e5d-provenance-runtime
E5_CGROUP_PARENT=/sys/fs/cgroup/explicitly-delegated-empty-parent
E5_MANIFEST_SHA256=REVIEWED_INVENTORY_MANIFEST_SHA256
E5_INTERPRETER_SHA256=REVIEWED_INVENTORY_INTERPRETER_SHA256
E5_HELPER="$E5_RUNTIME/tools/e5-confinement-helper"
install -d -m 0755 -- "$E5_RUNTIME" "$E5_RUNTIME/tools"
E5_BUILD_DIR=$(mktemp -d)
cc -static -O2 -Wall -Wextra -Werror \
  -o "$E5_BUILD_DIR/e5-confinement-helper" \
  packages/execution-node/src/boberagent_execution_node/preparation/native/e5_confinement.c
install -m 0755 -- "$E5_BUILD_DIR/e5-confinement-helper" "$E5_HELPER"
rm -- "$E5_BUILD_DIR/e5-confinement-helper"
rmdir -- "$E5_BUILD_DIR"
E5_HELPER_SHA256=$(sha256sum -- "$E5_HELPER" | cut -d ' ' -f 1)
E5_BWRAP_SHA256=$(sha256sum -- /usr/bin/bwrap | cut -d ' ' -f 1)
.venv/bin/python -B scripts/manual-smoke/m20e5d_python_provenance_smoke_test.py \
  --check-provenance \
  --distribution-root "$E5_PYTHON_ROOT" \
  --system-library-root "$E5_LIBRARY_ROOT" \
  --manifest-sha256 "$E5_MANIFEST_SHA256" \
  --interpreter-sha256 "$E5_INTERPRETER_SHA256" \
  --node-runtime-directory "$E5_RUNTIME" \
  --delegated-cgroup-parent "$E5_CGROUP_PARENT" \
  --trusted-helper "$E5_HELPER" --helper-sha256 "$E5_HELPER_SHA256" \
  --bubblewrap /usr/bin/bwrap --bubblewrap-sha256 "$E5_BWRAP_SHA256"
```

Keep the bounded PASS/FAIL summary and the dedicated Node journal/dossier. PASS must show
exact CPython 3.12.x/Linux/x86_64, v2 manifest/projection/interpreter/root pins, completed fixed
confined identity, all thirteen controls and successful full revalidation, with
`resource_created=false`, `runtime=UNAVAILABLE`, `ready=false`. Repeating the same explicit
configuration creates fresh proof while retaining prior history; no automatic replay grants
authority. The host-only harness does **not** fabricate an expired/fake E4 permit or Resource.
Resource-bound production evidence remains owned by the existing authenticated E5-B claim
and ledger API; later construction needs fresh eligible preparation authority.

Optional safe negative check: run only `--inventory-only` on an **operator-created disposable
copy**, pin it, then modify a stdlib file in that copy and rerun with the original pins.
It must reject before candidate execution. Do not mutate the trusted installed distribution,
system Python, live Resource or retained source. Ordinary CI already covers byte/mode/root
substitution and identity mismatches. This task does not automatically run a Kali check.
E5-E–H, E6–E9 and M20-F remain unimplemented; production execute_plan() stays denied.

## M20-E3 authenticated opaque Artifact import (operator-only)

E3 has **passed real Core↔Kali acceptance**, including identical import after a Kali Node
restart using the same persistent runtime. This harness uses the
existing harmless synthetic D7 fixture to produce a supported D→E2 chain and two retained
small Artifacts in an **explicit dedicated Core runtime directory**. `--check-config` may
create that local fixture and E2 attempt, then checks the real Node handshake, current permit
applicability, protocol support and Core bytes; it transfers no Artifact bytes. Reuse the
same directory and Node ID for the real mode and any later replay/restart check. It never
uses the retained CERTCC D8 UNSUPPORTED chain as a positive fixture.

On Kali, start the normal MCP Node with an isolated runtime directory. E3 admission is
built into the Node; no source-preparation capability path, tool, or target is needed:

```shell
export BOBERAGENT_MCP_TOKEN='<dedicated-test-token>'
RUNTIME='/var/lib/boberagent-m20e3-smoke'
sudo mkdir -p "$RUNTIME"
sudo chown "$USER":"$USER" "$RUNTIME"
uv run boberagent-node-mcp \
  --runtime-directory "$RUNTIME" \
  --bind-host 0.0.0.0 --port 8443 \
  --tls-certificate /etc/boberagent/node.crt \
  --tls-private-key /etc/boberagent/node.key
```

On WSL/Core, set the same bearer token in the process or ignored `.env.local` and substitute
the Node ID printed at startup. The first command is the required no-byte preflight:

```shell
export BOBERAGENT_MCP_TOKEN='<same-dedicated-test-token>'
uv run python scripts/manual-smoke/m20e3_preparation_import_smoke_test.py \
  --check-config \
  --core-runtime-directory /absolute/path/to/m20e3-core-smoke \
  --endpoint https://192.168.0.11:8443/mcp \
  --node-id 'node-from-Kali-startup' \
  --ca-file /absolute/path/to/lab-ca.pem
```

After reviewing the printed exact ArtifactRefs, SHA-256 hashes, sizes, RunRef and permit,
replace `--check-config` with `--real-artifact-import` using the same arguments. That command
dispatches only the E3 admission and imports the two opaque Artifacts; it disconnects,
reconnects and verifies identical import replay. For Node-restart verification, restart the
same Kali Node runtime and run the same real-import command again. The Node's managed
`imported-inputs` store is separate from its produced-evidence spool. No extraction,
workspace, Resource, venv, process, target/package/listener network, Secret grant or PoC
execution occurs. For an explicitly isolated plaintext lab only, replace `--ca-file` with
`--allow-insecure-remote-transport` and use `http://`; never send the bearer token over an
untrusted plaintext network. This manual smoke is not run by pytest or automatically by Codex.

The script prints the permit's `not_before`, `expires_at` and remaining validity before
import/replay. A warning under 60 seconds is operator guidance, not a changed authority
rule. Positive restart/replay acceptance must complete while the PreparationPermit is
currently applicable. The baseline E2 permit lifetime is **15 minutes**; after expiry,
fail-closed inapplicability is expected and does **not** indicate an Artifact replay defect.
Use a fresh dedicated Core runtime if a new permit is needed; never bypass the expiry.
Keep `RUNTIME` set to the same non-empty path across Kali restarts. The Node CLI rejects
an explicitly empty or whitespace-only `--runtime-directory` before initialization.

The operator's acceptance used Node `node-38195224-06e1-480c-a7f9-fdacd26861d6`,
Preparation `preparation-7a156e8a25c647b591589689a0d374c3` and Run
`run-preparation-287e2192955a4caf9b92c6fffe55ffda`. Both exact Artifacts verified
on the first import and again after Node restart against the same Core runtime; see the
[E3 acceptance record](../../docs/m20/M20E_ACCEPTANCE.md#e3-real-corekali-acceptance-passed).
**M20-E3 COMPLETE.** E4 real acceptance is recorded below; M20-E remains OPEN, and
E5–E9 and M20-F have not begun. Production
`execute_plan()` remains denied.

## M20-E4 exact source materialization (operator-only; accepted)

The first operator Kali `--check-config` failed closed after successful E3 import because
the closed bubblewrap view omitted usrmerge `/lib64 → usr/lib64` (and other standard
compatibility links), so trusted `/usr/bin/python3` could not find its ELF interpreter.
No source was materialized. A narrow fix reconstructs only allowlisted links, with no
host-root bind. The subsequent real Kali CHECK and explicit MATERIALIZE passed.

Use a new dedicated Core directory and the same Kali Node/runtime setup shown for E3.
The operator separately preflighted Kali Linux 6.12.25, bubblewrap 0.11.0, working
unprivileged user namespaces (`kernel.unprivileged_userns_clone=1`,
`user.max_user_namespaces=15097`), controlled tmpfs writes, blocked host `/etc` writes,
and an isolated network namespace unable to reach the external Node listener. That
exploratory command used `--ro-bind / /`; **the production E4 probe does not**.

On Kali, start the normal MCP Node command above with an isolated, persistent runtime
directory (for example `/var/lib/boberagent-m20e4-smoke`) and the same bearer/TLS
conventions. On WSL/Core, first run the E3 `--check-config` and
`--real-artifact-import` commands above against a fresh
`/absolute/path/to/m20e4-core-smoke` directory. Then, within the same 15-minute permit
window, run E4's no-materialization check:

```shell
uv run python scripts/manual-smoke/m20e4_source_materialization_smoke_test.py \
  --check-config \
  --core-runtime-directory /absolute/path/to/m20e4-core-smoke \
  --endpoint https://kali.example.test:8443/mcp \
  --node-id 'node-from-Kali-startup' \
  --ca-file /absolute/path/to/lab-ca.pem
```

After reviewing the exact retained refs/hashes and real bubblewrap proof, replace
`--check-config` with `--real-materialization` using the same arguments. It publishes only
the harmless synthetic archive already imported by E3 and prints logical identities,
file/byte counts, digest, backend/version/features and PUBLISHED state; it never prints
source contents. Repeating the command revalidates/reuses the exact published tree. No
PoC entrypoint, Python environment, package/network operation or target is invoked.
The harness is manual-only and is not executed by pytest or automatically by Codex. The
operator ran both real E4 modes and repeated MATERIALIZE after a same-runtime Node restart.
Node `node-8207f75c-8905-4fc4-ab96-863e52d9d51a`, Preparation
`preparation-128f07e383204665be425c85da36c6f6` and Run
`run-preparation-5e05d913809a45e7885294c2753ec44a` retained logical materialization
`materialization:93a92832d388166dc92fd53d069fef96d6aaf615d1b57f2562de60aae8683895`:
one file, 336 bytes, tree SHA-256
`3468149cb07e1a4d3058f6a5326758b2b4fa215e53d1c93e784cb4854228a59b`,
`PUBLISHED` both before and after restart. CHECK proved `linux-bubblewrap` /
`bubblewrap 0.11.0` with only the four reported E4 features and created no workspace. See the
[E4 acceptance record](../../docs/m20/M20E_ACCEPTANCE.md#e4-real-corekali-acceptance-passed).

**M20-E4 CLOSED.** M20-E remains OPEN; E5–E9 and M20-F have not begun. Production
`execute_plan()` remains denied.
