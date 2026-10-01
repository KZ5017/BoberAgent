"""E2 uses persisted D authority, never a Node or a preparation CapabilityRun."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import (
    CONTRACT_VERSION,
    CapabilityDefinition,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionSurfaceDeclaration,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_contracts.runtime_preparation import (
    ConfinementFeature,
    PreparationAction,
    PreparationBudgets,
    preparation_permit_digest,
)
from boberagent_core import CapabilityRegistry, CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.capabilities.models import provider_id_for
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.interaction_models import PlanningInteractionResponse
from boberagent_core.planning.models import PlanningInteractionPurpose
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import (
    CoreRuntimePreparationAdmissionService,
    PreparationAdmissionReason,
    PreparationLifecycle,
    PreparationRequest,
)
from boberagent_core.preparation.repository import PreparationConflict, PreparationPersistenceError
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    NodeAdvertisement,
    TransportMessageId,
)
from planning_construction_fixtures import prepared
from sqlalchemy import text
from test_core_poc_acquisition import NOW
from test_planning_policy import _profile

NODE = "node-preparation-test"


def _budgets() -> PreparationBudgets:
    return PreparationBudgets(
        max_imported_artifact_bytes=1_000_000,
        max_materialized_bytes=1_000_000,
        max_file_count=100,
        max_path_depth=16,
        max_temporary_bytes=1_000_000,
        max_preparation_write_bytes=1_000_000,
        max_processes=2,
        max_process_runtime_seconds=60,
        max_total_runtime_seconds=120,
        max_captured_output_bytes=100_000,
        max_memory_bytes=1_000_000_000,
    )


def _definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="runtime.prepare",
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="Synthetic preparation metadata",
        description="Never loaded or executed by the Node in E2.",
        operations=(
            OperationDefinition(
                name="prepare",
                title="Prepare",
                description="Synthetic registry metadata only.",
                input_schema=SchemaDeclaration(inline={"type": "object"}),
                result_types=(ResultObjectType.RESOURCE,),
                retry_semantics=RetrySemantics.UNSAFE,
            ),
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.ONE_SHOT,
            interaction=ExecutionInteraction.STATELESS,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=True,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.WRITE,
            ),
        ),
        dependencies=(),
    )


def _advertise(registry: CapabilityRegistry, *, lifecycle: str = "READY") -> None:
    definition = _definition()
    registry.register_or_refresh_node(
        NodeAdvertisement(
            request_message_id=TransportMessageId("transport-handshake:preparation-test"),
            node_id=NODE,
            timestamp=NOW,
            lifecycle=lifecycle,
            database_ready=True,
            capabilities=(definition,),
            capability_statuses=(
                CapabilityStatusAdvertisement(
                    capability_id=definition.capability_id,
                    status=AdvertisedCapabilityStatus.AVAILABLE,
                ),
            ),
        )
    )


def _setup(tmp_path: Path, *, approval: bool = False):  # type: ignore[no-untyped-def]
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    _chain, construction = prepared(database, tmp_path)
    built = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(construction)
    plan = built.attempt.finalized_plan
    assert plan is not None
    profile = _profile(plan, approval=approval)
    policy = CorePlanPolicyService(database, PolicyProfileRegistry((profile,)), clock=lambda: NOW)
    policy.evaluate(plan.execution_plan_id)
    registry = CapabilityRegistry(database, clock=lambda: NOW)
    _advertise(registry)
    approvals = CorePlanApprovalService(database, policy, clock=lambda: NOW)
    service = CoreRuntimePreparationAdmissionService(
        database, policy, approvals, registry, clock=lambda: NOW
    )
    request = PreparationRequest(
        mission_ref=plan.mission_ref,
        plan_ref=plan.execution_plan_id,
        node_id=NODE,
        provider_id=provider_id_for(NODE, "runtime.prepare"),
        profile_id="m20-e-python-stdlib-kali",
        profile_version="1",
        budgets=_budgets(),
        confinement_features=tuple(ConfinementFeature),
        actions=tuple(PreparationAction),
    )
    return database, plan, policy, approvals, registry, service, request


def test_eligible_admission_reuse_and_reopen(tmp_path: Path) -> None:
    database, _plan, policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        first = service.admit(request)
        assert first.attempt.lifecycle is PreparationLifecycle.REQUESTED
        assert first.current_applicable and first.permit is not None
        assert first.permit.run_ref == first.attempt.reserved_run_ref
        assert first.attempt.spec == first.permit.spec
        assert service.admit(request) == first
        assert service.get_permit(first.permit.permit_ref) == first.permit
        assert service.get_attempt(first.attempt.preparation_ref) == first.attempt
        assert service.current_admission(first.attempt.preparation_ref) == first
        with database.unit_of_work() as work:
            assert work.runs.get(first.permit.run_ref) is None
        digest = preparation_permit_digest(first.permit)
        database.dispose()
        reopened = CoreDatabase(database.config)
        try:
            new_policy = CorePlanPolicyService(reopened, policy._registry, clock=lambda: NOW)
            new_registry = CapabilityRegistry(reopened, clock=lambda: NOW)
            restarted = CoreRuntimePreparationAdmissionService(
                reopened,
                new_policy,
                CorePlanApprovalService(reopened, new_policy, clock=lambda: NOW),
                new_registry,
                clock=lambda: NOW,
            )
            assert restarted.get_attempt(first.attempt.preparation_ref) == first.attempt
            assert restarted.get_permit(first.permit.permit_ref) == first.permit
            assert preparation_permit_digest(first.permit) == digest
            stale = restarted.current_admission(first.attempt.preparation_ref)
            assert stale is not None and not stale.current_applicable
            _advertise(new_registry)
            assert restarted.current_admission(first.attempt.preparation_ref) is not None
            assert restarted.admit(request).attempt.preparation_ref == first.attempt.preparation_ref
            with reopened.unit_of_work() as work:
                assert work.runs.get(first.permit.run_ref) is None
        finally:
            reopened.dispose()
    finally:
        database.dispose()


def test_missing_approval_and_profile_rejection_are_durable(tmp_path: Path) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(
        tmp_path, approval=True
    )
    try:
        missing = service.admit(request)
        assert missing.attempt.lifecycle is PreparationLifecycle.REJECTED
        assert missing.attempt.reason_code is PreparationAdmissionReason.APPROVAL_REQUIRED
        assert missing.permit is None
        assert service.admit(request) == missing
        different = request.model_copy(update={"profile_id": "unsupported-profile"})
        rejected = service.admit(different)
        assert rejected.attempt.preparation_ref != missing.attempt.preparation_ref
        # Approval remains the first authoritative blocker for this request.
        assert rejected.attempt.reason_code is PreparationAdmissionReason.APPROVAL_REQUIRED
    finally:
        database.dispose()


def test_e_profile_rejection_and_cas(tmp_path: Path) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        rejected = service.admit(request.model_copy(update={"budgets": None}))
        assert rejected.attempt.reason_code is PreparationAdmissionReason.PREPARATION_BUDGET_INVALID
        assert rejected.permit is None
        invalid = service.admit(request.model_copy(update={"confinement_features": ()}))
        assert (
            invalid.attempt.reason_code
            is PreparationAdmissionReason.CONFINEMENT_REQUIREMENT_INVALID
        )
        unsupported_profile = service.admit(
            request.model_copy(update={"profile_version": "unsupported"})
        )
        assert (
            unsupported_profile.attempt.reason_code
            is PreparationAdmissionReason.PREPARATION_PROFILE_UNSUPPORTED
        )
        unsupported_actions = service.admit(request.model_copy(update={"actions": ()}))
        assert (
            unsupported_actions.attempt.reason_code
            is PreparationAdmissionReason.PREPARATION_ACTION_UNSUPPORTED
        )
        valid = service.admit(request)
        with database.unit_of_work() as work, pytest.raises(PreparationConflict, match="stale"):
            work.runtime_preparations.compare_and_set_revision(
                valid.attempt.preparation_ref,
                expected_revision=1,
                updated_at=NOW + timedelta(seconds=1),
            )
        with database.unit_of_work() as work:
            assert work.runtime_preparations.get(valid.attempt.preparation_ref) == valid.attempt
    finally:
        database.dispose()


def _approval_response(request: object) -> PlanningInteractionResponse:
    from boberagent_core.planning.interaction_models import PlanningInteractionRequest

    assert isinstance(request, PlanningInteractionRequest)
    return PlanningInteractionResponse(
        interaction_ref=request.interaction_ref,
        planning_attempt_ref=request.planning_attempt_ref,
        proposal_revision=request.proposal_revision,
        purpose=PlanningInteractionPurpose.POLICY_APPROVAL,
        operator_id="operator-e2-test",
        value="APPROVE",
        responded_at=NOW,
    )


def test_exact_approval_admits_then_stale_policy_invalidates_history(tmp_path: Path) -> None:
    database, plan, _policy, approvals, registry, service, request = _setup(tmp_path, approval=True)
    try:
        rejected = service.admit(request)
        assert rejected.attempt.reason_code is PreparationAdmissionReason.APPROVAL_REQUIRED
        pending = approvals.request(plan.execution_plan_id)
        approval = approvals.respond(_approval_response(pending.request))
        admitted = service.admit(request)
        assert admitted.current_applicable and admitted.permit is not None
        assert admitted.permit.approval_decision_ref == approval.decision_ref
        assert admitted.attempt.preparation_ref != rejected.attempt.preparation_ref
        registry.mark_node_stale(NODE)
        stale = service.current_admission(admitted.attempt.preparation_ref)
        assert stale is not None and not stale.current_applicable
        assert stale.permit == admitted.permit
        _advertise(registry)
        assert service.current_admission(admitted.attempt.preparation_ref) == admitted
        old_profile = _profile(plan, approval=True)
        changed_profile = old_profile.model_copy(
            update={"allowed_service_refs": (), "require_operator_approval": False}
        )
        changed_policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((changed_profile,)), clock=lambda: NOW
        )
        replacement = CoreRuntimePreparationAdmissionService(
            database,
            changed_policy,
            CorePlanApprovalService(database, changed_policy, clock=lambda: NOW),
            registry,
            clock=lambda: NOW,
        )
        current = replacement.current_admission(admitted.attempt.preparation_ref)
        assert current is not None and not current.current_applicable
        assert replacement.get_permit(admitted.permit.permit_ref) == admitted.permit
        missing = replacement.admit(request)
        assert missing.attempt.reason_code is PreparationAdmissionReason.POLICY_NOT_EVALUATED
        changed_policy.evaluate(plan.execution_plan_id)
        new = replacement.admit(request)
        assert new.attempt.preparation_ref != admitted.attempt.preparation_ref
        assert new.permit is not None
    finally:
        database.dispose()


def test_hard_policy_denial_is_not_overridden(tmp_path: Path) -> None:
    database, plan, _policy, _approvals, registry, _service, request = _setup(tmp_path)
    try:
        original = _profile(plan, approval=False)
        lower = original.maximum_limits.model_copy(update={"wall_time_seconds": 1})
        denied_profile = original.model_copy(update={"maximum_limits": lower})
        denied_policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((denied_profile,)), clock=lambda: NOW
        )
        denied_policy.evaluate(plan.execution_plan_id)
        denied = CoreRuntimePreparationAdmissionService(
            database,
            denied_policy,
            CorePlanApprovalService(database, denied_policy, clock=lambda: NOW),
            registry,
            clock=lambda: NOW,
        ).admit(request)
        assert denied.attempt.lifecycle is PreparationLifecycle.REJECTED
        assert denied.attempt.reason_code is PreparationAdmissionReason.POLICY_DENIED
        assert denied.permit is None
    finally:
        database.dispose()


def test_concurrent_identical_admission_has_one_attempt_and_permit(tmp_path: Path) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    barrier = Barrier(2)

    def admit_once() -> object:
        barrier.wait()
        return service.admit(request)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda _: admit_once(), range(2)))
        assert results[0] == results[1]
        with database._migration_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM runtime_preparation_attempts")
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(text("SELECT COUNT(*) FROM preparation_permits")).scalar_one()
                == 1
            )
    finally:
        database.dispose()


def test_migration_from_previous_head_and_strict_history(tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "upgrade.sqlite3"))
    try:
        upgrade_database(database, "0015_m20_d6_planning_interactions")
        with database._migration_engine.connect() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            assert "runtime_preparation_attempts" not in names
        upgrade_database(database)
        with database._migration_engine.connect() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            assert {"runtime_preparation_attempts", "preparation_permits"} <= names
    finally:
        database.dispose()


def test_tampered_permit_digest_is_not_loaded(tmp_path: Path) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        admitted = service.admit(request)
        assert admitted.permit is not None
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE preparation_permits SET authority_sha256 = :invalid WHERE permit_id = :permit"
                ),
                {"invalid": "0" * 64, "permit": str(admitted.permit.permit_ref)},
            )
        with pytest.raises(PreparationPersistenceError, match="corrupt"):
            service.get_permit(admitted.permit.permit_ref)
    finally:
        database.dispose()


def test_expired_permit_and_missing_source_remain_historical(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, service, request = _setup(tmp_path)
    try:
        admitted = service.admit(request)
        assert admitted.permit is not None
        expired_service = CoreRuntimePreparationAdmissionService(
            database,
            policy,
            approvals,
            registry,
            clock=lambda: NOW + timedelta(minutes=16),
        )
        expired = expired_service.current_admission(admitted.attempt.preparation_ref)
        assert expired is not None and not expired.current_applicable
        assert expired.permit == admitted.permit
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE artifacts SET content_state = 'METADATA_ONLY' WHERE artifact_id = :id"
                ),
                {"id": str(admitted.attempt.context.source.raw_artifact_ref)},
            )
        source_missing = service.current_admission(admitted.attempt.preparation_ref)
        assert source_missing is not None and not source_missing.current_applicable
        assert (
            source_missing.current_reason is PreparationAdmissionReason.SOURCE_PROVENANCE_MISMATCH
        )
        assert service.get_permit(admitted.permit.permit_ref) == admitted.permit
    finally:
        database.dispose()


def test_missing_current_policy_is_not_auto_evaluated(tmp_path: Path) -> None:
    database, plan, _policy, _approvals, registry, _service, request = _setup(tmp_path)
    try:
        original = _profile(plan, approval=False)
        changed = original.model_copy(update={"require_operator_approval": True})
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((changed,)), clock=lambda: NOW
        )
        service = CoreRuntimePreparationAdmissionService(
            database,
            policy,
            CorePlanApprovalService(database, policy, clock=lambda: NOW),
            registry,
            clock=lambda: NOW,
        )
        with database.unit_of_work() as work:
            before = work.plan_decisions.list_for_plan(plan.execution_plan_id)
        rejected = service.admit(request)
        assert rejected.attempt.reason_code is PreparationAdmissionReason.POLICY_NOT_EVALUATED
        with database.unit_of_work() as work:
            assert work.plan_decisions.list_for_plan(plan.execution_plan_id) == before
    finally:
        database.dispose()


def test_rejected_attempt_reopens_without_permit_or_run(tmp_path: Path) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        rejected = service.admit(request.model_copy(update={"budgets": None}))
        assert rejected.attempt.lifecycle is PreparationLifecycle.REJECTED
        assert rejected.attempt.reserved_run_ref is None and rejected.permit is None
        config = database.config
        database.dispose()
        reopened = CoreDatabase(config)
        try:
            assert reopened is not database
            with reopened.unit_of_work() as work:
                assert (
                    work.runtime_preparations.get(rejected.attempt.preparation_ref)
                    == rejected.attempt
                )
                assert (
                    work.runtime_preparations.find_by_fingerprint(
                        rejected.attempt.request_fingerprint
                    )
                    == rejected.attempt
                )
        finally:
            reopened.dispose()
    finally:
        database.dispose()
