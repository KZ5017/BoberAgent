# BoberAgent

BoberAgent is a capability-driven orchestration platform for authorized penetration testing,
security labs, and CTF environments. The project is being built in reviewed bootstrap milestones.
It currently includes Contract v1, Core persistence, the Capability SDK, the local Execution Node,
transport-neutral in-memory communication, and durable Node-to-Core Artifact synchronization.
The first production capability, `network.service_discovery`, is implemented behind the SDK and
currently uses Nmap as its managed provider.
Core can now discover Node-advertised providers and route explicit Capability invocations through
the existing transport using persisted, deterministic routing decisions. Transported terminal
Results can be durably ingested into Core's append-only Observation Store and reduced into
materialized Service state.
The same transport-neutral protocol now has a bearer-authenticated MCP Streamable HTTP carrier for
real Core-to-Execution-Node network deployments; the in-memory adapter remains available for fast
local tests.
Core also includes a durable, explicitly pumped sequential Workflow Engine and a thin operator CLI
that exposes the existing Core application services without becoming a second orchestration layer.

The authoritative design specifications live in [`docs/`](docs/). Start with
[`docs/00_PROJECT_CONTEXT.md`](docs/00_PROJECT_CONTEXT.md) and
[`docs/01_SYSTEM_ARCHITECTURE.md`](docs/01_SYSTEM_ARCHITECTURE.md), then read the normative document
for the area being changed. [`AGENTS.md`](AGENTS.md) contains mandatory rules for coding agents.

## Repository layout

- `packages/contracts`: transport-independent Capability Contract v1 models
- `packages/sdk`: capability author interfaces and in-memory testing utilities
- `packages/core`: SQLite-backed canonical state and initial Observation materialization
- `packages/cli`: thin operator-facing command line over public Core services
- `packages/execution-node`: local execution runtime, managed services, and durable outboxes
- `packages/transport`: neutral protocol envelopes/interfaces and the in-memory adapter
- `packages/transport-mcp`: real MCP Streamable HTTP transport adapter
- `capabilities`: production capability packages, beginning with network service discovery
- `knowledge`: future procedures and curated reference material
- `tests`: architecture, integration, and end-to-end test suites
- `docs`: architecture, specifications, plans, and ADRs

## Development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

Install the complete workspace and development tools:

```shell
uv sync --all-packages --dev
```

For optional local operator credentials, copy the committed [`.env.example`](.env.example) to
repo-root `.env.local` and fill in the needed values privately. `.env.local` is Git-ignored;
**never commit it or real API keys**. The operator CLI (when run from the repository root) and the
manual semantic-retrieval smoke script read it at startup. Existing process environment values
take precedence. Set `BOBERAGENT_ENV_FILE` to an explicit path to use a different file; a relative
path is resolved from the selected project root. A missing default file is harmless, and automated
tests/CI do not need one. For the current semantic smoke, the only template variable is
`LM_API_TOKEN`; populate it yourself in `.env.local` before running the smoke.

This file is local application configuration, **not** the M16 Mission-owned Secret/Credential
Store. Core/domain libraries do not search for env files or mutate `os.environ` on import. The
operator CLI receives a merged configuration mapping; secrets are not written to Core by this
loader.

Canonical quality commands:

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Focused test commands:

```shell
uv run pytest tests/architecture
uv run pytest tests/integration
uv run pytest tests/end_to_end
```

## Operator CLI

The `boberagent` command always requires an explicit Core SQLite database path. It does not choose
or create a database in the current working directory implicitly. Initialize a new database, or
upgrade an existing one through the migration history, before using stateful commands:

```shell
uv run boberagent --database /srv/boberagent/core.db core init
uv run boberagent --database /srv/boberagent/core.db core status
```

Create the initial Mission and its scoped Asset, then inspect them:

```shell
uv run boberagent --database /srv/boberagent/core.db mission create \
  --mission-ref mission-lab --name "Authorized lab"
uv run boberagent --database /srv/boberagent/core.db asset add \
  --mission mission-lab --asset-ref asset-web --address 192.0.2.10
uv run boberagent --database /srv/boberagent/core.db mission list
uv run boberagent --database /srv/boberagent/core.db asset list --mission mission-lab
uv run boberagent --database /srv/boberagent/core.db provider list
```

Workflow definitions are validated JSON files using the M11 domain model. The initial format is
deliberately static and sequential—there is no templating, expression language, or inline code:

```json
{
  "definition_id": "service-discovery",
  "version": "1",
  "steps": [
    {
      "step_id": "discover",
      "capability_id": "network.service_discovery",
      "operation": "discover",
      "inputs": {
        "asset_ref": "asset-web",
        "profile": "quick",
        "timeout_seconds": 120
      }
    }
  ]
}
```

Workflow dispatch requires an explicit MCP endpoint and Node identity. The bearer credential is read
from an environment variable and is never stored in the Core database. Global options precede the
command group:

```shell
export BOBERAGENT_MCP_BEARER_TOKEN='<token>'

uv run boberagent \
  --database /srv/boberagent/core.db \
  --node-url https://node.example.test/mcp \
  --node-id node-kali-01 \
  workflow start --mission mission-lab --definition workflow.json

uv run boberagent \
  --database /srv/boberagent/core.db \
  --node-url https://node.example.test/mcp \
  --node-id node-kali-01 \
  workflow advance workflow-01
```

The Workflow Engine remains explicitly pumped: run `workflow advance` again to receive pending
Node results and reconcile the next durable state. Read-only inspection needs no live Node:

```shell
uv run boberagent --database /srv/boberagent/core.db workflow status workflow-01
uv run boberagent --database /srv/boberagent/core.db run show run-01
uv run boberagent --database /srv/boberagent/core.db service list --asset asset-web
```

The M12 command-scoped MCP composition refreshes one explicitly selected Node and handles
invocation plus Event/Result delivery. It does not run a daemon or automatically pump Artifact byte
synchronization; the existing Artifact synchronization path remains a separate operational concern.

Add `--json` before the command group for stable machine-readable output. Normal operator errors use
deterministic non-zero exit codes and do not emit tracebacks. Use `boberagent --help` and the command
group help for the complete initial surface.

Normal automated tests use local fixtures and the in-memory transport. The scripts under
[`scripts/manual-smoke/`](scripts/manual-smoke/) are separate, opt-in WSL-to-Kali validation tools;
they are not normal CLI configuration sources and are not collected by pytest.
