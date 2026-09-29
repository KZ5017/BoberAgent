"""Pure D4-v1 validator. Intent consistency is neither safety nor permission."""

from boberagent_contracts import ExecutionPlanV2
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import (
    EffectScope,
    ExecutionLocation,
    NetworkDestinationClass,
    PlanDependencyKind,
)
from boberagent_contracts.plan_values import (
    BindingToken,
    DeliveryChannel,
    LiteralValue,
    MissionTargetValue,
    NetworkTarget,
    OperatorValue,
    OptionToken,
    OptionValueToken,
    PositionalToken,
    ResolutionState,
    TargetRole,
    ValueType,
)
from pydantic import BaseModel

from boberagent_core.inspections.classification_models import (
    ReasonDisposition,
    SupportClassification,
    disposition,
    semantic_digest,
)
from boberagent_core.inspections.semantic_models import (
    BehaviorKind,
    CoverageStatus,
    DependencyKind,
    EpistemicState,
    ImportKind,
    ParameterRole,
    SourceOrigin,
)

from .construction_models import ConstructionAssessment, PlanningEvidence
from .models import PlanProposal, PlanValidationReason
from .models import PlanValidationReasonCode as Code
from .models import PlanValidationStatus as Status

VALIDATOR_PROFILE = "m20-d4-plan-validator"
VALIDATOR_VERSION = "1"


def check_model_fields(value: object) -> None:
    """Reject hidden model_copy fields before JSON serialization can discard them."""
    if isinstance(value, BaseModel):
        if set(value.__dict__) - set(type(value).model_fields):
            raise ValueError("SCHEMA_INVALID")
        for name in type(value).model_fields:
            check_model_fields(getattr(value, name))
    elif isinstance(value, tuple | list):
        for item in value:
            check_model_fields(item)


def _answer(code: Code, *refs: str, waiting: bool = False) -> ConstructionAssessment:
    return ConstructionAssessment(
        status=Status.REQUIRES_INPUT if waiting else Status.INVALID,
        reasons=(PlanValidationReason(code=code, evidence_refs=tuple(sorted(set(refs)))),),
    )


def assess_proposal(proposal: PlanProposal, evidence: PlanningEvidence) -> ConstructionAssessment:
    """Fixed-order checks over snapshots only. Never reads source or current runtime.

    V1 requires every selected entrypoint parameter to have an explicit binding,
    including optional/defaulted parameters. No hidden default or CLI inference.
    Only reviewed option+value and positional/binding tokens are initially supported.
    """
    try:
        check_model_fields(proposal)
        check_model_fields(evidence)
        proposal = PlanProposal.model_validate_json(proposal.model_dump_json())
        evidence = PlanningEvidence.model_validate_json(evidence.model_dump_json())
    except (ValueError, TypeError, AttributeError):
        return _answer(Code.SCHEMA_INVALID)
    attempt, semantic, scope = evidence.attempt, evidence.semantic, evidence.scope
    request = attempt.request
    target = proposal.target
    # 1 schema (above), 2 ownership/scope, 3 source, 4 provenance, 5 admission.
    if scope.mission_ref != request.mission_ref:
        return _answer(Code.MISSION_MISMATCH)
    if not isinstance(target, NetworkTarget) or target.role not in {
        TargetRole.HOST,
        TargetRole.IP,
        TargetRole.SERVICE_ENDPOINT,
    }:
        return _answer(Code.TARGET_ROLE_MISMATCH)
    if evidence.asset is None or evidence.asset.mission_ref != request.mission_ref:
        return _answer(Code.MISSION_MISMATCH)
    if (
        target.asset_ref != evidence.asset.asset_ref
        or not any(
            item.asset_ref == target.asset_ref and item.address == target.address
            for item in scope.assets
        )
        or target.address != evidence.asset.primary_address
    ):
        return _answer(Code.OUT_OF_SCOPE)
    if target.service_ref is not None and (
        evidence.service is None
        or evidence.service.service_ref != target.service_ref
        or evidence.service.asset_ref != target.asset_ref
        or evidence.service.port != target.port
        or evidence.service.transport != target.transport
    ):
        return _answer(Code.MISSION_MISMATCH, str(target.service_ref))
    if proposal.source != request.source:
        return _answer(Code.SOURCE_MISMATCH)
    if any(
        citation.raw_artifact_ref != request.source.raw_artifact_ref
        or citation.raw_sha256 != request.source.raw_sha256
        or citation.manifest_artifact_ref != request.source.manifest_artifact_ref
        or citation.manifest_sha256 != request.source.manifest_sha256
        for citation in semantic.citations
    ):
        return _answer(Code.EVIDENCE_MISMATCH)
    classification = request.inspection.classification
    if request.inspection.classification_sha256 != canonical_digest(classification) or (
        classification.semantic_document_sha256 != semantic_digest(semantic)
        or semantic.document_version != "m20-c2-deterministic-v2"
        or classification.classifier_version != "2"
    ):
        return _answer(Code.EVIDENCE_MISMATCH)
    if classification.classification is SupportClassification.UNSUPPORTED or (
        classification.blocking_unknown_refs
        or classification.blocking_conflict_refs
        or any(
            disposition(reason.code) is ReasonDisposition.BLOCKER
            for reason in classification.reasons
        )
    ):
        return _answer(Code.C3_BLOCKER, *classification.blocking_unknown_refs)
    # Assisted input is deliberately non-final in D4. Check material effects below
    # before allowing a bounded wait; operator input cannot clear uncertainty.
    # 6 entrypoint and exact entry identity.
    entries = tuple(
        item
        for item in semantic.entrypoint_candidates
        if (
            item.origin is SourceOrigin.CODE
            and item.epistemic_state is EpistemicState.OBSERVED
            and item.runtime == "python"
            and item.invocation_style == "SCRIPT_MAIN_GUARD"
        )
    )
    if not entries:
        return _answer(Code.ENTRYPOINT_INVALID)
    entry = entries[0] if len(entries) == 1 else None
    if entry is not None:
        selected = proposal.entrypoint
        coverage = next(
            (item for item in semantic.coverage if item.path == entry.source_path), None
        )
        if (
            selected is None
            or coverage is None
            or coverage.status is not CoverageStatus.INSPECTED
            or (
                selected.relative_path != entry.source_path
                or selected.language != "python"
                or selected.invocation_form != "SCRIPT"
                or selected.entry_sha256 != coverage.sha256
                or selected.evidence_ids != (entry.item_id,)
                or not entry.citations
                or not all(
                    any(
                        fact.kind == kind
                        and fact.source_path == entry.source_path
                        and fact.origin is SourceOrigin.CODE
                        and fact.epistemic_state is EpistemicState.OBSERVED
                        for fact in semantic.facts
                    )
                    for kind in ("PYTHON_SOURCE", "MAIN_GUARD")
                )
                or any(
                    citation.entry_sha256 != selected.entry_sha256 for citation in entry.citations
                )
            )
        ):
            return _answer(Code.ENTRYPOINT_INVALID, entry.item_id)
    # 7 reviewed layout, 8 binding completeness/types, 9 roles, 10 single target.
    parameters = {item.item_id: item for item in semantic.parameter_candidates}
    selected_refs = set(entry.parameter_candidate_refs) if entry else set()
    layout = proposal.invocation
    if layout is not None and (
        len(set(layout.evidence_ids)) != len(layout.evidence_ids)
        or (
            set(layout.evidence_ids) != selected_refs
            if entry
            else not set(layout.evidence_ids) <= set(parameters)
        )
    ):
        return _answer(Code.INVOCATION_LAYOUT_INVALID)
    by_parameter = {item.parameter_id: item for item in proposal.bindings}
    by_binding = {item.binding_id: item for item in proposal.bindings}
    if len(by_parameter) != len(proposal.bindings) or len(by_binding) != len(proposal.bindings):
        return _answer(Code.INVOCATION_LAYOUT_INVALID)
    for binding in proposal.bindings:
        parameter = parameters.get(binding.parameter_id)
        if (
            parameter is None
            or (entry and binding.parameter_id not in selected_refs)
            or (
                (entry is not None and parameter.source_path != entry.source_path)
                or parameter.origin is not SourceOrigin.CODE
                or parameter.epistemic_state is not EpistemicState.OBSERVED
            )
        ):
            return _answer(Code.INVOCATION_LAYOUT_INVALID, binding.parameter_id)
        if (
            binding.channel is not DeliveryChannel.ARGUMENT
            or binding.required is not parameter.required
        ):
            return _answer(Code.BINDING_TYPE_MISMATCH, parameter.item_id)
        if binding.resolution is not ResolutionState.RESOLVED:
            return _answer(Code.UNRESOLVED_BINDING, parameter.item_id)
        if binding.provenance.evidence_ids != (parameter.item_id,):
            return _answer(Code.INVOCATION_LAYOUT_INVALID, parameter.item_id)
        value = binding.value
        if parameter.role is ParameterRole.TARGET_HOST:
            if (
                not isinstance(value, MissionTargetValue)
                or binding.value_type is not ValueType.TARGET
                or (value.target_role is not target.role or binding.provenance.origin != "MISSION")
            ):
                return _answer(Code.TARGET_ROLE_MISMATCH, parameter.item_id)
        elif parameter.role in {ParameterRole.TARGET_PORT, ParameterRole.TIMEOUT}:
            if (
                not isinstance(value, LiteralValue | OperatorValue)
                or binding.value_type is not ValueType.INTEGER
            ):
                return _answer(Code.BINDING_TYPE_MISMATCH, parameter.item_id)
            if binding.provenance.origin != (
                "OPERATOR" if isinstance(value, OperatorValue) else "PLANNING"
            ) or (
                isinstance(value, OperatorValue) and binding.provenance.answer_id != value.answer_id
            ):
                return _answer(Code.INVOCATION_LAYOUT_INVALID, parameter.item_id)
            if parameter.role is ParameterRole.TARGET_PORT and (
                target.port is None or value.value != target.port
            ):
                return _answer(Code.TARGET_ROLE_MISMATCH, parameter.item_id)
            if parameter.role is ParameterRole.TIMEOUT and (
                not isinstance(value.value, int)
                or isinstance(value.value, bool)
                or value.value <= 0
                or proposal.limits is None
                or value.value > proposal.limits.wall_time_seconds
            ):
                return _answer(Code.BINDING_TYPE_MISMATCH, parameter.item_id)
        else:
            return _answer(Code.TARGET_ROLE_MISMATCH, parameter.item_id)
    if entry:
        missing = selected_refs - set(by_parameter)
        if missing:
            return _answer(Code.BINDING_MISSING, *missing)
        if sum(parameters[ref].role is ParameterRole.TARGET_HOST for ref in selected_refs) != 1:
            return _answer(Code.TARGET_ROLE_MISMATCH)
    if layout is not None:
        used = tuple(
            token.binding_id
            for token in layout.arguments
            if isinstance(token, OptionValueToken | PositionalToken | BindingToken)
        )
        for index, token in enumerate(layout.arguments):
            if isinstance(token, OptionToken):
                if index + 1 >= len(layout.arguments) or not isinstance(
                    layout.arguments[index + 1], BindingToken
                ):
                    return _answer(Code.INVOCATION_LAYOUT_INVALID)
                continue
            if not isinstance(token, OptionValueToken | PositionalToken | BindingToken):
                return _answer(Code.INVOCATION_LAYOUT_INVALID)
            if isinstance(token, BindingToken) and (
                index == 0 or not isinstance(layout.arguments[index - 1], OptionToken)
            ):
                return _answer(Code.INVOCATION_LAYOUT_INVALID)
            if token.binding_id not in by_binding:
                return _answer(Code.INVOCATION_LAYOUT_INVALID)
        if len(set(used)) != len(used) or set(used) != set(by_binding):
            return _answer(Code.INVOCATION_LAYOUT_INVALID)
    # 11 runtime, 12 dependencies, 13 filesystem, 14 network, 15 finite limits.
    runtime = proposal.runtime
    if runtime is None or (runtime.kind, runtime.platform, runtime.platform_variant) != (
        "python",
        "LINUX",
        "kali",
    ):
        return _answer(Code.UNSUPPORTED_RUNTIME)
    if runtime.version_constraint != ">=3.12,<4":
        return _answer(Code.UNSUPPORTED_RUNTIME)
    dependencies = semantic.dependency_observations
    if any(
        item.kind is not DependencyKind.IMPORTED_MODULE
        or item.import_kind is not ImportKind.STDLIB_LOOKING
        or item.origin is not SourceOrigin.CODE
        or item.epistemic_state is not EpistemicState.OBSERVED
        for item in dependencies
    ):
        return _answer(Code.DEPENDENCY_UNSUPPORTED, *(item.item_id for item in dependencies))
    if len(proposal.dependencies) != len(dependencies) or any(
        item.kind is not PlanDependencyKind.STDLIB_MODULE
        or not any(
            item.dependency_id == source.item_id
            and item.identifier == source.name
            and item.evidence_ids == (source.item_id,)
            and item.version_constraint == source.version_constraint
            for source in dependencies
        )
        for item in proposal.dependencies
    ):
        return _answer(Code.DEPENDENCY_UNSUPPORTED)
    fs = proposal.filesystem
    if (
        fs is None
        or fs.scope is not EffectScope.BOUNDED
        or fs.writable_root_requirement_id is not None
        or fs.rules
    ):
        return _answer(Code.FILESYSTEM_UNSUPPORTED)
    if any(
        item.kind in {BehaviorKind.FILE_WRITE, BehaviorKind.FILE_DELETE}
        for item in semantic.behavior_indicators
    ):
        return _answer(Code.FILESYSTEM_UNSUPPORTED)
    network = proposal.network
    if (
        target.role is not TargetRole.SERVICE_ENDPOINT
        or target.port is None
        or target.transport != "tcp"
    ):
        return _answer(Code.NETWORK_UNSUPPORTED)
    if network is None or len(network.rules) != 1:
        return _answer(Code.NETWORK_UNSUPPORTED)
    rule = network.rules[0]
    host_bindings = [
        item for item in proposal.bindings if isinstance(item.value, MissionTargetValue)
    ]
    if (
        len(host_bindings) != 1
        or rule.destination is not NetworkDestinationClass.SELECTED_TARGET
        or (
            rule.transport != target.transport
            or rule.ports != (target.port,)
            or rule.endpoint_binding_id != host_bindings[0].binding_id
            or rule.requirement_id is not None
        )
    ):
        return _answer(Code.NETWORK_UNSUPPORTED)
    if any(item.kind is not BehaviorKind.NETWORK_CONNECT for item in semantic.behavior_indicators):
        return _answer(Code.NETWORK_UNSUPPORTED)
    if proposal.limits is None:
        return _answer(Code.LIMITS_REQUIRED)
    # No child processes or source writes belong to this initial intent.
    if proposal.limits.process_count != 1 or proposal.limits.disk_write_bytes != 0:
        return _answer(Code.FILESYSTEM_UNSUPPORTED)
    # 16 noninteractive, 17 user-space, 18 attacker-side, 19 unresolved semantics.
    if not runtime.noninteractive:
        return _answer(Code.NONINTERACTIVE_REQUIRED)
    if not runtime.user_space:
        return _answer(Code.USER_SPACE_REQUIRED)
    if runtime.location is not ExecutionLocation.ATTACKER_NODE:
        return _answer(Code.ATTACKER_SIDE_REQUIRED)
    if (
        semantic.risk_indicators
        or semantic.requirements
        or semantic.conflicts
        or semantic.limit_reasons
        or (
            proposal.sensitive_requirements
            or proposal.resources
            or proposal.sessions
            or proposal.environment
        )
    ):
        return _answer(Code.UNKNOWN_CRITICAL_EFFECT)
    non_blocking = {
        ref
        for reason in classification.reasons
        if reason.code.value == "NON_BLOCKING_UNKNOWN"
        for ref in reason.item_refs
    }
    # Only bounded entrypoint ambiguity is a D4 wait, never a safety override.
    entrypoint_assistance = {
        ref
        for reason in classification.reasons
        if reason.code.value == "REQUIRES_ENTRYPOINT_SELECTION"
        for ref in reason.item_refs
    }
    if any(
        item.item_id not in non_blocking
        and not (
            len(entries) > 1
            and item.item_id in entrypoint_assistance
            and item.reason in {"MULTIPLE_ENTRYPOINT_CANDIDATES", "EXTRACTOR_LIMITATIONS"}
        )
        for item in semantic.unknowns
    ):
        return _answer(Code.UNKNOWN_CRITICAL_EFFECT)
    if len(entries) != 1:
        return _answer(
            Code.ENTRYPOINT_SELECTION_REQUIRED, *(item.item_id for item in entries), waiting=True
        )
    if layout is None:
        return _answer(Code.INVOCATION_LAYOUT_REQUIRED, waiting=True)
    if classification.classification is not SupportClassification.AUTOMATIC:
        return _answer(Code.ASSISTANCE_REQUIRED, waiting=True)
    if (
        any(item.kind not in {"STDOUT", "STDERR"} for item in proposal.expected_evidence)
        or proposal.expected_results
    ):
        return _answer(Code.UNKNOWN_CRITICAL_EFFECT)
    if proposal.unresolved_requirement_ids:
        return _answer(Code.UNRESOLVED_BINDING, *proposal.unresolved_requirement_ids)
    return ConstructionAssessment(
        status=Status.VALID,
        reasons=(
            PlanValidationReason(
                code=Code.CONSISTENT_INTENT,
                evidence_refs=(entry.item_id,) if entry else (),
            ),
        ),
    )


def validate_plan(plan: ExecutionPlanV2, evidence: PlanningEvidence) -> ConstructionAssessment:
    """Validate a complete candidate without persistence or an authority side effect."""
    try:
        check_model_fields(plan)
        check_model_fields(evidence)
        evidence = PlanningEvidence.model_validate_json(evidence.model_dump_json())
        plan = ExecutionPlanV2.model_validate_json(plan.model_dump_json())
    except (ValueError, TypeError, AttributeError):
        return _answer(Code.SCHEMA_INVALID)
    if plan.mission_ref != evidence.attempt.request.mission_ref:
        return _answer(Code.MISSION_MISMATCH)
    proposal = PlanProposal.model_validate(
        {
            name: getattr(plan, name)
            for name in PlanProposal.model_fields
            if name != "unresolved_requirement_ids"
        }
    )
    if plan.uncertainties:
        return _answer(Code.UNKNOWN_CRITICAL_EFFECT, *plan.uncertainties)
    return assess_proposal(proposal, evidence)
