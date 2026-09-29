"""Pure D4 validator defenses and semantic digest invariants; no source execution."""

from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import ExecutionPlanRef, execution_intent_digest
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import (
    EffectScope,
    FilesystemConstraints,
    NetworkConstraints,
    NetworkDestinationClass,
    NetworkRule,
)
from boberagent_contracts.plan_values import (
    BindingToken,
    FlagToken,
    LiteralValue,
    NetworkTarget,
    OptionToken,
    PositionalToken,
)
from boberagent_core import CoreDatabase
from boberagent_core.inspections.classification_models import semantic_digest
from boberagent_core.inspections.semantic_models import (
    BehaviorKind,
    DependencyKind,
    ImportKind,
    SemanticInspectionDocument,
)
from boberagent_core.planning.construction import CoreExecutionPlanningService, _evidence, _proposal
from boberagent_core.planning.construction_models import PlanningEvidence
from boberagent_core.planning.models import PlanProposal
from boberagent_core.planning.models import PlanValidationStatus as Status
from boberagent_core.planning.validation import assess_proposal, validate_plan
from planning_construction_fixtures import prepared
from test_core_poc_acquisition import NOW


def snapshot(database: CoreDatabase, tmp_path: Path) -> tuple[PlanningEvidence, PlanProposal]:
    _, request = prepared(database, tmp_path)
    with database.unit_of_work() as work:
        attempt = work.planning_attempts.get(request.planning_attempt_ref)
        assert attempt is not None
        evidence = _evidence(work, attempt, request)
    return evidence, _proposal(request, evidence)


def changed_semantic(evidence: PlanningEvidence, changes: dict[str, object]) -> PlanningEvidence:
    """Adversarial in-memory snapshot, NOT rewritten persisted C2/C3 history.

    Retain a deliberately unearned AUTOMATIC label to prove D4's independent
    semantic checks. Admission refuses such inconsistent authoritative records.
    """
    semantic = SemanticInspectionDocument.model_validate(evidence.semantic.model_dump() | changes)
    original = evidence.attempt.request
    c3 = original.inspection.classification.model_copy(
        update={"semantic_document_sha256": semantic_digest(semantic)}
    )
    pins = original.inspection.model_copy(
        update={"classification": c3, "classification_sha256": canonical_digest(c3)}
    )
    attempt = evidence.attempt.model_copy(
        update={"request": original.model_copy(update={"inspection": pins})}
    )
    return evidence.model_copy(update={"attempt": attempt, "semantic": semantic})


@pytest.mark.parametrize(
    "kind",
    [
        BehaviorKind.FILE_WRITE,
        BehaviorKind.FILE_DELETE,
        BehaviorKind.NETWORK_BIND_LISTEN,
        BehaviorKind.SUBPROCESS_EXECUTION,
        BehaviorKind.SHELL_EXECUTION,
        BehaviorKind.NETWORK_RESOLUTION,
    ],
)
def test_automatic_label_never_overrides_material_effects(
    database: CoreDatabase, tmp_path: Path, kind: BehaviorKind
) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    behavior = evidence.semantic.behavior_indicators[0]
    altered = behavior.model_copy(update={"kind": kind, "reason": "FILE_EFFECT_SCOPE_UNKNOWN"})
    evidence = changed_semantic(evidence, {"behavior_indicators": (altered,)})
    result = assess_proposal(proposal, evidence)
    assert result.status is Status.INVALID
    # Even missing reviewed layout cannot turn material uncertainty into HITL.
    assert (
        assess_proposal(proposal.model_copy(update={"invocation": None}), evidence).status
        is Status.INVALID
    )


@pytest.mark.parametrize(
    "scope", ["FILE_EFFECT_SCOPE_BROAD", "FILE_EFFECT_SCOPE_UNKNOWN", "FILE_EFFECT_SCOPE_BOUNDED"]
)
def test_no_mutation_in_first_slice(database: CoreDatabase, tmp_path: Path, scope: str) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    behavior = evidence.semantic.behavior_indicators[0].model_copy(
        update={"kind": BehaviorKind.FILE_DELETE, "reason": scope}
    )
    evidence = changed_semantic(evidence, {"behavior_indicators": (behavior,)})
    assert assess_proposal(proposal, evidence).status is Status.INVALID


@pytest.mark.parametrize(
    "kind", [DependencyKind.UNKNOWN_DEPENDENCY, DependencyKind.DECLARED_PACKAGE]
)
def test_unresolved_dependency_is_not_invented_as_stdlib(
    database: CoreDatabase, tmp_path: Path, kind: DependencyKind
) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    deps = evidence.semantic.dependency_observations
    altered = deps[0].model_copy(update={"kind": kind, "import_kind": ImportKind.UNKNOWN})
    evidence = changed_semantic(evidence, {"dependency_observations": (altered, *deps[1:])})
    report = assess_proposal(proposal, evidence)
    assert report.status is Status.INVALID
    assert report.reasons[0].code.value == "DEPENDENCY_UNSUPPORTED"


@pytest.mark.parametrize(
    "destination",
    [
        NetworkDestinationClass.PUBLIC_INTERNET,
        NetworkDestinationClass.MULTI_TARGET,
        NetworkDestinationClass.UNKNOWN,
        NetworkDestinationClass.CALLBACK,
        NetworkDestinationClass.PREPARATION_EGRESS,
        NetworkDestinationClass.LISTENER_BIND,
    ],
)
def test_only_selected_endpoint_network_intent(
    database: CoreDatabase, tmp_path: Path, destination: NetworkDestinationClass
) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    network = NetworkConstraints(
        rules=(
            NetworkRule(
                destination=destination, transport="tcp", ports=(80,), endpoint_binding_id="host"
            ),
        )
    )
    assert (
        assess_proposal(proposal.model_copy(update={"network": network}), evidence).status
        is Status.INVALID
    )


@pytest.mark.parametrize(
    "change",
    [
        "entry-hash",
        "entry-path",
        "evidence-digest",
        "source",
        "environment",
        "unknown-fs",
        "unknowns",
        "missing-dependency",
    ],
)
def test_rejects_unproven_intent(database: CoreDatabase, tmp_path: Path, change: str) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    entrypoint = proposal.entrypoint
    assert entrypoint is not None
    if change == "entry-hash":
        proposal = proposal.model_copy(
            update={"entrypoint": entrypoint.model_copy(update={"entry_sha256": "f" * 64})}
        )
    elif change == "entry-path":
        proposal = proposal.model_copy(
            update={"entrypoint": entrypoint.model_copy(update={"relative_path": "elsewhere.py"})}
        )
    elif change == "evidence-digest":
        evidence = evidence.model_copy(
            update={
                "attempt": evidence.attempt.model_copy(
                    update={
                        "request": evidence.attempt.request.model_copy(
                            update={
                                "inspection": evidence.attempt.request.inspection.model_copy(
                                    update={"classification_sha256": "f" * 64}
                                )
                            }
                        )
                    }
                )
            }
        )
    elif change == "source":
        proposal = proposal.model_copy(
            update={"source": proposal.source.model_copy(update={"raw_sha256": "f" * 64})}
        )
    elif change == "environment":
        from boberagent_contracts.plan_values import EnvironmentBinding

        proposal = proposal.model_copy(
            update={"environment": (EnvironmentBinding(name="INHERITED", binding_id="host"),)}
        )
    elif change == "unknown-fs":
        proposal = proposal.model_copy(
            update={
                "filesystem": FilesystemConstraints(
                    scope=EffectScope.UNKNOWN, cleanup="OPERATOR_REVIEW"
                )
            }
        )
    elif change == "unknowns":
        proposal = proposal.model_copy(update={"unresolved_requirement_ids": ("critical-effect",)})
    else:
        proposal = proposal.model_copy(update={"dependencies": proposal.dependencies[:-1]})
    assert assess_proposal(proposal, evidence).status is Status.INVALID


@pytest.mark.parametrize(
    "tokens", ["positional", "option-binding", "bad-option", "flag", "repeat", "unknown-binding"]
)
def test_ordered_reviewed_layout_is_not_arbitrary_shell(
    database: CoreDatabase, tmp_path: Path, tokens: str
) -> None:
    evidence, proposal = snapshot(database, tmp_path)
    assert proposal.invocation is not None
    original = proposal.invocation.arguments
    arguments = {
        "positional": (PositionalToken(binding_id="host"), PositionalToken(binding_id="port")),
        "option-binding": (
            OptionToken(name="--host"),
            BindingToken(binding_id="host"),
            OptionToken(name="--port"),
            BindingToken(binding_id="port"),
        ),
        "bad-option": (OptionToken(name="--host"), *original),
        "flag": (FlagToken(name="--force"), *original),
        "repeat": (*original, original[0]),
        "unknown-binding": (PositionalToken(binding_id="missing"), *original),
    }[tokens]
    candidate = proposal.model_copy(
        update={"invocation": proposal.invocation.model_copy(update={"arguments": arguments})}
    )
    report = assess_proposal(candidate, evidence)
    assert report.status is (
        Status.VALID if tokens in {"positional", "option-binding"} else Status.INVALID
    )


def test_intent_digest_sensitive_to_semantics_not_generated_ids(
    database: CoreDatabase, tmp_path: Path
) -> None:
    _, request = prepared(database, tmp_path)
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    plan = result.attempt.finalized_plan
    assert plan is not None
    digest = execution_intent_digest(plan)
    assert digest == execution_intent_digest(
        plan.model_copy(
            update={
                "execution_plan_id": ExecutionPlanRef("execution-plan-other"),
                "created_at": NOW + timedelta(hours=1),
            }
        )
    )
    assert digest != execution_intent_digest(
        plan.model_copy(
            update={
                "invocation": plan.invocation.model_copy(
                    update={"arguments": tuple(reversed(plan.invocation.arguments))}
                )
            }
        )
    )
    assert isinstance(plan.target, NetworkTarget)
    assert digest != execution_intent_digest(
        plan.model_copy(
            update={"target": plan.target.model_copy(update={"address": "192.0.2.201"})}
        )
    )
    bindings = tuple(
        item
        if item.binding_id != "port"
        else item.model_copy(update={"value": LiteralValue(value=81)})
        for item in plan.bindings
    )
    assert digest != execution_intent_digest(plan.model_copy(update={"bindings": bindings}))
    assert digest != execution_intent_digest(
        plan.model_copy(update={"limits": plan.limits.model_copy(update={"wall_time_seconds": 31})})
    )
    with database.unit_of_work() as work:
        attempt = work.planning_attempts.get(request.planning_attempt_ref)
        assert attempt is not None
        evidence = _evidence(work, attempt, request)
    assert validate_plan(plan, evidence).status is Status.VALID
    bad = plan.model_copy(update={"schema_version": "execution-plan-v999"})
    assert validate_plan(bad, evidence).status is Status.INVALID
    assert (
        validate_plan(plan.model_copy(update={"permission": True}), evidence).status
        is Status.INVALID
    )
    assert (
        assess_proposal(
            _proposal(request, evidence).model_copy(update={"allow": True}), evidence
        ).status
        is Status.INVALID
    )
