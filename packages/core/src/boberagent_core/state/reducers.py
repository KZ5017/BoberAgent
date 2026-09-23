"""Small registry for deterministic Observation materializers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from boberagent_contracts import Observation, ObservationRef
from pydantic import ValidationError

from boberagent_core.credentials import CredentialCandidateReducer
from boberagent_core.models import MaterializationStatus
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .network_service import NetworkServiceReducer


class ObservationReducer(Protocol):
    observation_type: str

    def reduce(self, observation: Observation, unit_of_work: CoreUnitOfWork) -> object: ...


class ReducerRegistry:
    """Dispatch normalized Observation types without a monolithic reducer."""

    def __init__(self, reducers: Mapping[str, ObservationReducer] | None = None) -> None:
        default_reducers: tuple[ObservationReducer, ...] = (
            NetworkServiceReducer(),
            CredentialCandidateReducer(),
        )
        self._reducers = (
            dict(reducers)
            if reducers is not None
            else {reducer.observation_type: reducer for reducer in default_reducers}
        )

    def materialize(
        self, observation_ref: ObservationRef, unit_of_work: CoreUnitOfWork
    ) -> MaterializationStatus:
        stored = unit_of_work.observations.get(observation_ref)
        if stored is None:
            raise KeyError(f"unknown Observation: {observation_ref}")

        reducer = self._reducers.get(stored.observation.type)
        if reducer is None:
            unit_of_work.observations.set_materialization(
                observation_ref,
                MaterializationStatus.UNSUPPORTED,
                error=f"no reducer registered for {stored.observation.type}",
            )
            return MaterializationStatus.UNSUPPORTED

        try:
            reducer.reduce(stored.observation, unit_of_work)
        except ValidationError:
            unit_of_work.observations.set_materialization(
                observation_ref,
                MaterializationStatus.REJECTED,
                error=f"invalid payload for {stored.observation.type}",
            )
            return MaterializationStatus.REJECTED
        except ValueError as error:
            unit_of_work.observations.set_materialization(
                observation_ref,
                MaterializationStatus.REJECTED,
                error=str(error),
            )
            return MaterializationStatus.REJECTED

        unit_of_work.observations.set_materialization(
            observation_ref, MaterializationStatus.MATERIALIZED
        )
        return MaterializationStatus.MATERIALIZED
