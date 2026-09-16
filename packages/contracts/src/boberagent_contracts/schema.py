"""Reproducible JSON Schema bundle generation for exchanged Contract models."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, JsonSchemaValue, models_json_schema

from .artifact import ArtifactDescriptor
from .capability import CapabilityDefinition, OperationDefinition
from .checkpoint import Checkpoint
from .diagnostic import Diagnostic
from .effect import Effect
from .event import Event
from .execution_plan import ExecutionPlan
from .finding import Finding
from .interaction import InteractionRequest, InteractionResponse
from .invocation import CapabilityInvocation
from .observation import Observation
from .resource import ResourceDescriptor
from .result import CapabilityOutcome, CapabilityResult
from .run import CapabilityRun
from .session import SessionDescriptor
from .version import CONTRACT_VERSION

EXCHANGED_MODEL_TYPES: tuple[type[BaseModel], ...] = (
    CapabilityDefinition,
    OperationDefinition,
    CapabilityInvocation,
    CapabilityRun,
    CapabilityOutcome,
    CapabilityResult,
    Observation,
    Finding,
    ArtifactDescriptor,
    Effect,
    Diagnostic,
    ResourceDescriptor,
    SessionDescriptor,
    Event,
    InteractionRequest,
    InteractionResponse,
    Checkpoint,
    ExecutionPlan,
)


def contract_schema_bundle() -> JsonSchemaValue:
    """Build one definitions-based JSON Schema document for Contract v1."""

    inputs: Sequence[tuple[type[BaseModel], JsonSchemaMode]] = tuple(
        (model_type, "validation") for model_type in EXCHANGED_MODEL_TYPES
    )
    _model_schemas, bundle = models_json_schema(
        inputs,
        by_alias=True,
        ref_template="#/$defs/{model}",
        title=f"BoberAgent Capability Contract {CONTRACT_VERSION}",
    )
    return bundle


def contract_schema_json() -> str:
    """Render the schema bundle deterministically for fixtures and source control."""

    return json.dumps(contract_schema_bundle(), indent=2, sort_keys=True) + "\n"


def write_contract_schema(destination: Path) -> None:
    """Write the reproducible schema bundle to a caller-selected path."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contract_schema_json(), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for schema export."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Output path for the JSON Schema bundle")
    arguments = parser.parse_args(argv)
    write_contract_schema(cast(Path, arguments.destination))
    return 0
