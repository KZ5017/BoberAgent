"""Controlled upstream C/D facts; preparation itself has no fixture authority bypass."""

from pathlib import Path

from boberagent_contracts import ConfinementFeature, PreparationAction, PreparationBudgets
from boberagent_core import CoreDatabase
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import PreparationRequest
from planning_construction_fixtures import CHECKER, prepared
from test_core_poc_acquisition import NOW
from test_planning_policy import _profile

# A marker is emitted before normal behavior. If accidentally launched inside a
# trusted identity/constructor operation, its bounded captured output is retained
# by the confinement journal and cannot be mistaken for the expected JSON proof.
# These are inert acquired bytes, NOT test modules or a package to install.
MARKER = "E5G_ACQUIRED_SOURCE_EXECUTED"
SENTINEL = f'print("{MARKER}", flush=True)\n'.encode()
SOURCE_FILES = {
    "checker.py": SENTINEL + CHECKER,
    "package/__init__.py": SENTINEL,
    "setup.py": SENTINEL,
    "sitecustomize.py": SENTINEL,
}


def establish_d(
    database: CoreDatabase, root: Path, node_id: str
) -> tuple[CorePlanPolicyService, PreparationRequest]:
    """Actual retained bytes → C2@2/C3@2 → D3/D4 VALID → D5 ALLOW.

    No preparation Run, Node record, Resource or positive runtime proof is seeded.
    The existing D fixture models a loopback intent; G never launches that intent.
    """
    _, construction = prepared(database, root, SOURCE_FILES)
    built = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(construction)
    plan = built.attempt.finalized_plan
    assert plan is not None and built.validation is not None
    policy = CorePlanPolicyService(
        database, PolicyProfileRegistry((_profile(plan, approval=False),)), clock=lambda: NOW
    )
    policy.evaluate(plan.execution_plan_id)
    from boberagent_core.capabilities.models import provider_id_for

    # Existing accepted E5-budget fixture ceilings, not a changed E5 limit profile.
    return policy, PreparationRequest(
        mission_ref=plan.mission_ref,
        plan_ref=plan.execution_plan_id,
        node_id=node_id,
        provider_id=provider_id_for(node_id, "runtime.prepare"),
        profile_id="m20-e-python-stdlib-kali",
        profile_version="1",
        confinement_features=tuple(ConfinementFeature),
        actions=tuple(PreparationAction),
        budgets=PreparationBudgets(
            max_imported_artifact_bytes=1_000_000,
            max_materialized_bytes=1_000_000,
            max_file_count=15000,
            max_path_depth=16,
            max_temporary_bytes=1024**3,
            max_preparation_write_bytes=2 * 1024**3,
            max_processes=11,
            max_process_runtime_seconds=60,
            max_total_runtime_seconds=900,
            max_captured_output_bytes=200000,
            max_memory_bytes=1024**3,
        ),
    )
