"""D6 questions are durable Core planning input, never execution permission."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import JsonValue
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_values import BindingProvenance, ResolutionState
from boberagent_core import CoreDatabase
from boberagent_core.inspections.classification_models import semantic_digest
from boberagent_core.inspections.semantic_models import SemanticInspectionDocument
from boberagent_core.interactions.errors import InteractionConflict
from boberagent_core.planning.assistance import (
    CorePlanningAssistanceService,
    PlanningAssistanceError,
    _construction_request,
)
from boberagent_core.planning.construction import CoreExecutionPlanningService, _evidence
from boberagent_core.planning.construction_models import PlanningEvidence
from boberagent_core.planning.interaction_models import PlanningInteractionResponse
from boberagent_core.planning.models import PlanningAttemptLifecycle as State
from boberagent_core.planning.models import PlanningAttemptRef
from boberagent_core.planning.models import PlanningDisposition as Disposition
from boberagent_core.planning.models import PlanningInteractionPurpose as Purpose
from boberagent_core.planning.validation import assess_proposal
from planning_construction_fixtures import CHECKER, prepared
from test_core_poc_acquisition import NOW


def _reply(question: object, value: JsonValue) -> PlanningInteractionResponse:
    from boberagent_core.planning.interaction_models import PlanningInteractionRequest

    assert isinstance(question, PlanningInteractionRequest)
    return PlanningInteractionResponse(
        interaction_ref=question.interaction_ref,
        planning_attempt_ref=question.planning_attempt_ref,
        proposal_revision=question.proposal_revision,
        purpose=question.purpose,
        operator_id="operator-test",
        value=value,
        responded_at=NOW,
    )


def test_manual_parameter_restart_resume_and_replay(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    unresolved = tuple(
        binding.model_copy(
            update={
                "resolution": ResolutionState.UNRESOLVED,
                "value": None,
                "provenance": BindingProvenance(
                    origin="OPERATOR", evidence_ids=(binding.parameter_id,)
                ),
            }
        )
        if binding.binding_id == "port"
        else binding
        for binding in request.bindings
    )
    waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(update={"bindings": unresolved})
    )
    assert waiting.attempt.lifecycle is State.WAITING_INPUT
    service = CorePlanningAssistanceService(database, clock=lambda: NOW)
    pending = service.pending(waiting.attempt.planning_attempt_ref)
    assert len(pending) == 1
    question = pending[0].request
    assert question.purpose is Purpose.PLANNING_PARAMETER_VALUE
    assert question.input_schema["type"] == "integer"
    matching = _reply(question, 80)
    with pytest.raises(InteractionConflict):
        service.respond(
            matching.model_copy(
                update={"planning_attempt_ref": PlanningAttemptRef("planning-attempt-other")}
            )
        )
    with pytest.raises(InteractionConflict):
        service.respond(
            matching.model_copy(update={"proposal_revision": question.proposal_revision + 1})
        )
    with pytest.raises(InteractionConflict):
        service.respond(matching.model_copy(update={"purpose": Purpose.PLANNING_INVOCATION_LAYOUT}))
    with pytest.raises(PlanningAssistanceError):
        service.respond(_reply(question, "80"))
    with pytest.raises(PlanningAssistanceError):
        service.respond(_reply(question, 81))
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        service = CorePlanningAssistanceService(reopened, clock=lambda: NOW)
        assert service.pending(waiting.attempt.planning_attempt_ref)[0].request == question
        response = _reply(question, 80)
        answered = service.respond(response)
        assert service.respond(response) == answered
        with pytest.raises(InteractionConflict):
            service.respond(_reply(question, 79))
        resumed = service.resume(waiting.attempt.planning_attempt_ref)
        assert resumed.attempt.lifecycle is State.COMPLETED
        assert resumed.attempt.disposition is Disposition.VALID
        assert resumed.validation is not None
        assert resumed.attempt.revisions[1].answers[0].interaction_ref == question.interaction_ref
        assert (
            resumed.attempt.revisions[1].answers[0].proposal_revision == question.proposal_revision
        )
    finally:
        reopened.dispose()


def test_reviewed_invocation_layout(database: CoreDatabase, tmp_path: Path) -> None:
    _, request = prepared(database, tmp_path)
    assert request.invocation is not None
    waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(update={"invocation": None})
    )
    service = CorePlanningAssistanceService(database, clock=lambda: NOW)
    question = service.pending(waiting.attempt.planning_attempt_ref)[0].request
    assert question.purpose is Purpose.PLANNING_INVOCATION_LAYOUT
    bad = request.invocation.model_dump(mode="json")
    with pytest.raises(PlanningAssistanceError):
        service.respond(_reply(question, bad))
    reviewed = request.invocation.model_copy(update={"review_id": str(question.interaction_ref)})
    service.respond(_reply(question, reviewed.model_dump(mode="json")))
    result = service.resume(waiting.attempt.planning_attempt_ref)
    assert result.attempt.disposition is Disposition.VALID
    assert result.attempt.finalized_plan is not None
    assert result.attempt.finalized_plan.invocation == reviewed


def test_multi_entrypoint_selection_uses_c2_candidates(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain, request = prepared(database, tmp_path, {"checker.py": CHECKER, "other.py": CHECKER})
    waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    assert waiting.attempt.lifecycle is State.WAITING_INPUT
    service = CorePlanningAssistanceService(database, clock=lambda: NOW)
    pending = service.pending(waiting.attempt.planning_attempt_ref)
    assert len(pending) == 1
    question = pending[0].request
    assert question.purpose is Purpose.PLANNING_ENTRYPOINT_SELECTION
    assert len(question.options) == 2
    assert isinstance(chain.c2.document, SemanticInspectionDocument)
    selected = next(
        item.item_id
        for item in chain.c2.document.entrypoint_candidates
        if item.source_path == "checker.py"
    )
    service.respond(_reply(question, selected))
    result = service.resume(waiting.attempt.planning_attempt_ref)
    assert result.attempt.lifecycle is State.COMPLETED
    assert result.attempt.disposition is Disposition.VALID
    assert result.attempt.finalized_plan is not None
    assert result.attempt.finalized_plan.entrypoint.evidence_ids == (selected,)


def test_concurrent_entrypoint_answers_accept_only_one(
    database: CoreDatabase, tmp_path: Path
) -> None:
    _, request = prepared(database, tmp_path, {"checker.py": CHECKER, "other.py": CHECKER})
    waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    service = CorePlanningAssistanceService(database, clock=lambda: NOW)
    question = service.pending(waiting.attempt.planning_attempt_ref)[0].request
    choices = tuple(option.option_id for option in question.options)
    assert len(choices) == 2
    barrier = Barrier(2)

    def answer(choice: str) -> str:
        barrier.wait()
        try:
            service.respond(_reply(question, choice))
            return "ACCEPTED"
        except InteractionConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(answer, choices[0])
        right = pool.submit(answer, choices[1])
        results = (left.result(), right.result())
    assert sorted(results) == ["ACCEPTED", "CONFLICT"]
    persisted = service.get(question.interaction_ref)
    assert persisted is not None and persisted.response is not None
    assert persisted.response.value in choices
    with database.unit_of_work() as work:
        attempt = work.planning_attempts.get(waiting.attempt.planning_attempt_ref)
        assert attempt is not None
        assert len(attempt.revisions) == 2
        assert len(attempt.revisions[-1].answers) == 1


def test_entrypoint_choice_does_not_clear_unrelated_extractor_gap(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain, request = prepared(database, tmp_path, {"checker.py": CHECKER, "other.py": CHECKER})
    waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    service = CorePlanningAssistanceService(database, clock=lambda: NOW)
    question = service.pending(waiting.attempt.planning_attempt_ref)[0].request
    assert isinstance(chain.c2.document, SemanticInspectionDocument)
    selected = next(
        item.item_id
        for item in chain.c2.document.entrypoint_candidates
        if item.source_path == "checker.py"
    )
    service.respond(_reply(question, selected))
    with database.unit_of_work() as work:
        attempt = work.planning_attempts.get(waiting.attempt.planning_attempt_ref)
        assert attempt is not None
        proposal = attempt.revisions[-1].proposal
        evidence = _evidence(
            work, attempt, _construction_request(proposal, attempt, len(attempt.revisions))
        )
    original = next(item for item in evidence.semantic.unknowns if item.source_path == "checker.py")
    unrelated = original.model_copy(
        update={"item_id": "item-" + "e" * 64, "reason": "EXTRACTOR_LIMITATIONS"}
    )
    semantic = SemanticInspectionDocument.model_validate(
        evidence.semantic.model_dump() | {"unknowns": (*evidence.semantic.unknowns, unrelated)}
    )
    inspection = evidence.attempt.request.inspection
    classification = inspection.classification.model_copy(
        update={"semantic_document_sha256": semantic_digest(semantic)}
    )
    changed_attempt = evidence.attempt.model_copy(
        update={
            "request": evidence.attempt.request.model_copy(
                update={
                    "inspection": inspection.model_copy(
                        update={
                            "classification": classification,
                            "classification_sha256": canonical_digest(classification),
                        }
                    )
                }
            )
        }
    )
    adversarial = PlanningEvidence.model_validate(
        evidence.model_dump() | {"attempt": changed_attempt, "semantic": semantic}
    )
    assessed = assess_proposal(proposal, adversarial)
    assert assessed.status.value == "INVALID"
    assert assessed.reasons[0].code.value == "ENTRYPOINT_INVALID"
