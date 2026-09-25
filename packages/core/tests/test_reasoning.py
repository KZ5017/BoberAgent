"""Bounded service-evidence reasoning, source ordering, and Core proposal rejection."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityDefinition,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
)
from boberagent_core import (
    Asset,
    CapabilityRegistry,
    CoreDatabase,
    CorePersistence,
    CoreSecretService,
    Goal,
    GoalRef,
    GoalStatus,
    Mission,
)
from boberagent_core.knowledge import (
    KnowledgeId,
    KnowledgeRouter,
    ProcedureId,
    SemanticHit,
    chunk_source,
)
from boberagent_core.models import CoreModel
from boberagent_core.reasoning import (
    ActionProposal,
    ContextBuilder,
    ContextSelectionError,
    EvidenceStrength,
    Hypothesis,
    InterpretationResult,
    ProposalRejected,
    ProposalValidator,
    ReasonerGeneration,
    ReasoningContext,
    ReasoningSelection,
    ReasoningService,
    StructuredReasoning,
)
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    NodeAdvertisement,
    TransportMessageId,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 25, tzinfo=UTC)
MISSION = MissionRef("mission-reasoning")
ASSET = AssetRef("asset-reasoning")
GOAL = GoalRef("goal-reasoning")
RUN = CapabilityRunRef("run-reasoning-evidence")
OBSERVATION = ObservationRef("observation-reasoning-service")
PRIVATE_OBSERVATION = ObservationRef("observation-reasoning-private")
KNOWLEDGE = KnowledgeId("knowledge.network.service_evidence")
PROCEDURE = ProcedureId("procedure.network.service_discovery")
PRIVATE_VALUE = "harmless-private-test-value"


def _definition() -> CapabilityDefinition:
    manifest = json.loads(
        (ROOT / "capabilities/network-service-discovery/capability.json").read_text(
            encoding="utf-8"
        )
    )
    return CapabilityDefinition.model_validate(manifest["definition"])


def _setup(
    database: CoreDatabase,
) -> tuple[ContextBuilder, ProposalValidator, ReasoningSelection, CapabilityRegistry]:
    persistence = CorePersistence(database)
    persistence.create_mission(Mission(mission_ref=MISSION, status="ACTIVE", created_at=NOW))
    persistence.create_asset(
        Asset(
            asset_ref=ASSET,
            mission_ref=MISSION,
            kind="host",
            primary_address="192.0.2.23",
            created_at=NOW,
        )
    )
    persistence.create_goal(
        Goal(
            goal_ref=GOAL,
            mission_ref=MISSION,
            goal_type="service_discovery",
            status=GoalStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            parameters={"asset_ref": str(ASSET), "password": PRIVATE_VALUE},
        )
    )
    persistence.record_run(
        CapabilityRun(
            run_id=RUN,
            capability_id="network.service_discovery",
            operation="discover",
            mission_ref=MISSION,
            status=CapabilityRunStatus.COMPLETED,
            created_at=NOW,
            finished_at=NOW,
        )
    )
    persistence.append_observation(
        Observation(
            observation_id=OBSERVATION,
            type="network.service",
            subject_ref=ASSET,
            value={
                "transport": "tcp",
                "port": 80,
                "state": "open",
                "service": "http",
                "product": "unknown",
                "version": None,
            },
            run_ref=RUN,
            observed_at=NOW,
        )
    )
    persistence.materialize_observation(OBSERVATION)
    persistence.append_observation(
        Observation(
            observation_id=PRIVATE_OBSERVATION,
            type="test.private_evidence",
            subject_ref=ASSET,
            value={"password": PRIVATE_VALUE},
            run_ref=RUN,
            observed_at=NOW,
        )
    )
    CoreSecretService(database).store(
        mission_ref=MISSION,
        value=PRIVATE_VALUE.encode(),
        secret_type="password",
    )

    knowledge = KnowledgeRouter.from_directory(ROOT / "knowledge")
    registry = CapabilityRegistry(database, clock=lambda: NOW)
    definition = _definition()
    registry.register_or_refresh_node(
        NodeAdvertisement(
            request_message_id=TransportMessageId("transport-reasoning-handshake"),
            node_id="node-reasoning",
            timestamp=NOW,
            lifecycle="READY",
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
    document = knowledge.get_canonical(KNOWLEDGE)
    assert document is not None
    hits = tuple(SemanticHit(chunk=chunk, score=0.8) for chunk in reversed(chunk_source(document)))
    selection = ReasoningSelection(
        mission_ref=MISSION,
        goal_ref=GOAL,
        asset_ref=ASSET,
        observation_refs=(OBSERVATION, PRIVATE_OBSERVATION),
        attempt_run_refs=(RUN,),
        procedure_id=PROCEDURE,
        canonical_knowledge_ids=(KNOWLEDGE,),
        semantic_hits=hits,
        capability_ids=(definition.capability_id,),
        diagnostic_codes=("SERVICE_ID_AMBIGUOUS",),
    )
    return (
        ContextBuilder(database, knowledge, registry),
        ProposalValidator(database, knowledge, registry),
        selection,
        registry,
    )


def _proposal(context: ReasoningContext) -> ActionProposal:
    return ActionProposal(
        capability_id="network.service_discovery",
        operation="discover",
        purpose="Resolve the remaining service identity uncertainty.",
        expected_information_gain="Additional service and version evidence.",
        asset_ref=ASSET,
        inputs={"asset_ref": str(ASSET), "profile": "quick"},
        supporting_observation_refs=(OBSERVATION,),
        supporting_knowledge=context.knowledge[0].citations,
        supporting_procedure=context.procedure.citation if context.procedure else None,
    )


class FakeReasonerProvider:
    def __init__(self, value: StructuredReasoning) -> None:
        self.value = value
        self.calls = 0

    async def generate[T: CoreModel](
        self, context: ReasoningContext, output_type: type[T]
    ) -> ReasonerGeneration[T]:
        assert context.goal.goal_ref == GOAL
        self.calls += 1
        return ReasonerGeneration(
            value=output_type.model_validate(self.value.model_dump(mode="python")),
            provider_id="deterministic-fake",
            model_id="test-model",
            finish_reason="stop",
        )


def test_context_authority_provenance_dedup_and_secret_isolation(database: CoreDatabase) -> None:
    builder, _validator, selection, _registry = _setup(database)
    context = builder.build(selection)

    assert context.authority_order[:3] == ("goal", "world_state", "procedure")
    assert context.goal.goal_ref == GOAL
    assert context.services[0].provenance_refs == (OBSERVATION,)
    assert context.observation_refs == (OBSERVATION, PRIVATE_OBSERVATION)
    assert context.procedure is not None and context.procedure.citation.procedure_id == PROCEDURE
    assert context.attempts[0].run_ref == RUN
    operation = context.capabilities[0].operations[0]
    assert operation.name == "discover"
    assert operation.input_schema == _definition().operations[0].input_schema.inline
    assert operation.input_schema["required"] == ["asset_ref"]
    properties = operation.input_schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"asset_ref", "profile", "timeout_seconds"}
    assert context.knowledge
    assert all(item.provenance.source_path.startswith("reference/") for item in context.knowledge)
    assert all(item.source_sha256 == item.provenance.content_sha256 for item in context.knowledge)
    assert len({item.citations[0].chunk_id for item in context.knowledge}) == len(context.knowledge)
    assert PRIVATE_VALUE not in context.model_dump_json()


def test_semantic_source_order_and_lower_priority_budget(database: CoreDatabase) -> None:
    builder, _validator, selection, _registry = _setup(database)
    semantic_only = selection.model_copy(update={"canonical_knowledge_ids": ()})
    context = builder.build(semantic_only)
    assert [item.document_ordinal for item in context.knowledge] == sorted(
        item.document_ordinal for item in context.knowledge
    )
    assert all(item.authority == "SEMANTIC" for item in context.knowledge)

    tight = builder.build(selection.model_copy(update={"max_content_chars": 1500}))
    assert tight.goal == context.goal
    assert tight.services == context.services
    assert tight.procedure is not None
    assert tight.budget.included_chars <= 1500
    assert sum(tight.budget.omitted_counts.values()) > 0


def test_bounded_reasoning_end_to_end_validated_but_never_executed(
    database: CoreDatabase, database_path: Path
) -> None:
    builder, validator, selection, registry = _setup(database)
    context = builder.build(selection)
    interpretation = InterpretationResult(
        summary="Open HTTP service observed; product remains ambiguous.",
        hypotheses=(
            Hypothesis(
                statement="A generic HTTP server is present.",
                evidence_strength=EvidenceStrength.MIXED,
                uncertainty="Product and version are unconfirmed.",
            ),
        ),
        evidence_strength=EvidenceStrength.MIXED,
        supporting_observation_refs=(OBSERVATION,),
        supporting_knowledge=context.knowledge[0].citations,
        supporting_procedure=context.procedure.citation if context.procedure else None,
        missing_information=("Service product and version",),
    )
    proposal_data = _proposal(context).model_dump(mode="json")
    del proposal_data["asset_ref"]
    fake = FakeReasonerProvider(
        StructuredReasoning(
            interpretation=interpretation, proposal=ActionProposal.model_validate(proposal_data)
        )
    )
    service = ReasoningService(builder, fake, validator)
    with sqlite3.connect(database_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM capability_runs").fetchone()

    assessed = asyncio.run(service.interpret_and_propose(selection))

    assert assessed.proposal_validated
    assert assessed.generation.value.proposal is not None
    assert assessed.generation.provider_id == "deterministic-fake"
    assert assessed.context.knowledge[0].citations[0].knowledge_id == KNOWLEDGE
    assert fake.calls == 1
    with sqlite3.connect(database_path) as connection:
        after = connection.execute("SELECT COUNT(*) FROM capability_runs").fetchone()
    assert after == before
    assert registry.routing_decision_for_run(RUN) is None


def test_invalid_proposals_and_hallucinated_sources_are_rejected(database: CoreDatabase) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    valid = _proposal(context)
    cases = (
        {"capability_id": "network.unknown"},
        {"operation": "invented"},
        {"asset_ref": "asset-other"},
        {"inputs": {"asset_ref": str(ASSET), "profile": "invented"}},
        {"inputs": {"asset_ref": str(ASSET), "made_up_parameter": True}},
        {"inputs": {"asset_ref": str(ASSET), "timeout_seconds": 3601}},
        {"supporting_observation_refs": ["observation-unknown"]},
        {"supporting_knowledge": [{"knowledge_id": "knowledge.unknown", "version": 1}]},
        {"secret_refs": ["secret-missing"]},
    )
    for changes in cases:
        proposed = ActionProposal.model_validate({**valid.model_dump(mode="json"), **changes})
        with pytest.raises(ProposalRejected):
            validator.validate(proposed, context)

    for unsafe_inputs in (
        {"password": PRIVATE_VALUE},
        {"credentials": {"db_password": PRIVATE_VALUE}},
    ):
        with pytest.raises(ValidationError):
            ActionProposal.model_validate(
                {**valid.model_dump(mode="json"), "inputs": unsafe_inputs}
            )


def test_context_rejects_out_of_mission_and_missing_selection(database: CoreDatabase) -> None:
    builder, _validator, selection, _registry = _setup(database)
    with pytest.raises(ContextSelectionError):
        builder.build(selection.model_copy(update={"asset_ref": AssetRef("asset-unknown")}))
    with pytest.raises(ContextSelectionError):
        builder.build(
            selection.model_copy(update={"observation_refs": (ObservationRef("obs-missing"),)})
        )


def test_structured_proposal_requires_explicit_inputs(database: CoreDatabase) -> None:
    builder, _validator, selection, _registry = _setup(database)
    payload = _proposal(builder.build(selection)).model_dump(mode="json")
    del payload["inputs"]
    interpretation = {"summary": "Service identity is uncertain", "evidence_strength": "MIXED"}
    with pytest.raises(ValidationError):
        StructuredReasoning.model_validate({"interpretation": interpretation, "proposal": payload})
    generated = StructuredReasoning.model_json_schema()
    assert "inputs" in generated["$defs"]["ActionProposal"]["required"]
    assert StructuredReasoning.model_validate({"interpretation": interpretation}).proposal is None


def test_explicit_empty_inputs_rejected_but_required_asset_input_passes(
    database: CoreDatabase,
) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    payload = _proposal(context).model_dump(mode="json")
    empty = ActionProposal.model_validate({**payload, "inputs": {}})
    assert empty.inputs == {}
    assert empty.asset_ref == ASSET  # Proposal-level ref does not populate operation inputs.
    with pytest.raises(ProposalRejected, match="operation schema"):
        validator.validate(empty, context)
    valid = ActionProposal.model_validate({**payload, "inputs": {"asset_ref": str(ASSET)}})
    validator.validate(valid, context)


def test_capability_schema_projection_is_bounded_selected_and_available(
    database: CoreDatabase,
) -> None:
    builder, _validator, selection, registry = _setup(database)
    authoritative = _definition().operations[0].input_schema.inline
    context = builder.build(selection)
    assert context.capabilities[0].operations[0].input_schema == authoritative
    assert builder.build(selection.model_copy(update={"capability_ids": ()})).capabilities == ()

    tight = builder.build(selection.model_copy(update={"max_content_chars": 1500}))
    assert tight.budget.included_chars <= 1500
    assert all(
        capability.operations[0].input_schema == authoritative for capability in tight.capabilities
    )
    if not tight.capabilities:
        assert tight.budget.omitted_counts["capabilities"] == 1

    registry.mark_node_stale("node-reasoning")
    assert builder.build(selection).capabilities == ()


def test_conflicting_provider_input_contract_is_not_shown_as_applicable(
    database: CoreDatabase,
) -> None:
    builder, _validator, selection, registry = _setup(database)
    variant_data = json.loads(_definition().model_dump_json())
    variant_data["operations"][0]["input_schema"]["inline"]["properties"]["profile"]["enum"] = [
        "standard"
    ]
    variant = CapabilityDefinition.model_validate(variant_data)
    registry.register_or_refresh_node(
        NodeAdvertisement(
            request_message_id=TransportMessageId("transport-reasoning-variant"),
            node_id="node-reasoning-variant",
            timestamp=NOW,
            lifecycle="READY",
            database_ready=True,
            capabilities=(variant,),
            capability_statuses=(
                CapabilityStatusAdvertisement(
                    capability_id=variant.capability_id,
                    status=AdvertisedCapabilityStatus.AVAILABLE,
                ),
            ),
        )
    )
    assert builder.build(selection).capabilities == ()


@pytest.mark.parametrize("include_top_level", [False, True])
def test_matching_operation_asset_ref_accepts_optional_matching_target_metadata(
    database: CoreDatabase, include_top_level: bool
) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    payload = _proposal(context).model_dump(mode="json")
    if not include_top_level:
        del payload["asset_ref"]
    proposal = ActionProposal.model_validate(payload)
    assert proposal.inputs["asset_ref"] == str(context.asset.asset_ref)
    assert proposal.asset_ref == (ASSET if include_top_level else None)
    validator.validate(proposal, context)


def test_wrong_operation_asset_ref_is_rejected_without_top_level_ref(
    database: CoreDatabase,
) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    payload = _proposal(context).model_dump(mode="json")
    del payload["asset_ref"]
    proposal = ActionProposal.model_validate({**payload, "inputs": {"asset_ref": "asset-other"}})
    with pytest.raises(ProposalRejected, match="input AssetRef does not match"):
        validator.validate(proposal, context)


def test_conflicting_top_level_asset_ref_is_rejected_independently(
    database: CoreDatabase,
) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    payload = _proposal(context).model_dump(mode="json")
    payload["asset_ref"] = "asset-other"
    proposal = ActionProposal.model_validate(payload)
    assert proposal.inputs["asset_ref"] == str(context.asset.asset_ref)
    with pytest.raises(ProposalRejected, match="proposed Asset differs"):
        validator.validate(proposal, context)


def test_foreign_mission_asset_ref_and_misbound_selected_asset_are_rejected(
    database: CoreDatabase,
) -> None:
    builder, validator, selection, _registry = _setup(database)
    context = builder.build(selection)
    foreign_mission = MissionRef("mission-reasoning-foreign")
    foreign_asset = AssetRef("asset-reasoning-foreign")
    persistence = CorePersistence(database)
    persistence.create_mission(
        Mission(mission_ref=foreign_mission, status="ACTIVE", created_at=NOW)
    )
    persistence.create_asset(
        Asset(
            asset_ref=foreign_asset,
            mission_ref=foreign_mission,
            kind="host",
            primary_address="198.51.100.19",
            created_at=NOW,
        )
    )
    payload = _proposal(context).model_dump(mode="json")
    del payload["asset_ref"]
    foreign_proposal = ActionProposal.model_validate(
        {**payload, "inputs": {"asset_ref": str(foreign_asset)}}
    )
    with pytest.raises(ProposalRejected, match="input AssetRef does not match"):
        validator.validate(foreign_proposal, context)

    uncited = ActionProposal(
        capability_id="network.service_discovery",
        operation="discover",
        purpose="Check selected Asset ownership",
        expected_information_gain="Service evidence",
        inputs={"asset_ref": str(ASSET)},
    )
    wrong_mission_context = context.model_copy(update={"mission_ref": foreign_mission})
    with pytest.raises(ProposalRejected, match="selected Asset is outside the Mission"):
        validator.validate(uncited, wrong_mission_context)
