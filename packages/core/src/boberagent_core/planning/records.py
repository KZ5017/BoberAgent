"""Versioned persistence values; records are history, never execution authority."""

from typing import Annotated, Literal, Self

from boberagent_contracts import DomainRef, ExecutionPlanRef, ExecutionPlanV2, Sha256Digest
from boberagent_contracts._base import FrozenContractModel
from pydantic import AwareDatetime, Field, model_validator

from .models import (
    DecisionContext,
    OperatorPlanApproval,
    PlanningAttemptRef,
    PlanPolicyAssessment,
    PlanProposalRevision,
    PlanValidation,
)


class PlanDecisionRef(DomainRef):
    """Core-owned identity of one immutable assessment/approval record."""


class ProposalHistory(FrozenContractModel):
    schema_version: Literal["plan-proposal-history-v1"] = "plan-proposal-history-v1"
    revisions: tuple[PlanProposalRevision, ...] = ()


class StoredExecutionPlan(FrozenContractModel):
    planning_attempt_ref: PlanningAttemptRef
    plan: ExecutionPlanV2
    intent_sha256: Sha256Digest
    supersedes_plan_ref: ExecutionPlanRef | None = None


class ValidationDocument(FrozenContractModel):
    kind: Literal["VALIDATION"] = "VALIDATION"
    value: PlanValidation


class PolicyDocument(FrozenContractModel):
    kind: Literal["POLICY"] = "POLICY"
    value: PlanPolicyAssessment


class ApprovalDocument(FrozenContractModel):
    kind: Literal["APPROVAL"] = "APPROVAL"
    value: OperatorPlanApproval


type DecisionDocument = Annotated[
    ValidationDocument | PolicyDocument | ApprovalDocument, Field(discriminator="kind")
]


class PlanDecisionRecord(FrozenContractModel):
    schema_version: Literal["plan-decision-v1"] = "plan-decision-v1"
    decision_ref: PlanDecisionRef
    document: DecisionDocument
    context: DecisionContext
    created_at: AwareDatetime

    @model_validator(mode="after")
    def identity(self) -> Self:
        value = self.document.value
        if (
            value.mission_ref != self.context.mission_ref
            or value.intent_sha256 != self.context.intent_sha256
            or value.scope_sha256 != self.context.scope_sha256
        ):
            raise ValueError("decision and context identities disagree")
        if isinstance(value, PlanValidation):
            if (value.validation_profile, value.validation_version) != (
                self.context.validation_profile,
                self.context.validation_version,
            ):
                raise ValueError("validation profile does not match context")
            timestamp = value.assessed_at
        else:
            if (value.policy_profile, value.policy_version) != (
                self.context.policy.profile,
                self.context.policy.version,
            ):
                raise ValueError("policy profile does not match context")
            timestamp = (
                value.decided_at if isinstance(value, OperatorPlanApproval) else value.assessed_at
            )
        if timestamp != self.created_at:
            raise ValueError("decision timestamp does not match record")
        return self
