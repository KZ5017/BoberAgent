"""Human/external interaction request and response models."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, model_validator

from ._base import ContractModel, JsonObject, JsonValue, NonEmptyStr, ShortStr, SymbolicName
from .enums import InteractionType
from .refs import ArtifactRef, CapabilityRunRef, InteractionRef, SecretRef


class InteractionRequest(ContractModel):
    """Structured assistance request owned by an active CapabilityRun."""

    interaction_id: InteractionRef
    run_ref: CapabilityRunRef
    interaction_type: InteractionType
    title: ShortStr
    description: NonEmptyStr
    input_schema: JsonObject
    resume_semantics: SymbolicName
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def validate_input_schema(self) -> Self:
        schema_type = self.input_schema.get("type")
        if not isinstance(schema_type, str) or not schema_type:
            raise ValueError("interaction input_schema must declare a non-empty top-level type")
        return self


class InteractionResponse(ContractModel):
    """Validated response data or a secure logical input reference."""

    interaction_ref: InteractionRef
    run_ref: CapabilityRunRef
    responded_at: AwareDatetime
    value: JsonValue = None
    secret_ref: SecretRef | None = None
    artifact_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def exactly_one_response_source(self) -> Self:
        supplied = sum(
            (
                self.value is not None,
                self.secret_ref is not None,
                self.artifact_ref is not None,
            )
        )
        if supplied != 1:
            raise ValueError("exactly one response value, secret_ref, or artifact_ref is required")
        return self
