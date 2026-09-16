"""JSON Schema generation and reproducibility tests."""

import json
from pathlib import Path

from boberagent_contracts.schema import (
    EXCHANGED_MODEL_TYPES,
    contract_schema_bundle,
    contract_schema_json,
)

CONTRACT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_SCHEMA = CONTRACT_PACKAGE_ROOT / "schemas/contract-v1.schema.json"


def test_every_exchanged_model_generates_json_schema() -> None:
    for model_type in EXCHANGED_MODEL_TYPES:
        schema = model_type.model_json_schema()
        assert schema["title"] == model_type.__name__


def test_schema_bundle_contains_required_contract_models() -> None:
    definitions = contract_schema_bundle()["$defs"]

    assert isinstance(definitions, dict)
    assert {
        "CapabilityDefinition",
        "CapabilityInvocation",
        "CapabilityRun",
        "CapabilityResult",
        "Observation",
        "ExecutionPlan",
    } <= definitions.keys()


def test_committed_schema_bundle_is_reproducible() -> None:
    generated = contract_schema_json()

    assert json.loads(generated) == json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
    assert generated == COMMITTED_SCHEMA.read_text(encoding="utf-8")
