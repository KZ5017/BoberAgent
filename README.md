# BoberAgent

BoberAgent is a capability-driven orchestration platform for authorized penetration testing,
security labs, and CTF environments. The project is being built in reviewed bootstrap milestones.
It currently includes Contract v1, Core persistence, the Capability SDK, the local Execution Node,
and a transport-neutral protocol with an in-memory development adapter.

The authoritative design specifications live in [`docs/`](docs/). Start with
[`docs/00_PROJECT_CONTEXT.md`](docs/00_PROJECT_CONTEXT.md) and
[`docs/01_SYSTEM_ARCHITECTURE.md`](docs/01_SYSTEM_ARCHITECTURE.md), then read the normative document
for the area being changed. [`AGENTS.md`](AGENTS.md) contains mandatory rules for coding agents.

## Repository layout

- `packages/contracts`: transport-independent Capability Contract v1 models
- `packages/sdk`: capability author interfaces and in-memory testing utilities
- `packages/core`: SQLite-backed canonical state and initial Observation materialization
- `packages/execution-node`: local execution runtime, managed services, and durable outboxes
- `packages/transport`: neutral protocol envelopes/interfaces and the in-memory adapter
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
