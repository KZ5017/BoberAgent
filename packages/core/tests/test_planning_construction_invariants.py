"""D4 revision races, rollback, authority boundaries and targeted invalid inputs."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import AssetRef, MissionRef, Observation, ObservationRef, ServiceRef
from boberagent_contracts.plan_requirements import ExecutionLocation
from boberagent_contracts.plan_values import (
    BindingProvenance,
    LiteralValue,
    NetworkTarget,
    OperatorValue,
    ResolutionState,
    SourceTarget,
    TargetRole,
    ValueType,
)
from boberagent_core import CoreDatabase, CorePersistence
from boberagent_core.artifacts.service import CoreArtifactService
from boberagent_core.inspections.classification_service import CorePoCSupportClassificationService
from boberagent_core.inspections.service import CorePoCInspectionService
from boberagent_core.models import Asset, Mission
from boberagent_core.planning.construction import (
    CoreExecutionPlanningService,
    PlanningConstructionError,
)
from boberagent_core.planning.construction_models import PlanConstructionRequest
from boberagent_core.planning.errors import PlanningConflict
from boberagent_core.planning.models import PlanningAttemptLifecycle as State
from boberagent_core.planning.models import PlanningDisposition as Disposition
from boberagent_core.planning.repository import PlanDecisionRepository
from planning_construction_fixtures import CHECKER, prepared
from sqlalchemy import text
from test_core_poc_acquisition import NOW


def counts(database: CoreDatabase) -> tuple[int, ...]:
    with database._migration_engine.connect() as connection:
        return tuple(
            connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in (
                "execution_plans",
                "plan_decisions",
                "capability_runs",
                "capability_routing_decisions",
                "interactions",
            )
        )


def test_missing_layout_durable_wait_and_revision_cas(
    database: CoreDatabase, tmp_path: Path
) -> None:
    _, original = prepared(database, tmp_path)
    request = original.model_copy(update={"invocation": None})
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    wait = planner.construct(request)
    assert wait.attempt.lifecycle is State.WAITING_INPUT
    assert wait.attempt.revisions[-1].proposal.unresolved_requirement_ids == (
        "INVOCATION_LAYOUT_REQUIRED",
    )
    assert planner.construct(request) == wait
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        planner = CoreExecutionPlanningService(reopened, clock=lambda: NOW)
        assert planner.get(request.planning_attempt_ref) == wait
        with pytest.raises(PlanningConflict):
            planner.construct(original)
        final = planner.construct(original.model_copy(update={"expected_revision": 1}))
        assert final.attempt.disposition is Disposition.VALID
        assert len(final.attempt.revisions) == 2
        assert final.attempt.revisions[0] == wait.attempt.revisions[0]
    finally:
        reopened.dispose()


def test_multiple_entrypoints_do_not_guess(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path, {"checker.py": CHECKER, "other.py": CHECKER})
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    assert result.attempt.lifecycle is State.WAITING_INPUT
    assert result.attempt.disposition is Disposition.REQUIRES_INPUT
    assert result.attempt.revisions[-1].proposal.entrypoint is None
    assert result.attempt.diagnostic_codes == ("ENTRYPOINT_SELECTION_REQUIRED",)


@pytest.mark.parametrize(
    "change, code",
    [
        ("wrong-layout-ref", "INVOCATION_LAYOUT_INVALID"),
        ("missing-binding", "BINDING_MISSING"),
        ("wrong-type", "BINDING_TYPE_MISMATCH"),
        ("file-target", "TARGET_ROLE_MISMATCH"),
        ("address", "OUT_OF_SCOPE"),
        ("interactive", "NONINTERACTIVE_REQUIRED"),
        ("privileged", "USER_SPACE_REQUIRED"),
        ("target-runtime", "ATTACKER_SIDE_REQUIRED"),
        ("runtime", "UNSUPPORTED_RUNTIME"),
        ("version", "UNSUPPORTED_RUNTIME"),
        ("unresolved", "UNRESOLVED_BINDING"),
        ("unknown-service", "MISSION_MISMATCH"),
    ],
)
def test_invalid_construction_keeps_revision_not_plan(
    database: CoreDatabase,
    tmp_path: Path,
    change: str,
    code: str,
) -> None:
    chain, request = prepared(database, tmp_path)
    assert request.invocation is not None and request.runtime is not None
    assert isinstance(request.target, NetworkTarget)
    updates: dict[str, object] = {}
    if change == "wrong-layout-ref":
        updates["invocation"] = request.invocation.model_copy(
            update={"evidence_ids": ("item-" + "0" * 64,)}
        )
    elif change in {"missing-binding", "wrong-type", "unresolved"}:
        host = next(item for item in request.bindings if item.binding_id == "host")
        port = next(item for item in request.bindings if item.binding_id == "port")
        if change == "missing-binding":
            updates["bindings"] = (host,)
        else:
            values: dict[str, object] = {
                "value_type": ValueType.TEXT,
                "value": LiteralValue(value="80"),
            }
            if change == "unresolved":
                values = {"resolution": ResolutionState.UNRESOLVED, "value": None}
            updates["bindings"] = (host, port.model_copy(update=values))
    elif change == "file-target":
        updates["target"] = (
            SourceTarget(
                role=TargetRole.DIRECTORY,
                artifact_ref=chain.acquisition.receipt.raw_source.artifact_id,
                relative_path="data",
            )
            if chain.acquisition.receipt
            else None
        )
    elif change == "address":
        updates["target"] = request.target.model_copy(update={"address": "192.0.2.200"})
    elif change == "unknown-service":
        updates["target"] = request.target.model_copy(
            update={"service_ref": ServiceRef("service-missing")}
        )
    else:
        runtime_values: dict[str, dict[str, object]] = {
            "interactive": {"noninteractive": False},
            "privileged": {"user_space": False},
            "target-runtime": {"location": ExecutionLocation.TARGET},
            "runtime": {"kind": "ruby"},
            "version": {"version_constraint": "unknown"},
        }
        updates["runtime"] = request.runtime.model_copy(update=runtime_values[change])
    before = counts(database)
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    invalid_request = request.model_copy(update=updates)
    result = planner.construct(invalid_request)
    assert result.attempt.lifecycle is State.COMPLETED
    assert result.attempt.disposition is Disposition.INVALID
    assert result.attempt.finalized_plan is None and result.validation is None
    assert result.attempt.diagnostic_codes == (code,)
    assert len(result.attempt.revisions) == 1
    assert counts(database) == before
    assert planner.construct(invalid_request) == result


def test_cross_mission_target_rejected(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(mission_ref=MissionRef("mission-other"), status="ACTIVE", created_at=NOW)
        )
        asset = Asset(
            asset_ref=AssetRef("asset-other"),
            mission_ref=MissionRef("mission-other"),
            kind="HOST",
            primary_address="192.0.2.100",
            created_at=NOW,
        )
        work.assets.add(asset)
    assert isinstance(request.target, NetworkTarget)
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(
            update={
                "target": request.target.model_copy(
                    update={"asset_ref": asset.asset_ref, "address": asset.primary_address}
                ),
            }
        )
    )
    assert result.attempt.disposition is Disposition.INVALID
    assert result.attempt.diagnostic_codes == ("MISSION_MISMATCH",)


def test_service_must_belong_to_selected_asset(database: CoreDatabase, tmp_path: Path) -> None:
    chain, request = prepared(database, tmp_path)
    assert isinstance(request.target, NetworkTarget)
    core = CorePersistence(database)
    other = Asset(
        asset_ref=AssetRef("asset-service-other"),
        mission_ref=chain.c2.mission_ref,
        kind="HOST",
        primary_address="192.0.2.21",
        created_at=NOW,
    )
    core.create_asset(other)
    assert chain.acquisition.run_ref is not None
    core.append_observation(
        Observation(
            observation_id=ObservationRef("observation-d4-service"),
            type="network.service",
            subject_ref=other.asset_ref,
            value={"transport": "tcp", "port": 80, "state": "open"},
            run_ref=chain.acquisition.run_ref,
            observed_at=NOW,
        )
    )
    core.materialize_observation(ObservationRef("observation-d4-service"))
    service = core.services_for_asset(other.asset_ref)[0]
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(
            update={
                "target": request.target.model_copy(update={"service_ref": service.service_ref}),
            }
        )
    )
    assert result.attempt.disposition is Disposition.INVALID


def test_operator_integer_and_provenance_supported(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    bindings = tuple(
        item
        if item.binding_id != "port"
        else item.model_copy(
            update={
                "value": OperatorValue(answer_id="review-answer-port", value=80),
                "provenance": BindingProvenance(
                    origin="OPERATOR",
                    answer_id="review-answer-port",
                    evidence_ids=(item.parameter_id,),
                ),
            }
        )
        for item in request.bindings
    )
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(update={"bindings": bindings})
    )
    assert result.attempt.disposition is Disposition.VALID
    assert result.attempt.revisions[-1].answers == ()  # Reviewed input, no D6 Interaction.


def test_atomic_failure_after_finalization_rolls_back_everything(
    database: CoreDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, request = prepared(database, tmp_path)
    before = counts(database)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("untrusted payload must never be rendered")

    monkeypatch.setattr(PlanDecisionRepository, "append", fail)
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    with pytest.raises(PlanningConstructionError, match=r"^CONSTRUCTION_INTERNAL_ERROR$"):
        planner.construct(request)
    unchanged = planner.get(request.planning_attempt_ref)
    assert unchanged is not None and unchanged.attempt.lifecycle is State.REQUESTED
    assert unchanged.attempt.revisions == ()
    assert counts(database) == before


def test_no_byte_reader_classifier_or_new_execution_rows(
    database: CoreDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, request = prepared(database, tmp_path)
    before = counts(database)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("D4 attempted source access or reinspection")

    for owner, method in (
        (CoreArtifactService, "open_content"),
        (CorePoCInspectionService, "inspect"),
        (CorePoCInspectionService, "read_citation"),
        (CorePoCSupportClassificationService, "classify"),
    ):
        monkeypatch.setattr(owner, method, forbidden)
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    assert counts(database) == (before[0] + 1, before[1] + 1, *before[2:])
    assert result.attempt.finalized_plan is not None
    assert "authorization" not in result.model_dump()
    assert "capability_run_ref" not in result.attempt.finalized_plan.model_dump()
    with database.unit_of_work() as work:
        decisions = work.plan_decisions.list_for_plan(
            result.attempt.finalized_plan.execution_plan_id
        )
    assert len(decisions) == 1 and decisions[0].document.kind == "VALIDATION"


def test_concurrent_finalizations_have_one_plan_and_validation(
    database: CoreDatabase, tmp_path: Path
) -> None:
    _, request = prepared(database, tmp_path)
    before = counts(database)
    barrier = Barrier(2)

    def construct(number: int) -> str:
        independent = CoreDatabase(database.config)
        try:
            barrier.wait(timeout=10)
            try:
                result = CoreExecutionPlanningService(independent, clock=lambda: NOW).construct(
                    request
                )
                assert result.attempt.finalized_plan is not None
                return str(result.attempt.finalized_plan.execution_plan_id)
            except PlanningConflict:
                return "conflict"
        finally:
            independent.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = tuple(pool.map(construct, (1, 2)))
    winners = {value for value in values if value != "conflict"}
    assert len(winners) == 1
    assert counts(database) == (before[0] + 1, before[1] + 1, *before[2:])


def test_changed_finalized_input_conflicts(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    result = planner.construct(request)
    assert request.limits is not None
    with pytest.raises(PlanningConflict):
        planner.construct(
            request.model_copy(
                update={"limits": request.limits.model_copy(update={"wall_time_seconds": 31})}
            )
        )
    assert planner.get(request.planning_attempt_ref) == result


def test_bypass_extra_fields_rejected_before_write(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    with pytest.raises(PlanningConstructionError, match="CONSTRUCTION_REQUEST_INVALID"):
        CoreExecutionPlanningService(database).construct(request.model_copy(update={"allow": True}))
    assert PlanConstructionRequest.model_validate_json(request.model_dump_json()) == request
