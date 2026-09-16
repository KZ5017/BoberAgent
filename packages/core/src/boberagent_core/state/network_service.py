"""Normalized ``network.service`` payload and deterministic materialization."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid5

from boberagent_contracts import AssetRef, Observation, ObservationRef, ServiceRef
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from boberagent_core.models import Service
from boberagent_core.persistence.repositories import CoreUnitOfWork

_SERVICE_NAMESPACE = UUID("b48f225f-4770-50c7-b62e-40c00eed682f")
_ShortValue = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class NetworkServiceValue(BaseModel):
    """Core's normalized value shape for ``network.service`` observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transport: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    port: int = Field(ge=1, le=65535)
    state: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    service: _ShortValue | None = None
    product: _ShortValue | None = None
    version: _ShortValue | None = None

    @field_validator("transport", "state", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("service", mode="before")
    @classmethod
    def normalize_service(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("product", "version", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


def service_ref_for_endpoint(asset_ref: AssetRef, transport: str, port: int) -> ServiceRef:
    """Derive the stable public reference from semantic endpoint identity."""

    endpoint = f"{asset_ref}\0{transport.lower()}\0{port}"
    return ServiceRef(f"service-{uuid5(_SERVICE_NAMESPACE, endpoint)}")


class NetworkServiceReducer:
    """Materialize one endpoint using a deterministic latest-observation policy.

    Identity is ``AssetRef + normalized transport + port``. All contributing Observation refs
    remain as provenance. The lexicographically greatest ``(observed_at, observation_id)`` owns
    the current fields; this makes same-timestamp conflicts deterministic and replay-safe.
    """

    observation_type = "network.service"

    def reduce(self, observation: Observation, unit_of_work: CoreUnitOfWork) -> Service:
        if observation.subject_ref is None:
            raise ValueError("network.service requires an AssetRef subject")
        asset_ref = AssetRef(str(observation.subject_ref))
        if unit_of_work.assets.get(asset_ref) is None:
            raise ValueError(f"network.service subject is not a persisted Asset: {asset_ref}")

        value = NetworkServiceValue.model_validate(observation.value)
        service_ref = service_ref_for_endpoint(asset_ref, value.transport, value.port)
        current = unit_of_work.services.get_by_endpoint(asset_ref, value.transport, value.port)
        if current is None:
            materialized = Service(
                service_ref=service_ref,
                asset_ref=asset_ref,
                transport=value.transport,
                port=value.port,
                state=value.state,
                service=value.service,
                product=value.product,
                version=value.version,
                first_observed_at=observation.observed_at,
                last_observed_at=observation.observed_at,
                current_observation_ref=observation.observation_id,
                provenance_refs=(observation.observation_id,),
            )
            return unit_of_work.services.upsert_current(materialized)

        provenance = tuple(
            ObservationRef(ref)
            for ref in sorted(
                {str(ref) for ref in (*current.provenance_refs, observation.observation_id)}
            )
        )
        incoming_key = (observation.observed_at, str(observation.observation_id))
        current_key = (current.last_observed_at, str(current.current_observation_ref))
        incoming_is_current = incoming_key >= current_key

        materialized = Service(
            service_ref=current.service_ref,
            asset_ref=current.asset_ref,
            transport=current.transport,
            port=current.port,
            state=value.state if incoming_is_current else current.state,
            service=value.service if incoming_is_current else current.service,
            product=value.product if incoming_is_current else current.product,
            version=value.version if incoming_is_current else current.version,
            first_observed_at=min(current.first_observed_at, observation.observed_at),
            last_observed_at=max(current.last_observed_at, observation.observed_at),
            current_observation_ref=(
                observation.observation_id
                if incoming_is_current
                else current.current_observation_ref
            ),
            provenance_refs=provenance,
        )
        return unit_of_work.services.upsert_current(materialized)
