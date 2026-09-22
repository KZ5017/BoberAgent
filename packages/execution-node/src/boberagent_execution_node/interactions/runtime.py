"""Durable request state plus bounded live waiters for SDK human interaction."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import (
    CapabilityRunRef,
    InteractionLifecycle,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    JsonObject,
    MissionRef,
    WorkflowRunRef,
)
from boberagent_sdk import ExecutionCancelled, InputError
from pydantic import TypeAdapter

from boberagent_execution_node.events import NodeEventService
from boberagent_execution_node.persistence import InteractionRuntimeRecord, RuntimeStore

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class InteractionConflict(ValueError):
    """A response conflicts with durable interaction identity or lifecycle."""


class InteractionRuntime:
    """Own live waiters while keeping every request/response durable in SQLite."""

    def __init__(self, store: RuntimeStore, *, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._clock = clock
        self._waiters: dict[str, asyncio.Future[InteractionResponse]] = {}
        self._event_services: dict[str, NodeEventService] = {}

    async def request(
        self,
        request: InteractionRequest,
        *,
        run_ref: CapabilityRunRef,
        mission_ref: MissionRef,
        workflow_run_ref: WorkflowRunRef | None,
        events: NodeEventService,
    ) -> InteractionResponse:
        if request.run_ref != run_ref or request.mission_ref != mission_ref:
            raise InputError("Interaction request does not match its ExecutionContext")
        if request.workflow_run_ref != workflow_run_ref:
            raise InputError("Interaction request does not match its Workflow context")
        key = str(request.interaction_id)
        if key in self._waiters:
            raise InputError(f"Interaction already has a live waiter: {request.interaction_id}")
        waiter: asyncio.Future[InteractionResponse] = asyncio.get_running_loop().create_future()
        self._waiters[key] = waiter
        self._event_services[key] = events
        try:
            self._store.begin_interaction(request)
            events.runtime_event(
                "interaction.requested",
                {
                    "interaction_ref": str(request.interaction_id),
                    "request": _json_object_adapter.validate_python(
                        request.model_dump(mode="json")
                    ),
                },
            )
            return await waiter
        finally:
            self._waiters.pop(key, None)
            self._event_services.pop(key, None)

    def accept_response(
        self, response: InteractionResponse
    ) -> tuple[InteractionRuntimeRecord, bool]:
        try:
            record, duplicate = self._store.accept_interaction_response(response)
        except (KeyError, ValueError) as error:
            raise InteractionConflict(str(error)) from error
        waiter = self._waiters.get(str(response.interaction_ref))
        if not duplicate:
            if waiter is None or waiter.done():
                raise InteractionConflict("Interaction no longer has a live suspended capability")
            waiter.set_result(response)
            events = self._event_services.get(str(response.interaction_ref))
            if events is not None:
                events.runtime_event(
                    "interaction.answered",
                    {
                        "interaction_ref": str(response.interaction_ref),
                        "responded_at": response.responded_at.isoformat(),
                    },
                )
        return record, duplicate

    def cancel_for_run(self, run_ref: CapabilityRunRef, *, reason: str) -> int:
        records = self._store.cancel_interactions_for_run(
            run_ref,
            cancelled_at=self._clock(),
            reason=reason,
        )
        for record in records:
            key = str(record.request.interaction_id)
            events = self._event_services.get(key)
            if events is not None:
                events.runtime_event(
                    "interaction.cancelled",
                    {
                        "interaction_ref": key,
                        "reason": reason,
                    },
                )
            waiter = self._waiters.get(key)
            if waiter is not None and not waiter.done():
                waiter.set_exception(ExecutionCancelled(reason))
        return len(records)

    def pending(self, interaction_ref: InteractionRef) -> InteractionRuntimeRecord | None:
        return self._store.get_interaction(interaction_ref)

    def shutdown(self) -> int:
        run_refs = {
            record.request.run_ref
            for interaction_id in tuple(self._waiters)
            if (record := self._store.get_interaction(InteractionRef(interaction_id))) is not None
            and record.state is InteractionLifecycle.REQUESTED
        }
        return sum(
            self.cancel_for_run(
                run_ref,
                reason="Execution Node shut down while waiting for operator input",
            )
            for run_ref in run_refs
        )


class NodeInteractionService:
    """Run-scoped SDK adapter; capabilities never see persistence or transport details."""

    def __init__(
        self,
        *,
        runtime: InteractionRuntime,
        run_ref: CapabilityRunRef,
        mission_ref: MissionRef,
        workflow_run_ref: WorkflowRunRef | None,
        events: NodeEventService,
    ) -> None:
        self._runtime = runtime
        self._run_ref = run_ref
        self._mission_ref = mission_ref
        self._workflow_run_ref = workflow_run_ref
        self._events = events

    async def request(self, request: InteractionRequest) -> InteractionResponse:
        return await self._runtime.request(
            request,
            run_ref=self._run_ref,
            mission_ref=self._mission_ref,
            workflow_run_ref=self._workflow_run_ref,
            events=self._events,
        )
