"""Private SQLAlchemy repositories for provider metadata and routing decisions."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from boberagent_contracts import CapabilityDefinition, CapabilityRunRef, JsonObject
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import (
    CapabilityProviderRow,
    CapabilityRoutingDecisionRow,
)

from .errors import ConflictingProviderRegistration, ConflictingRoutingDecision
from .models import (
    CapabilityProvider,
    ProviderAvailability,
    ProviderReportedStatus,
    RoutingDecision,
)

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class CapabilityProviderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, provider: CapabilityProvider) -> CapabilityProvider:
        provider_key = str(provider.provider_id)
        row = self._session.get(CapabilityProviderRow, provider_key)
        identity_row = self._session.scalar(
            select(CapabilityProviderRow).where(
                CapabilityProviderRow.node_id == provider.node_id,
                CapabilityProviderRow.capability_id == provider.capability_id,
            )
        )
        if row is not None and (
            row.node_id != provider.node_id or row.capability_id != provider.capability_id
        ):
            raise ConflictingProviderRegistration(
                f"provider identity collision: {provider.provider_id}"
            )
        if identity_row is not None and identity_row.provider_id != provider_key:
            raise ConflictingProviderRegistration(
                f"Node/Capability pair has conflicting provider identity: {provider.node_id} / "
                f"{provider.capability_id}"
            )
        definition = _json_object_adapter.validate_python(
            provider.definition.model_dump(mode="json")
        )
        if row is None:
            row = CapabilityProviderRow(
                provider_id=provider_key,
                node_id=provider.node_id,
                capability_id=provider.capability_id,
                definition_json=deepcopy(definition),
                implementation_version=provider.implementation_version,
                reported_status=provider.reported_status.value,
                availability=provider.availability.value,
                first_registered_at=provider.first_registered_at,
                last_seen_at=provider.last_seen_at,
                node_lifecycle=provider.node_lifecycle,
                node_database_ready=provider.node_database_ready,
                node_degraded_reasons_json=list(provider.node_degraded_reasons),
                unavailability_reason=provider.unavailability_reason,
            )
            self._session.add(row)
        else:
            row.definition_json = deepcopy(definition)
            row.implementation_version = provider.implementation_version
            row.reported_status = provider.reported_status.value
            row.availability = provider.availability.value
            row.last_seen_at = provider.last_seen_at
            row.node_lifecycle = provider.node_lifecycle
            row.node_database_ready = provider.node_database_ready
            row.node_degraded_reasons_json = list(provider.node_degraded_reasons)
            row.unavailability_reason = provider.unavailability_reason
        try:
            self._session.flush()
        except IntegrityError as error:
            raise ConflictingProviderRegistration(
                f"provider registration violated persistence identity: {provider.provider_id}"
            ) from error
        return _provider_from_row(row)

    def get(self, provider_id: UUID) -> CapabilityProvider | None:
        row = self._session.get(CapabilityProviderRow, str(provider_id))
        return None if row is None else _provider_from_row(row)

    def list_all(self) -> tuple[CapabilityProvider, ...]:
        rows = self._session.scalars(
            select(CapabilityProviderRow).order_by(CapabilityProviderRow.provider_id)
        )
        return tuple(_provider_from_row(row) for row in rows)

    def list_for_capability(self, capability_id: str) -> tuple[CapabilityProvider, ...]:
        rows = self._session.scalars(
            select(CapabilityProviderRow)
            .where(CapabilityProviderRow.capability_id == capability_id)
            .order_by(CapabilityProviderRow.provider_id)
        )
        return tuple(_provider_from_row(row) for row in rows)

    def list_for_node(self, node_id: str) -> tuple[CapabilityProvider, ...]:
        rows = self._session.scalars(
            select(CapabilityProviderRow)
            .where(CapabilityProviderRow.node_id == node_id)
            .order_by(CapabilityProviderRow.provider_id)
        )
        return tuple(_provider_from_row(row) for row in rows)

    def mark_missing_from_refresh(
        self,
        *,
        node_id: str,
        advertised_capability_ids: frozenset[str],
        reason: str,
    ) -> None:
        rows = self._session.scalars(
            select(CapabilityProviderRow).where(CapabilityProviderRow.node_id == node_id)
        )
        for row in rows:
            if row.capability_id not in advertised_capability_ids:
                row.availability = ProviderAvailability.UNAVAILABLE.value
                row.unavailability_reason = reason
        self._session.flush()

    def mark_node_stale(self, node_id: str, reason: str) -> None:
        rows = self._session.scalars(
            select(CapabilityProviderRow).where(CapabilityProviderRow.node_id == node_id)
        )
        for row in rows:
            row.availability = ProviderAvailability.STALE.value
            row.unavailability_reason = reason
        self._session.flush()

    def mark_all_stale(self, reason: str) -> None:
        rows = self._session.scalars(select(CapabilityProviderRow))
        for row in rows:
            row.availability = ProviderAvailability.STALE.value
            row.unavailability_reason = reason
        self._session.flush()


class RoutingDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, decision: RoutingDecision) -> RoutingDecision:
        row = self._session.get(CapabilityRoutingDecisionRow, str(decision.run_ref))
        if row is not None:
            existing = _decision_from_row(row)
            same_selection = (
                existing.run_ref == decision.run_ref
                and existing.capability_id == decision.capability_id
                and existing.operation == decision.operation
                and existing.provider_id == decision.provider_id
                and existing.node_id == decision.node_id
                and existing.implementation_version == decision.implementation_version
            )
            if not same_selection:
                raise ConflictingRoutingDecision(
                    f"CapabilityRun already has a different routing decision: {decision.run_ref}"
                )
            return existing
        row = CapabilityRoutingDecisionRow(
            run_id=str(decision.run_ref),
            capability_id=decision.capability_id,
            operation=decision.operation,
            provider_id=str(decision.provider_id),
            node_id=decision.node_id,
            implementation_version=decision.implementation_version,
            selected_at=decision.selected_at,
        )
        self._session.add(row)
        self._session.flush()
        return _decision_from_row(row)

    def get(self, run_ref: CapabilityRunRef) -> RoutingDecision | None:
        row = self._session.get(CapabilityRoutingDecisionRow, str(run_ref))
        return None if row is None else _decision_from_row(row)


def _provider_from_row(row: CapabilityProviderRow) -> CapabilityProvider:
    return CapabilityProvider(
        provider_id=UUID(row.provider_id),
        node_id=row.node_id,
        definition=CapabilityDefinition.model_validate(deepcopy(row.definition_json)),
        reported_status=ProviderReportedStatus(row.reported_status),
        availability=ProviderAvailability(row.availability),
        first_registered_at=row.first_registered_at,
        last_seen_at=row.last_seen_at,
        node_lifecycle=row.node_lifecycle,
        node_database_ready=row.node_database_ready,
        node_degraded_reasons=tuple(row.node_degraded_reasons_json),
        unavailability_reason=row.unavailability_reason,
    )


def _decision_from_row(row: CapabilityRoutingDecisionRow) -> RoutingDecision:
    return RoutingDecision(
        run_ref=CapabilityRunRef(row.run_id),
        capability_id=row.capability_id,
        operation=row.operation,
        provider_id=UUID(row.provider_id),
        node_id=row.node_id,
        implementation_version=row.implementation_version,
        selected_at=row.selected_at,
    )
