"""Real persisted negative evidence is not cleared by D4 reviewed input."""

from pathlib import Path

import pytest
from boberagent_contracts import AssetRef, Observation, ObservationRef
from boberagent_contracts.plan_values import NetworkTarget
from boberagent_core import CoreDatabase, CorePersistence
from boberagent_core.models import Asset
from boberagent_core.planning.construction import (
    CoreExecutionPlanningService,
    PlanningConstructionError,
)
from boberagent_core.planning.models import PlanningDisposition as Disposition
from planning_construction_fixtures import CHECKER, prepared
from test_core_poc_acquisition import NOW


@pytest.mark.parametrize(
    "extra",
    [
        b'\nimport shutil\nshutil.rmtree("/")\n',
        b'\nopen(args.host, "w").write("data")\n',
        b"\nunknown.connect(args.host)\n",
        b'\nparser.add_argument("--url", required=True)\n',
    ],
)
def test_real_unsupported_chain_cannot_enter_construction(
    database: CoreDatabase, tmp_path: Path, extra: bytes
) -> None:
    chain, request = prepared(database, tmp_path, {"checker.py": CHECKER + extra})
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    before = planner.get(request.planning_attempt_ref)
    assert before is not None and before.attempt.disposition is Disposition.UNSUPPORTED
    with pytest.raises(PlanningConstructionError, match="ADMISSION_UNSUPPORTED"):
        planner.construct(request)
    assert planner.get(request.planning_attempt_ref) == before
    with database.unit_of_work() as work:
        assert work.inspections.get(chain.c3.inspection_ref) == chain.c3


def test_real_third_party_requirement_not_finalized(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path, {"checker.py": CHECKER + b"\nimport requests\n"})
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    assert result.attempt.disposition is Disposition.INVALID
    assert result.attempt.diagnostic_codes == ("DEPENDENCY_UNSUPPORTED",)
    assert result.attempt.finalized_plan is None
    proposal = result.attempt.revisions[-1].proposal
    assert any(item.kind.value == "UNKNOWN" for item in proposal.dependencies)


def test_redacted_required_default_is_not_recovered(database: CoreDatabase, tmp_path: Path) -> None:
    secret = b"harmless-redacted-default"
    source = CHECKER.replace(
        b"required=False, type=int, default=80", b'required=True, default="' + secret + b'"'
    )
    chain, request = prepared(database, tmp_path, {"checker.py": source})
    request = request.model_copy(
        update={"bindings": tuple(item for item in request.bindings if item.binding_id != "port")}
    )
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    assert result.attempt.disposition is Disposition.INVALID
    assert result.attempt.diagnostic_codes == ("BINDING_MISSING",)
    assert secret.decode() not in result.model_dump_json()
    with database.unit_of_work() as work:
        assert work.inspections.get(chain.c2.inspection_ref) == chain.c2


def test_owned_service_endpoint_can_be_pinned(database: CoreDatabase, tmp_path: Path) -> None:
    chain, request = prepared(database, tmp_path)
    assert isinstance(request.target, NetworkTarget)
    assert chain.acquisition.run_ref is not None
    core = CorePersistence(database)
    core.append_observation(
        Observation(
            observation_id=ObservationRef("observation-d4-owned-service"),
            type="network.service",
            subject_ref=request.target.asset_ref,
            value={"transport": "tcp", "port": 80, "state": "open"},
            run_ref=chain.acquisition.run_ref,
            observed_at=NOW,
        )
    )
    core.materialize_observation(ObservationRef("observation-d4-owned-service"))
    service = core.services_for_asset(request.target.asset_ref)[0]
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(
            update={
                "target": request.target.model_copy(update={"service_ref": service.service_ref}),
            }
        )
    )
    assert result.attempt.disposition is Disposition.VALID
    assert result.attempt.finalized_plan is not None
    assert isinstance(result.attempt.finalized_plan.target, NetworkTarget)
    assert result.attempt.finalized_plan.target.service_ref == service.service_ref


def test_same_mission_wrong_asset_service_is_rejected(
    database: CoreDatabase, tmp_path: Path
) -> None:
    # Cover explicit endpoint data: knowing an address is not enough to borrow a Service.
    chain, request = prepared(database, tmp_path)
    assert isinstance(request.target, NetworkTarget)
    assert chain.acquisition.run_ref is not None
    core = CorePersistence(database)
    asset = Asset(
        asset_ref=AssetRef("asset-second-owned"),
        mission_ref=chain.c2.mission_ref,
        kind="HOST",
        primary_address="192.0.2.201",
        created_at=NOW,
    )
    core.create_asset(asset)
    core.append_observation(
        Observation(
            observation_id=ObservationRef("observation-d4-other-service"),
            type="network.service",
            subject_ref=asset.asset_ref,
            value={"transport": "tcp", "port": 80, "state": "open"},
            run_ref=chain.acquisition.run_ref,
            observed_at=NOW,
        )
    )
    core.materialize_observation(ObservationRef("observation-d4-other-service"))
    service = core.services_for_asset(asset.asset_ref)[0]
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(
            update={
                "target": request.target.model_copy(update={"service_ref": service.service_ref}),
            }
        )
    )
    assert result.attempt.disposition is Disposition.INVALID
