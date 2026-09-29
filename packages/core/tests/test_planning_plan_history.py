"""Immutable V2 plans, decision history, strict decoding and refs-only persistence."""

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from boberagent_contracts import (
    ArtifactRef,
    CredentialRef,
    ExecutionPlan,
    ExecutionPlanRef,
    ExecutionPlanStatus,
    ExecutionPlanV2,
    IsolationRequirement,
    SecretRef,
    execution_intent_digest,
)
from boberagent_contracts.plan_requirements import CredentialRequirement, SecretRequirement
from boberagent_contracts.plan_values import (
    BindingProvenance,
    CredentialValue,
    DeliveryChannel,
    ParameterBinding,
    ResolutionState,
    SecretValue,
    ValueType,
)
from boberagent_core import CoreDatabase, DatabaseConfig
from boberagent_core.planning import (
    ApprovalDocument,
    DecisionContext,
    OperatorPlanApproval,
    PlanDecisionRecord,
    PlanDecisionRef,
    PlanningRequest,
    PlanPolicyAssessment,
    PlanPolicyDecision,
    PlanProposal,
    PlanValidation,
    PlanValidationReason,
    PlanValidationReasonCode,
    PlanValidationStatus,
    PolicyDocument,
    ValidationDocument,
    decision_context_fingerprint,
)
from boberagent_core.planning import (
    PlanningAttemptLifecycle as State,
)
from boberagent_core.planning.errors import PlanningConflict, PlanningPersistenceError
from plan_test_fixtures import NOW, plan_fixture
from planning_persistence_fixtures import attempt_fixture, context_fixture, finalize, seed
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_v2_finalized_round_trip_digest_order_and_nested_immutability(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    attempt = attempt_fixture()
    plan = plan_fixture()
    finalize(database, attempt, plan)
    with database.unit_of_work() as work:
        stored = work.execution_plans.get(plan.execution_plan_id)
        assert stored is not None and stored.plan == plan
        assert work.execution_plans.get_by_attempt(attempt.planning_attempt_ref) == stored
        assert work.execution_plans.get_by_intent_digest(execution_intent_digest(plan)) == (stored,)
        completed = work.planning_attempts.get(attempt.planning_attempt_ref)
        assert completed is not None and completed.lifecycle is State.COMPLETED
        assert completed.finalized_plan == plan and completed.completed_at == NOW
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            loaded = work.execution_plans.get(plan.execution_plan_id)
            assert loaded == stored and loaded is not None
            assert loaded.plan.invocation.arguments == plan.invocation.arguments
            with pytest.raises(ValidationError, match="frozen_instance"):
                loaded.plan.source.raw_sha256 = "e" * 64
    finally:
        reopened.dispose()


def test_same_semantics_same_digest_changed_order_new_ref_supersedes(
    database: CoreDatabase,
) -> None:
    seed(database)
    plan = plan_fixture()
    first = attempt_fixture()
    finalize(database, first, plan)
    duplicate = ExecutionPlanV2.model_validate(
        {**plan.model_dump(), "execution_plan_id": "plan-same-intent"}
    )
    assert execution_intent_digest(duplicate) == execution_intent_digest(plan)
    changed = ExecutionPlanV2.model_validate(
        {
            **plan.model_dump(),
            "execution_plan_id": "plan-reordered",
            "invocation": {
                **plan.invocation.model_dump(),
                "arguments": tuple(reversed(plan.invocation.arguments)),
            },
        }
    )
    assert execution_intent_digest(changed) != execution_intent_digest(plan)
    proposal = PlanProposal(source=changed.source, invocation=changed.invocation)
    request = PlanningRequest.model_validate({**first.request.model_dump(), "proposal": proposal})
    second = attempt_fixture("planning-reordered", request=request)
    with database.unit_of_work() as work:
        work.planning_attempts.add(second)
        stored = work.planning_attempts.finalize(
            second.planning_attempt_ref,
            changed,
            intent_sha256=execution_intent_digest(changed),
            expected_state=State.REQUESTED,
            expected_revision=0,
            completed_at=NOW,
            supersedes_plan_ref=plan.execution_plan_id,
        )
        assert stored.supersedes_plan_ref == plan.execution_plan_id
        original = work.execution_plans.get(plan.execution_plan_id)
        assert original is not None and original.plan == plan


def test_wrong_digest_legacy_and_identity_rewrite_rejected(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    plan = plan_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        with pytest.raises(PlanningPersistenceError, match="digest"):
            work.execution_plans.add_finalized(
                attempt.planning_attempt_ref, plan, intent_sha256="f" * 64
            )
        legacy = ExecutionPlan(
            execution_plan_id=ExecutionPlanRef("legacy-plan"),
            status=ExecutionPlanStatus.APPROVED,
            isolation=IsolationRequirement(profile="legacy"),
            runtime_type="python",
            entrypoint="check.py",
            source_artifact_ref=ArtifactRef("artifact-raw"),
            created_at=NOW,
        )
        with pytest.raises(PlanningPersistenceError, match="V2"):
            work.execution_plans.add_finalized(
                attempt.planning_attempt_ref, cast(ExecutionPlanV2, legacy), intent_sha256="f" * 64
            )
    finalize(database, attempt, plan)
    with database.unit_of_work() as work, pytest.raises(PlanningConflict):
        work.execution_plans.add_finalized(
            attempt.planning_attempt_ref, plan, intent_sha256=execution_intent_digest(plan)
        )
    assert not hasattr(work.execution_plans, "update")
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="immutable"),
    ):
        connection.execute(
            text("UPDATE execution_plans SET intent_sha256 = :digest"), {"digest": "f" * 64}
        )


def decisions(attempt_ref: str = "planning-d2") -> tuple[PlanDecisionRecord, ...]:
    plan = plan_fixture()
    attempt = attempt_fixture(attempt_ref)
    context = context_fixture(attempt, execution_intent_digest(plan))
    documents: tuple[ValidationDocument | PolicyDocument | ApprovalDocument, ...] = (
        ValidationDocument(
            value=PlanValidation(
                execution_plan_ref=plan.execution_plan_id,
                intent_sha256=context.intent_sha256,
                mission_ref=plan.mission_ref,
                scope_sha256=context.scope_sha256,
                validation_profile="m20-d-validation",
                validation_version="1",
                status=PlanValidationStatus.VALID,
                reasons=(PlanValidationReason(code=PlanValidationReasonCode.CONSISTENT_INTENT),),
                assessed_at=NOW,
            )
        ),
        PolicyDocument(
            value=PlanPolicyAssessment(
                execution_plan_ref=plan.execution_plan_id,
                intent_sha256=context.intent_sha256,
                mission_ref=plan.mission_ref,
                scope_sha256=context.scope_sha256,
                policy_profile="m20-python-single-target",
                policy_version="1",
                decision=PlanPolicyDecision.ALLOW,
                reason_codes=("BOUNDED",),
                assessed_at=NOW,
            )
        ),
        ApprovalDocument(
            value=OperatorPlanApproval(
                execution_plan_ref=plan.execution_plan_id,
                intent_sha256=context.intent_sha256,
                mission_ref=plan.mission_ref,
                scope_sha256=context.scope_sha256,
                policy_profile="m20-python-single-target",
                policy_version="1",
                decision="APPROVE",
                operator_id="operator-test",
                decided_at=NOW,
            )
        ),
    )
    return tuple(
        PlanDecisionRecord(
            decision_ref=PlanDecisionRef(f"decision-{index}"),
            document=document,
            context=context,
            created_at=NOW,
        )
        for index, document in enumerate(documents)
    )


def test_decisions_append_round_trip_restart_no_authority(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    finalize(database, attempt_fixture())
    records = decisions()
    with database.unit_of_work() as work:
        for record in records:
            assert work.plan_decisions.append(record) == record
            assert work.plan_decisions.append(record) == record
            assert work.plan_decisions.get(record.decision_ref) == record
        assert work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id) == records
        assert (
            work.plan_decisions.find_by_context(
                plan_fixture().execution_plan_id, decision_context_fingerprint(records[0].context)
            )
            == records
        )
    with database._migration_engine.connect() as connection:
        for table in (
            "capability_runs",
            "capability_routing_decisions",
            "secret_access_records",
            "interactions",
        ):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == (
                1 if table == "capability_runs" else 0
            )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            assert work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id) == records
    finally:
        reopened.dispose()


def test_reevaluation_preserves_history_context_and_decision_identity(
    database: CoreDatabase,
) -> None:
    seed(database)
    finalize(database, attempt_fixture())
    old = decisions()[1]
    context = DecisionContext.model_validate({**old.context.model_dump(), "scope_sha256": "a" * 64})
    value = PlanPolicyAssessment.model_validate(
        {
            **old.document.value.model_dump(),
            "scope_sha256": context.scope_sha256,
            "decision": "DENY",
        }
    )
    new = PlanDecisionRecord(
        decision_ref=PlanDecisionRef("decision-new"),
        document=PolicyDocument(value=value),
        context=context,
        created_at=NOW,
    )
    for change in (
        {"scope_sha256": "b" * 64},
        {"prerequisite_state_sha256": "c" * 64},
        {
            "policy": {
                **context.policy.model_dump(),
                "maximum_limits": {
                    **context.policy.maximum_limits.model_dump(),
                    "wall_time_seconds": 20,
                },
            }
        },
    ):
        changed = DecisionContext.model_validate({**context.model_dump(), **change})
        assert decision_context_fingerprint(changed) != decision_context_fingerprint(context)
    with database.unit_of_work() as work:
        work.plan_decisions.append(old)
        work.plan_decisions.append(new)
        assert work.plan_decisions.find_by_context(
            plan_fixture().execution_plan_id, decision_context_fingerprint(old.context)
        ) == (old,)
        assert len(work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id)) == 2
        conflict = new.model_copy(update={"decision_ref": old.decision_ref})
        with pytest.raises(PlanningConflict):
            work.plan_decisions.append(conflict)
        assert work.plan_decisions.get(old.decision_ref) == old
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="immutable"),
    ):
        connection.execute(text("DELETE FROM plan_decisions"))


def test_wrong_decision_digest_rejected(database: CoreDatabase) -> None:
    seed(database)
    finalize(database, attempt_fixture())
    record = decisions()[0]
    data = record.model_dump()
    data["context"]["intent_sha256"] = "a" * 64
    data["document"]["value"]["intent_sha256"] = "a" * 64
    bad = PlanDecisionRecord.model_validate(data)
    with database.unit_of_work() as work, pytest.raises(PlanningConflict, match="exact plan"):
        work.plan_decisions.append(bad)


@pytest.mark.parametrize(
    ("table", "column", "content"),
    [
        ("planning_attempts", "schema_version", "planning-attempt-v99"),
        ("planning_attempts", "request_json", '{"plaintext":"must-not-render"}'),
        ("planning_attempts", "history_json", '{"schema_version":"plan-proposal-history-v99"}'),
        ("execution_plans", "schema_version", "execution-plan-v99"),
        ("execution_plans", "intent_sha256", "f" * 64),
        ("execution_plans", "plan_json", '{"plaintext":"must-not-render"}'),
        ("plan_decisions", "schema_version", "plan-decision-v99"),
        (
            "plan_decisions",
            "record_json",
            '{"schema_version":"plan-decision-v99","plaintext":"must-not-render"}',
        ),
        ("plan_decisions", "context_fingerprint", "f" * 64),
    ],
)
def test_corrupt_or_unknown_documents_fail_closed_safe_error(
    database: CoreDatabase, table: str, column: str, content: str
) -> None:
    seed(database)
    attempt = attempt_fixture()
    finalize(database, attempt)
    with database.unit_of_work() as work:
        work.plan_decisions.append(decisions()[0])
    # Explicit corruption bypasses immutability guards; normal APIs never mutate these rows.
    trigger = (
        "planning_attempt_terminal" if table == "planning_attempts" else table + "_immutable_update"
    )
    with database._migration_engine.begin() as connection:
        connection.execute(text(f"DROP TRIGGER {trigger}"))
        if table == "planning_attempts":
            connection.execute(text("DROP TRIGGER planning_attempt_identity"))
        connection.execute(text(f"UPDATE {table} SET {column} = :content"), {"content": content})
    with database.unit_of_work() as work, pytest.raises(PlanningPersistenceError) as raised:
        if table == "planning_attempts":
            work.planning_attempts.get(attempt.planning_attempt_ref)
        elif table == "execution_plans":
            work.execution_plans.get(plan_fixture().execution_plan_id)
        else:
            work.plan_decisions.get(decisions()[0].decision_ref)
    assert "must-not-render" not in str(raised.value)


def test_sensitive_plan_database_contains_refs_never_value_or_grants(
    database: CoreDatabase,
) -> None:
    seed(database)
    secret = "harmless-secret-never-used-by-d2"
    plan = plan_fixture()
    secret_binding = ParameterBinding(
        binding_id="password",
        parameter_id="password",
        value_type=ValueType.SECRET,
        channel=DeliveryChannel.STANDARD_INPUT,
        required=True,
        resolution=ResolutionState.RESOLVED,
        value=SecretValue(secret_ref=SecretRef("secret-d2")),
        provenance=BindingProvenance(origin="OPERATOR"),
    )
    credential_binding = ParameterBinding(
        binding_id="account",
        parameter_id="account",
        value_type=ValueType.CREDENTIAL,
        channel=DeliveryChannel.STANDARD_INPUT,
        required=True,
        resolution=ResolutionState.RESOLVED,
        value=CredentialValue(
            credential_ref=CredentialRef("credential-d2"), secret_role="password"
        ),
        provenance=BindingProvenance(origin="OPERATOR"),
    )
    sensitive = ExecutionPlanV2.model_validate(
        {
            **plan.model_dump(),
            "bindings": (*plan.bindings, secret_binding, credential_binding),
            "sensitive_requirements": (
                SecretRequirement(
                    secret_ref=SecretRef("secret-d2"),
                    binding_id="password",
                    role="password",
                    purpose="test intent only",
                ),
                CredentialRequirement(
                    credential_ref=CredentialRef("credential-d2"),
                    binding_id="account",
                    role="password",
                    purpose="test intent only",
                ),
            ),
        }
    )
    request = attempt_fixture().request
    proposal = PlanProposal(
        source=plan.source,
        bindings=sensitive.bindings,
        sensitive_requirements=sensitive.sensitive_requirements,
    )
    request = PlanningRequest.model_validate({**request.model_dump(), "proposal": proposal})
    attempt = attempt_fixture(request=request)
    finalize(database, attempt, sensitive)
    with database.unit_of_work() as work:
        record = decisions()[0]
        record = PlanDecisionRecord.model_validate(
            {
                **record.model_dump(),
                "document": {
                    "kind": "VALIDATION",
                    "value": {
                        **record.document.value.model_dump(),
                        "intent_sha256": execution_intent_digest(sensitive),
                    },
                },
                "context": {
                    **record.context.model_dump(),
                    "intent_sha256": execution_intent_digest(sensitive),
                },
            }
        )
        work.plan_decisions.append(record)
    with database._migration_engine.connect() as connection:
        documents: list[tuple[object, ...]] = []
        for table, columns in (
            ("planning_attempts", "request_json, history_json"),
            ("execution_plans", "plan_json"),
            ("plan_decisions", "record_json"),
        ):
            documents.extend(
                tuple(row) for row in connection.execute(text(f"SELECT {columns} FROM {table}"))
            )
    serialized = json.dumps(documents)
    assert "secret-d2" in serialized and "credential-d2" in serialized
    assert (
        secret not in serialized and hashlib.sha256(secret.encode()).hexdigest() not in serialized
    )
    assert "transport_grant" not in serialized and "authorization" not in serialized
    assert not hasattr(work.plan_decisions, "update")
