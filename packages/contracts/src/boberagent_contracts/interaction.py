"""Human/external interaction request and response models."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from ._base import FrozenContractModel, JsonObject, JsonValue, NonEmptyStr, ShortStr, SymbolicName
from .enums import InteractionType
from .refs import (
    ArtifactRef,
    CapabilityRunRef,
    InteractionRef,
    MissionRef,
    SecretRef,
    WorkflowRunRef,
)

MAX_INTERACTION_TEXT_LENGTH = 4096
MAX_INTERACTION_OPTIONS = 32


class InteractionOption(FrozenContractModel):
    """One safe, stable operator choice; values are data, never executable input."""

    option_id: SymbolicName
    label: ShortStr
    description: NonEmptyStr | None = None


class InteractionRequest(FrozenContractModel):
    """Structured assistance request owned by an active CapabilityRun."""

    interaction_id: InteractionRef
    run_ref: CapabilityRunRef
    mission_ref: MissionRef
    workflow_run_ref: WorkflowRunRef | None = None
    workflow_step_ref: SymbolicName | None = None
    interaction_type: InteractionType
    title: ShortStr
    description: NonEmptyStr
    input_schema: JsonObject
    resume_semantics: SymbolicName
    requested_at: AwareDatetime
    options: tuple[InteractionOption, ...] = Field(default=(), max_length=MAX_INTERACTION_OPTIONS)
    default_value: JsonValue = None

    @model_validator(mode="after")
    def validate_input_schema(self) -> Self:
        schema_type = self.input_schema.get("type")
        if not isinstance(schema_type, str) or not schema_type:
            raise ValueError("interaction input_schema must declare a non-empty top-level type")
        if self.interaction_type is InteractionType.CONFIRMATION:
            if schema_type != "boolean" or self.options:
                raise ValueError("confirmation interaction requires boolean input and no options")
            if self.default_value is not None and not isinstance(self.default_value, bool):
                raise ValueError("confirmation default must be a boolean")
        elif self.interaction_type is InteractionType.TEXT:
            if schema_type != "string" or self.options:
                raise ValueError("text interaction requires string input and no options")
            maximum = self.input_schema.get("maxLength")
            if not isinstance(maximum, int) or not 1 <= maximum <= MAX_INTERACTION_TEXT_LENGTH:
                raise ValueError(
                    f"text interaction maxLength must be between 1 and "
                    f"{MAX_INTERACTION_TEXT_LENGTH}"
                )
            if self.default_value is not None and not isinstance(self.default_value, str):
                raise ValueError("text default must be a string")
        elif self.interaction_type is InteractionType.SINGLE_CHOICE:
            if schema_type != "string" or not self.options:
                raise ValueError("single-choice interaction requires string input and options")
            option_ids = tuple(option.option_id for option in self.options)
            if len(option_ids) != len(set(option_ids)):
                raise ValueError("single-choice option IDs must be unique")
            declared = self.input_schema.get("enum")
            if declared != list(option_ids):
                raise ValueError("single-choice input enum must match option IDs in order")
            if self.default_value is not None and self.default_value not in option_ids:
                raise ValueError("single-choice default must identify an available option")
        return self


class InteractionResponse(FrozenContractModel):
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


def validate_interaction_response(
    request: InteractionRequest,
    response: InteractionResponse,
) -> InteractionResponse:
    """Validate the three non-secret M15 response shapes against their durable request."""

    if response.interaction_ref != request.interaction_id:
        raise ValueError("Interaction response identifies a different request")
    if response.run_ref != request.run_ref:
        raise ValueError("Interaction response belongs to a different CapabilityRun")
    if response.secret_ref is not None or response.artifact_ref is not None:
        raise ValueError("M15 human interactions accept non-secret structured values only")
    value = response.value
    if request.interaction_type is InteractionType.CONFIRMATION:
        if not isinstance(value, bool):
            raise ValueError("confirmation response must be a boolean")
    elif request.interaction_type is InteractionType.TEXT:
        if not isinstance(value, str):
            raise ValueError("text response must be a string")
        minimum = request.input_schema.get("minLength", 0)
        maximum = request.input_schema["maxLength"]
        if (
            not isinstance(minimum, int)
            or not isinstance(maximum, int)
            or not minimum <= len(value) <= maximum
        ):
            raise ValueError("text response length is outside the requested bounds")
    elif request.interaction_type is InteractionType.SINGLE_CHOICE:
        allowed = {option.option_id for option in request.options}
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("single-choice response must identify an available option")
    else:
        raise ValueError(f"Interaction type is not supported by M15: {request.interaction_type}")
    return response
