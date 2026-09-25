"""Core validates advisory interpretation and proposed actions without dispatch."""

from __future__ import annotations

from collections.abc import Iterator

from boberagent_contracts import AssetRef, CredentialRef, ObservationRef, SecretRef, ServiceRef
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from boberagent_core.capabilities import CapabilityRegistry, ProviderAvailability
from boberagent_core.knowledge import KnowledgeRouter, KnowledgeStatus, chunk_source
from boberagent_core.models import CredentialStatus, SecretStatus
from boberagent_core.persistence import CoreDatabase

from .context import ContextBuilder
from .models import (
    ActionProposal,
    InterpretationResult,
    KnowledgeCitation,
    ProcedureCitation,
    ReasoningAssessment,
    ReasoningContext,
    ReasoningSelection,
    StructuredReasoning,
)
from .provider import ReasonerProvider


class ProposalRejected(ValueError):
    """A model-proposed identity, input, or source failed Core validation."""


class ProposalValidator:
    """Validate only. Never creates a Run, routes, or executes a Capability."""

    def __init__(
        self, database: CoreDatabase, knowledge: KnowledgeRouter, registry: CapabilityRegistry
    ) -> None:
        self._database = database
        self._knowledge = knowledge
        self._registry = registry

    def validate_interpretation(
        self, interpretation: InterpretationResult, context: ReasoningContext
    ) -> None:
        self._check_sources(
            interpretation.supporting_observation_refs,
            interpretation.supporting_knowledge,
            interpretation.supporting_procedure,
            context,
        )

    def validate(self, proposal: ActionProposal, context: ReasoningContext) -> None:
        self._check_sources(
            proposal.supporting_observation_refs,
            proposal.supporting_knowledge,
            proposal.supporting_procedure,
            context,
        )
        advertised = {item.capability_id: item for item in context.capabilities}
        if proposal.capability_id not in advertised:
            raise ProposalRejected("proposed Capability was not in the selected available context")
        providers = tuple(
            provider
            for provider in self._registry.list_providers(proposal.capability_id)
            if provider.availability is ProviderAvailability.AVAILABLE
        )
        if not providers:
            raise ProposalRejected("proposed Capability has no available provider")
        operations = [
            operation
            for provider in providers
            for operation in provider.definition.operations
            if operation.name == proposal.operation
        ]
        if not operations:
            raise ProposalRejected("proposed operation is not available")
        if not any(
            operation.name == proposal.operation
            for operation in advertised[proposal.capability_id].operations
        ):
            raise ProposalRejected("proposed operation was not selected in context")
        if proposal.asset_ref is not None and proposal.asset_ref != context.asset.asset_ref:
            raise ProposalRejected("proposed Asset differs from the selected Mission Asset")
        if proposal.service_ref is not None and proposal.service_ref not in {
            service.service_ref for service in context.services
        }:
            raise ProposalRejected("proposed Service is not in the selected World State")

        with self._database.unit_of_work() as work:
            asset = work.assets.get(context.asset.asset_ref)
            if asset is None or asset.mission_ref != context.mission_ref:
                raise ProposalRejected("selected Asset is outside the Mission")
            for secret_ref in proposal.secret_refs:
                secret = work.secrets.get(secret_ref)
                if (
                    secret is None
                    or secret.mission_ref != context.mission_ref
                    or secret.status is not SecretStatus.AVAILABLE
                ):
                    raise ProposalRejected("proposed SecretRef is unavailable for the Mission")
            for credential_ref in proposal.credential_refs:
                credential = work.credentials.get(credential_ref)
                if (
                    credential is None
                    or credential.mission_ref != context.mission_ref
                    or credential.status
                    not in {CredentialStatus.CANDIDATE, CredentialStatus.VALIDATED}
                ):
                    raise ProposalRejected("proposed CredentialRef is unavailable for the Mission")
        _check_input_refs(proposal, context)

        for operation in operations:
            schema = operation.input_schema.inline
            if schema is None:
                raise ProposalRejected(
                    "operation input schema is not available for local validation"
                )
            _check_local_schema_references(schema)
            try:
                Draft202012Validator.check_schema(schema)
                errors = list(
                    Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                        proposal.inputs
                    )
                )
            except SchemaError:
                raise ProposalRejected("provider operation has an invalid input schema") from None
            if errors:
                raise ProposalRejected("proposed inputs do not match the operation schema")

    def _check_sources(
        self,
        observation_refs: tuple[ObservationRef, ...],
        knowledge: tuple[KnowledgeCitation, ...],
        procedure: ProcedureCitation | None,
        context: ReasoningContext,
    ) -> None:
        if not set(observation_refs).issubset(set(context.observation_refs)):
            raise ProposalRejected("reasoning cited an Observation outside its context")
        with self._database.unit_of_work() as work:
            for ref in observation_refs:
                observation = work.observations.get(ref)
                if observation is None:
                    raise ProposalRejected("reasoning cited an unknown Observation")
                run = work.runs.get(observation.observation.run_ref)
                if run is None or run.mission_ref != context.mission_ref:
                    raise ProposalRejected("reasoning cited an Observation outside the Mission")
        supplied = {citation for fragment in context.knowledge for citation in fragment.citations}
        for citation in knowledge:
            if citation not in supplied:
                raise ProposalRejected("reasoning cited Knowledge outside its context")
            document = self._knowledge.repository.get(
                citation.knowledge_id, version=citation.version
            )
            if document is None or document.status is not KnowledgeStatus.CANONICAL:
                raise ProposalRejected("reasoning cited noncanonical Knowledge")
            if citation.chunk_id is not None and citation.chunk_id not in {
                chunk.chunk_id for chunk in chunk_source(document)
            }:
                raise ProposalRejected("reasoning cited an unknown Knowledge chunk")
        if procedure is not None:
            if context.procedure is None or context.procedure.citation != procedure:
                raise ProposalRejected("reasoning cited a Procedure outside its context")
            definition = self._knowledge.procedures.get(
                procedure.procedure_id, version=procedure.version
            )
            if definition is None or definition.status is not KnowledgeStatus.CANONICAL:
                raise ProposalRejected("reasoning cited a noncanonical Procedure")


def _walk_inputs(value: object) -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key, child
            yield from _walk_inputs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_inputs(child)


def _check_input_refs(proposal: ActionProposal, context: ReasoningContext) -> None:
    """Operation refs must agree with selected context or explicit proposal refs."""

    permitted = {"asset_ref", "service_ref", "observation_ref", "secret_ref", "credential_ref"}
    for key, value in _walk_inputs(proposal.inputs):
        if key.endswith("_ref") and key not in permitted:
            raise ProposalRejected("proposed input uses an unsupported reference field")
        if key not in permitted:
            continue
        if not isinstance(value, str):
            raise ProposalRejected("proposed input reference must be a logical string")
        try:
            if key == "asset_ref" and AssetRef(value) != context.asset.asset_ref:
                raise ProposalRejected("proposed input AssetRef does not match the selected Asset")
            if key == "service_ref" and ServiceRef(value) != proposal.service_ref:
                raise ProposalRejected(
                    "proposed input ServiceRef does not match the selected Service"
                )
            if (
                key == "observation_ref"
                and ObservationRef(value) not in proposal.supporting_observation_refs
            ):
                raise ProposalRejected("proposed input ObservationRef was not cited")
            if key == "secret_ref" and SecretRef(value) not in proposal.secret_refs:
                raise ProposalRejected("proposed input SecretRef is not explicitly authorized")
            if key == "credential_ref" and CredentialRef(value) not in proposal.credential_refs:
                raise ProposalRejected("proposed input CredentialRef is not explicitly authorized")
        except (TypeError, ValueError) as error:
            if isinstance(error, ProposalRejected):
                raise
            raise ProposalRejected("proposed input reference is invalid") from None


def _check_local_schema_references(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$dynamicRef", "$recursiveRef"}:
                raise ProposalRejected("operation schema uses unsupported dynamic references")
            if key == "$ref" and (not isinstance(child, str) or not child.startswith("#/$defs/")):
                raise ProposalRejected("operation schema requires unsupported external references")
            _check_local_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            _check_local_schema_references(child)


class ReasoningService:
    """One bounded interpret/propose/validate pass; intentionally no dispatch path."""

    def __init__(
        self,
        context_builder: ContextBuilder,
        provider: ReasonerProvider,
        validator: ProposalValidator,
    ) -> None:
        self._context_builder = context_builder
        self._provider = provider
        self._validator = validator

    async def interpret_and_propose(self, selection: ReasoningSelection) -> ReasoningAssessment:
        context = self._context_builder.build(selection)
        generation = await self._provider.generate(context, StructuredReasoning)
        self._validator.validate_interpretation(generation.value.interpretation, context)
        proposal = generation.value.proposal
        if proposal is not None:
            self._validator.validate(proposal, context)
        return ReasoningAssessment(
            context=context,
            generation=generation,
            proposal_validated=proposal is not None,
        )
