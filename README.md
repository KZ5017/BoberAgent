# BoberAgent

BoberAgent is a capability-driven orchestration platform for authorized penetration testing,
security labs, and CTF environments. The project is currently in its architecture and repository
bootstrap stage; application behavior has not been implemented yet.

The authoritative design specifications live in [`docs/`](docs/). Start with
[`docs/00_PROJECT_CONTEXT.md`](docs/00_PROJECT_CONTEXT.md) and
[`docs/01_SYSTEM_ARCHITECTURE.md`](docs/01_SYSTEM_ARCHITECTURE.md), then read the normative document
for the area being changed. [`AGENTS.md`](AGENTS.md) contains mandatory rules for coding agents.

## Repository layout

- `packages/contracts`: transport-independent platform contracts (skeleton only)
- `packages/sdk`: capability author SDK (skeleton only)
- `packages/core`: assessment meaning and orchestration (skeleton only)
- `packages/execution-node`: execution mechanics (skeleton only)
- `capabilities`: future capability packages
- `knowledge`: future procedures and curated reference material
- `tests`: architecture, integration, and end-to-end test suites
- `docs`: architecture, specifications, plans, and ADRs

## Development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

Install the complete workspace and development tools:

```shell
uv sync --all-packages --dev
```

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
