"""Harmless C1→C2→C3→D3 evidence; source is inspected, never executed."""

from pathlib import Path

from boberagent_contracts.plan_requirements import (
    ExecutionLimits,
    ExecutionLocation,
    RuntimeRequirement,
)
from boberagent_contracts.plan_values import (
    BindingProvenance,
    DeliveryChannel,
    InvocationLayout,
    LiteralValue,
    MissionTargetValue,
    NetworkTarget,
    OptionValueToken,
    ParameterBinding,
    ResolutionState,
    TargetRole,
    ValueType,
)
from boberagent_core import CoreDatabase
from boberagent_core.inspections.semantic_models import ParameterRole, SemanticInspectionDocument
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.construction_models import PlanConstructionRequest
from planning_admission_fixtures import AdmissionChain, seed_chain
from test_core_poc_acquisition import NOW

CHECKER = b"""import argparse
import socket
parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True)
parser.add_argument("--port", required=False, type=int, default=80)
if __name__ == "__main__":
    args = parser.parse_args()
    connection = socket.create_connection((args.host, args.port), timeout=5)
    connection.close()
"""


def prepared(
    database: CoreDatabase,
    tmp_path: Path,
    files: dict[str, bytes] | None = None,
) -> tuple[AdmissionChain, PlanConstructionRequest]:
    chain = seed_chain(database, tmp_path, files or {"checker.py": CHECKER})
    attempt = CorePlanningAdmissionService(database, clock=lambda: NOW).admit(chain.request).attempt
    assert isinstance(chain.c2.document, SemanticInspectionDocument)
    doc = chain.c2.document
    with database.unit_of_work() as work:
        hypothesis = work.research.get_hypothesis(chain.acquisition.hypothesis_ref)
        assert hypothesis is not None
        asset = work.assets.get(hypothesis.asset_ref)
    assert asset is not None
    parameters = tuple(
        item for item in doc.parameter_candidates if item.source_path == "checker.py"
    )
    bindings = tuple(
        ParameterBinding(
            binding_id="host" if item.role is ParameterRole.TARGET_HOST else "port",
            parameter_id=item.item_id,
            value_type=ValueType.TARGET
            if item.role is ParameterRole.TARGET_HOST
            else ValueType.INTEGER,
            channel=DeliveryChannel.ARGUMENT,
            required=item.required is True,
            resolution=ResolutionState.RESOLVED,
            value=MissionTargetValue(target_role=TargetRole.SERVICE_ENDPOINT)
            if item.role is ParameterRole.TARGET_HOST
            else LiteralValue(value=80),
            provenance=BindingProvenance(
                origin="MISSION" if item.role is ParameterRole.TARGET_HOST else "PLANNING",
                evidence_ids=(item.item_id,),
            ),
        )
        for item in parameters
    )
    return chain, PlanConstructionRequest(
        planning_attempt_ref=attempt.planning_attempt_ref,
        expected_revision=0,
        target=NetworkTarget(
            role=TargetRole.SERVICE_ENDPOINT,
            asset_ref=asset.asset_ref,
            address=asset.primary_address,
            port=80,
            transport="tcp",
        ),
        invocation=InvocationLayout(
            review_id="review-d4-fixture",
            evidence_ids=tuple(item.item_id for item in parameters),
            arguments=(
                OptionValueToken(name="--host", binding_id="host"),
                OptionValueToken(name="--port", binding_id="port"),
            ),
        ),
        bindings=bindings,
        runtime=RuntimeRequirement(
            kind="python",
            version_constraint=">=3.12,<4",
            platform="LINUX",
            platform_variant="kali",
            user_space=True,
            noninteractive=True,
            location=ExecutionLocation.ATTACKER_NODE,
        ),
        limits=ExecutionLimits(
            wall_time_seconds=30,
            process_count=1,
            memory_bytes=256 * 1024 * 1024,
            output_bytes=1024 * 1024,
            disk_write_bytes=0,
        ),
    )
