"""M15 structured human-interaction Contract validation."""

from datetime import UTC, datetime

import pytest
from boberagent_contracts import (
    MAX_INTERACTION_TEXT_LENGTH,
    CapabilityRunRef,
    InteractionOption,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    InteractionType,
    JsonObject,
    MissionRef,
    validate_interaction_response,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def _request(interaction_type: InteractionType) -> InteractionRequest:
    schema: JsonObject
    options: tuple[InteractionOption, ...] = ()
    if interaction_type is InteractionType.CONFIRMATION:
        schema = {"type": "boolean"}
    elif interaction_type is InteractionType.TEXT:
        schema = {"type": "string", "minLength": 1, "maxLength": 32}
    else:
        schema = {"type": "string", "enum": ["continue", "stop"]}
        options = (
            InteractionOption(option_id="continue", label="Continue"),
            InteractionOption(option_id="stop", label="Stop"),
        )
    return InteractionRequest(
        interaction_id=InteractionRef(f"interaction-{interaction_type.value}"),
        run_ref=CapabilityRunRef("run-interaction"),
        mission_ref=MissionRef("mission-interaction"),
        interaction_type=interaction_type,
        title="Operator input",
        description="Provide a harmless test value.",
        input_schema=schema,
        resume_semantics="same_run",
        requested_at=NOW,
        options=options,
    )


@pytest.mark.parametrize(
    ("interaction_type", "value"),
    [
        (InteractionType.CONFIRMATION, False),
        (InteractionType.TEXT, "test-host"),
        (InteractionType.SINGLE_CHOICE, "continue"),
    ],
)
def test_supported_response_types_validate_and_round_trip(
    interaction_type: InteractionType, value: bool | str
) -> None:
    request = _request(interaction_type)
    response = InteractionResponse(
        interaction_ref=request.interaction_id,
        run_ref=request.run_ref,
        responded_at=NOW,
        value=value,
    )

    assert validate_interaction_response(request, response) == response
    assert InteractionRequest.model_validate_json(request.model_dump_json()) == request
    assert InteractionResponse.model_validate_json(response.model_dump_json()) == response
    with pytest.raises(ValidationError, match="frozen"):
        request.title = "changed"


def test_text_and_choice_bounds_reject_unsafe_values() -> None:
    with pytest.raises(ValidationError, match="maxLength"):
        InteractionRequest(
            interaction_id=InteractionRef("interaction-long-text"),
            run_ref=CapabilityRunRef("run-interaction"),
            mission_ref=MissionRef("mission-interaction"),
            interaction_type=InteractionType.TEXT,
            title="Text",
            description="Bounded input",
            input_schema={"type": "string", "maxLength": MAX_INTERACTION_TEXT_LENGTH + 1},
            resume_semantics="same_run",
            requested_at=NOW,
        )
    with pytest.raises(ValidationError, match="option IDs"):
        InteractionRequest(
            interaction_id=InteractionRef("interaction-duplicate-choice"),
            run_ref=CapabilityRunRef("run-interaction"),
            mission_ref=MissionRef("mission-interaction"),
            interaction_type=InteractionType.SINGLE_CHOICE,
            title="Choice",
            description="Bounded choice",
            input_schema={"type": "string", "enum": ["same", "same"]},
            resume_semantics="same_run",
            requested_at=NOW,
            options=(
                InteractionOption(option_id="same", label="First"),
                InteractionOption(option_id="same", label="Second"),
            ),
        )

    request = _request(InteractionType.SINGLE_CHOICE)
    response = InteractionResponse(
        interaction_ref=request.interaction_id,
        run_ref=request.run_ref,
        responded_at=NOW,
        value="arbitrary-shell-like-value",
    )
    with pytest.raises(ValueError, match="available option"):
        validate_interaction_response(request, response)
