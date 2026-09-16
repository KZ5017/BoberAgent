"""Round-trip tests for Core-owned metadata repositories."""

from datetime import timedelta

from boberagent_contracts import (
    AssetRef,
    MissionRef,
    WorkflowRunRef,
)
from boberagent_core import (
    Asset,
    CoreDatabase,
    Goal,
    GoalRef,
    GoalStatus,
    Mission,
    WorkflowRun,
    WorkflowStatus,
)
from conftest import NOW, add_artifact, add_mission_and_run


def test_mission_and_asset_logical_ids_round_trip(database: CoreDatabase) -> None:
    mission = Mission(
        mission_ref=MissionRef("mission-roundtrip"),
        status="ACTIVE",
        created_at=NOW,
        name="Internal lab",
        metadata={"owner": "team-blue"},
    )
    asset = Asset(
        asset_ref=AssetRef("asset-roundtrip"),
        mission_ref=mission.mission_ref,
        kind="host",
        primary_address="192.0.2.10",
        created_at=NOW,
        metadata={"environment": "lab"},
    )
    with database.unit_of_work() as work:
        work.missions.add(mission)
        work.assets.add(asset)

    with database.unit_of_work() as work:
        assert work.missions.get(mission.mission_ref) == mission
        assert work.assets.get(asset.asset_ref) == asset
        assert work.assets.list_for_mission(mission.mission_ref) == (asset,)


def test_run_and_artifact_contract_models_round_trip(database: CoreDatabase) -> None:
    run = add_mission_and_run(database)
    artifact = add_artifact(database, run)

    with database.unit_of_work() as work:
        assert work.runs.get(run.run_id) == run
        assert work.artifacts.get(artifact.artifact_id) == artifact


def test_workflow_and_core_owned_goal_metadata_round_trip(database: CoreDatabase) -> None:
    mission = Mission(mission_ref=MissionRef("mission-workflow"), status="ACTIVE", created_at=NOW)
    workflow = WorkflowRun(
        workflow_run_ref=WorkflowRunRef("workflow-test"),
        mission_ref=mission.mission_ref,
        procedure_ref="procedure:bootstrap",
        status=WorkflowStatus.CREATED,
        created_at=NOW,
        updated_at=NOW,
    )
    goal = Goal(
        goal_ref=GoalRef("goal-test"),
        mission_ref=mission.mission_ref,
        workflow_run_ref=workflow.workflow_run_ref,
        goal_type="service.discovery.complete",
        parameters={"asset_ref": "asset-future"},
        status=GoalStatus.PENDING,
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=1),
    )
    with database.unit_of_work() as work:
        work.missions.add(mission)
        work.workflows.add(workflow)
        work.goals.add(goal)

    with database.unit_of_work() as work:
        assert work.workflows.get(workflow.workflow_run_ref) == workflow
        assert work.goals.get(goal.goal_ref) == goal
        assert work.goals.list_for_mission(mission.mission_ref) == (goal,)
