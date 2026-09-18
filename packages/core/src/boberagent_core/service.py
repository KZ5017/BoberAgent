"""Minimal Core application service over persistence and reducers."""

from __future__ import annotations

from boberagent_contracts import (
    ArtifactDescriptor,
    AssetRef,
    CapabilityRun,
    CapabilityRunRef,
    MissionRef,
    Observation,
    ObservationRef,
)

from .models import (
    Asset,
    Goal,
    MaterializationStatus,
    Mission,
    Service,
    StoredObservation,
    WorkflowRun,
)
from .persistence import CoreDatabase
from .state import ReducerRegistry


class CorePersistence:
    """Thin use-case boundary; contains no capability execution behavior."""

    def __init__(self, database: CoreDatabase, reducers: ReducerRegistry | None = None) -> None:
        self._database = database
        self._reducers = reducers or ReducerRegistry()

    def create_mission(self, mission: Mission) -> None:
        with self._database.unit_of_work() as work:
            work.missions.add(mission)

    def get_mission(self, mission_ref: MissionRef) -> Mission | None:
        with self._database.unit_of_work() as work:
            return work.missions.get(mission_ref)

    def list_missions(self) -> tuple[Mission, ...]:
        with self._database.unit_of_work() as work:
            return work.missions.list_all()

    def create_asset(self, asset: Asset) -> None:
        with self._database.unit_of_work() as work:
            work.assets.add(asset)

    def get_asset(self, asset_ref: AssetRef) -> Asset | None:
        with self._database.unit_of_work() as work:
            return work.assets.get(asset_ref)

    def list_assets(self, mission_ref: MissionRef) -> tuple[Asset, ...]:
        with self._database.unit_of_work() as work:
            return work.assets.list_for_mission(mission_ref)

    def record_run(self, run: CapabilityRun) -> None:
        with self._database.unit_of_work() as work:
            work.runs.add(run)

    def get_run(self, run_ref: CapabilityRunRef) -> CapabilityRun | None:
        with self._database.unit_of_work() as work:
            return work.runs.get(run_ref)

    def record_artifact(self, artifact: ArtifactDescriptor) -> None:
        with self._database.unit_of_work() as work:
            work.artifacts.add(artifact)

    def append_observation(self, observation: Observation) -> None:
        with self._database.unit_of_work() as work:
            work.observations.append(observation)

    def get_observation(self, observation_ref: ObservationRef) -> StoredObservation | None:
        with self._database.unit_of_work() as work:
            return work.observations.get(observation_ref)

    def materialize_observation(self, observation_ref: ObservationRef) -> MaterializationStatus:
        with self._database.unit_of_work() as work:
            return self._reducers.materialize(observation_ref, work)

    def services_for_asset(self, asset_ref: AssetRef) -> tuple[Service, ...]:
        with self._database.unit_of_work() as work:
            return work.services.list_for_asset(asset_ref)

    def create_workflow(self, workflow: WorkflowRun) -> None:
        with self._database.unit_of_work() as work:
            work.workflows.add(workflow)

    def create_goal(self, goal: Goal) -> None:
        with self._database.unit_of_work() as work:
            work.goals.add(goal)
