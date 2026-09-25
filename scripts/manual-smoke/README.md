Manual cross-machine smoke tests only.

These scripts are not part of the automated pytest suite.
They require an explicitly running Kali Execution Node and lab configuration.
Do not execute them automatically from CI or normal test runs.

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

From the repository root in WSL, supply the required bearer token only through the shell
environment and run the smoke with an explicit, separate on-disk derived-index directory:

```bash
export LM_API_TOKEN='...'
uv run python scripts/manual-smoke/semantic_retrieval_smoke_test.py \
  --knowledge-root /mnt/d/hack/OBSIDIAN/my_notes_v2/BOBER_AGENT \
  --index-directory /tmp/boberagent-m18-semantic-smoke \
  --base-url http://127.0.0.1:1234/v1 \
  --model text-embedding-bge-m3 \
  --api-key-env LM_API_TOKEN \
  --query "authentication is rejected because the directory service requires signed communication"
unset LM_API_TOKEN
```

`LM_API_TOKEN` is secret configuration: **do not commit it** or place its value in Knowledge
Markdown, Qdrant payloads, logs, screenshots, an `.env` file, or command-line arguments. The
repository has no dotenv convention for this smoke; no env file is needed. The script does not
print the token or vectors and does not persist the token. `--timeout`, `--limit`, `--domain`,
`--protocol`, and `--tool` are optional; filters narrow the real candidate set.

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
