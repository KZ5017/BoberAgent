"""Interaction, Checkpoint, Event, and structured logging test services."""

import asyncio

import pytest
from boberagent_contracts import (
    Checkpoint,
    CheckpointRef,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    InteractionType,
)
from boberagent_sdk import InteractionUnavailable
from boberagent_sdk.testing import FakeExecutionContext, LogLevel


def test_preconfigured_interaction_response_and_missing_response() -> None:
    context = FakeExecutionContext()
    request = InteractionRequest(
        interaction_id=InteractionRef("interaction-one"),
        run_ref=context.invocation.run_id,
        interaction_type=InteractionType.CHOICE,
        title="Choose",
        description="Choose a safe test option",
        input_schema={"type": "string", "enum": ["stop", "continue"]},
        resume_semantics="resume",
        requested_at=context.clock.now(),
    )
    response = InteractionResponse(
        interaction_ref=request.interaction_id,
        run_ref=context.invocation.run_id,
        responded_at=context.clock.now(),
        value="continue",
    )
    context.interactions.respond_with(response)
    try:
        assert asyncio.run(context.interactions.request(request)) == response
        with pytest.raises(InteractionUnavailable, match="interaction-one"):
            asyncio.run(context.interactions.request(request))
    finally:
        context.close()


def test_checkpoint_save_and_load_uses_contract_object() -> None:
    context = FakeExecutionContext()
    checkpoint = Checkpoint(
        checkpoint_id=CheckpointRef("checkpoint-one"),
        run_ref=context.invocation.run_id,
        phase="awaiting_input",
        state={"attempt": 2, "variants": ["one", "two"]},
        created_at=context.clock.now(),
    )
    try:
        asyncio.run(context.checkpoints.save(checkpoint))
        assert asyncio.run(context.checkpoints.load(checkpoint.checkpoint_id)) == checkpoint
        assert asyncio.run(context.checkpoints.load(CheckpointRef("checkpoint-missing"))) is None
    finally:
        context.close()


def test_progress_and_structured_log_are_recorded() -> None:
    context = FakeExecutionContext()
    try:
        event = asyncio.run(
            context.events.progress(
                message="Halfway", current=1, total=2, metadata={"phase": "test"}
            )
        )
        context.logger.info("Produced progress", event_ref=str(event.event_id))
        assert event.type == "capability.progress"
        assert event.source_ref == context.invocation.run_id
        assert not hasattr(context.events, "emit_any_event_type")
        assert context.logger.records[0].level is LogLevel.INFO
        assert context.logger.records[0].fields == {"event_ref": str(event.event_id)}
    finally:
        context.close()
