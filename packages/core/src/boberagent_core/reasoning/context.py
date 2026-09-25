"""Deterministic, Mission-scoped projection of selected Core and Knowledge state."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from boberagent_core.capabilities import CapabilityRegistry, ProviderAvailability
from boberagent_core.knowledge import (
    KnowledgeId,
    KnowledgeRouter,
    KnowledgeStatus,
    SemanticChunk,
    SemanticHit,
    chunk_source,
)
from boberagent_core.models import CoreModel
from boberagent_core.persistence import CoreDatabase

from .models import (
    AssetContext,
    AttemptContext,
    CapabilityContext,
    ContextBudget,
    GoalContext,
    KnowledgeCitation,
    KnowledgeFragment,
    OperationContext,
    ProcedureCitation,
    ProcedureContext,
    ReasoningContext,
    ReasoningSelection,
    ServiceContext,
)


class ContextSelectionError(ValueError):
    """A selected reference is absent, out of Mission, or not canonical."""


class ContextBuilder:
    """Build from explicit IDs; never load raw Observation values, Artifacts, or Secrets."""

    def __init__(
        self, database: CoreDatabase, knowledge: KnowledgeRouter, registry: CapabilityRegistry
    ) -> None:
        self._database = database
        self._knowledge = knowledge
        self._registry = registry

    def build(self, selection: ReasoningSelection) -> ReasoningContext:
        if len(selection.observation_refs) > 32 or len(selection.attempt_run_refs) > 16:
            raise ContextSelectionError("too many selected evidence or attempt references")
        if len(selection.semantic_hits) > 32 or len(selection.capability_ids) > 24:
            raise ContextSelectionError("too many selected Knowledge hits or Capabilities")
        if any(not _safe_code(code) for code in selection.diagnostic_codes):
            raise ContextSelectionError("diagnostics must be bounded symbolic codes")

        with self._database.unit_of_work() as work:
            mission = work.missions.get(selection.mission_ref)
            goal = work.goals.get(selection.goal_ref)
            asset = work.assets.get(selection.asset_ref)
            if mission is None or goal is None or goal.mission_ref != selection.mission_ref:
                raise ContextSelectionError("selected Mission or Goal is unavailable")
            if asset is None or asset.mission_ref != selection.mission_ref:
                raise ContextSelectionError("selected Asset is outside the Mission")
            services = work.services.list_for_asset(selection.asset_ref)
            for observation_ref in selection.observation_refs:
                stored = work.observations.get(observation_ref)
                if stored is None:
                    raise ContextSelectionError("selected Observation does not exist")
                run = work.runs.get(stored.observation.run_ref)
                if run is None or run.mission_ref != selection.mission_ref:
                    raise ContextSelectionError("selected Observation is outside the Mission")
                if stored.observation.subject_ref not in {
                    None,
                    selection.asset_ref,
                    *(service.service_ref for service in services),
                }:
                    raise ContextSelectionError("selected Observation is unrelated to the Asset")
            attempts: list[AttemptContext] = []
            for run_ref in selection.attempt_run_refs:
                run = work.runs.get(run_ref)
                if run is None or run.mission_ref != selection.mission_ref:
                    raise ContextSelectionError("selected Run is outside the Mission")
                attempts.append(
                    AttemptContext(
                        run_ref=run_ref,
                        capability_id=run.capability_id,
                        operation=run.operation,
                        status=run.status.value,
                    )
                )

        selected_procedure: ProcedureContext | None = None
        if selection.procedure_id is not None:
            definition = self._knowledge.lookup_procedure(selection.procedure_id)
            if definition is None or definition.status is not KnowledgeStatus.CANONICAL:
                raise ContextSelectionError("selected Procedure is not canonical")
            selected_procedure = ProcedureContext(
                citation=ProcedureCitation(
                    procedure_id=definition.procedure_id, version=definition.version
                ),
                title=definition.title,
                goal_type=definition.goal_type,
                preconditions=definition.preconditions,
                candidate_actions=tuple(
                    f"{step.capability_id}:{step.operation}" for step in definition.steps
                ),
                provenance=definition.provenance,
            )

        canonical: list[KnowledgeFragment] = []
        for knowledge_id in dict.fromkeys(selection.canonical_knowledge_ids):
            document = self._knowledge.get_canonical(knowledge_id)
            if document is None:
                raise ContextSelectionError("selected Knowledge is not canonical")
            canonical.extend(
                _fragment(chunk, authority="CANONICAL", semantic_score=None)
                for chunk in chunk_source(document)
            )

        semantic: list[KnowledgeFragment] = []
        for hit in _semantic_source_order(selection.semantic_hits):
            chunk = hit.chunk
            if chunk.source_type != "reference" or not isinstance(chunk.source_ref, KnowledgeId):
                # Active Procedures already have their own higher-authority projection.
                continue
            document = self._knowledge.get_canonical(chunk.source_ref)
            if (
                document is None
                or document.version != chunk.version
                or document.provenance.content_sha256 != chunk.source_sha256
                or not any(
                    current.chunk_id == chunk.chunk_id and current.source_text == chunk.source_text
                    for current in chunk_source(document)
                )
            ):
                raise ContextSelectionError("semantic hit is not from current canonical Knowledge")
            semantic.append(_fragment(chunk, authority="SEMANTIC", semantic_score=hit.score))

        capabilities: list[CapabilityContext] = []
        for capability_id in dict.fromkeys(selection.capability_ids):
            providers = tuple(
                provider
                for provider in self._registry.list_providers(capability_id)
                if provider.availability is ProviderAvailability.AVAILABLE
            )
            if not providers:
                continue
            capability_definition = providers[0].definition
            operations: list[OperationContext] = []
            for operation in capability_definition.operations:
                schema = operation.input_schema.inline
                if schema is None:
                    continue
                # A shared operation is exposed only when all available providers agree on
                # its complete inline contract. The validator checks those same providers.
                if any(
                    not any(
                        candidate.name == operation.name and candidate.input_schema.inline == schema
                        for candidate in provider.definition.operations
                    )
                    for provider in providers[1:]
                ):
                    continue
                operations.append(OperationContext(name=operation.name, input_schema=schema))
            if not operations:
                continue
            capabilities.append(
                CapabilityContext(
                    capability_id=capability_definition.capability_id,
                    title=capability_definition.title,
                    operations=tuple(operations),
                    provider_ids=tuple(sorted(str(provider.provider_id) for provider in providers)),
                )
            )

        budget = _Budget(selection.max_content_chars)
        goal_context = GoalContext(
            goal_ref=goal.goal_ref, goal_type=goal.goal_type, status=goal.status
        )
        asset_context = AssetContext(
            asset_ref=asset.asset_ref, kind=asset.kind, primary_address=asset.primary_address
        )
        budget.require("goal", goal_context)
        budget.require("world_state", asset_context)
        bounded_services: tuple[ServiceContext, ...] = budget.choose(
            "world_state",
            (
                ServiceContext(
                    service_ref=service.service_ref,
                    asset_ref=service.asset_ref,
                    transport=service.transport,
                    port=service.port,
                    state=service.state,
                    service=service.service,
                    product=service.product,
                    version=service.version,
                    provenance_refs=service.provenance_refs,
                )
                for service in services
            ),
        )
        procedure = budget.optional("procedure", selected_procedure)
        bounded_attempts: tuple[AttemptContext, ...] = budget.choose("attempts", attempts)
        bounded_canonical: tuple[KnowledgeFragment, ...] = budget.choose(
            "canonical_knowledge", canonical
        )
        bounded_semantic: tuple[KnowledgeFragment, ...] = budget.choose(
            "semantic_knowledge", _deduplicate(semantic, bounded_canonical)
        )
        bounded_capabilities: tuple[CapabilityContext, ...] = budget.choose(
            "capabilities", capabilities
        )
        return ReasoningContext(
            mission_ref=selection.mission_ref,
            goal=goal_context,
            asset=asset_context,
            services=bounded_services,
            observation_refs=tuple(dict.fromkeys(selection.observation_refs)),
            procedure=procedure,
            attempts=bounded_attempts,
            knowledge=(*bounded_canonical, *bounded_semantic),
            capabilities=bounded_capabilities,
            diagnostic_codes=selection.diagnostic_codes,
            budget=budget.snapshot(),
        )


def _safe_code(code: str) -> bool:
    return 1 <= len(code) <= 64 and all(
        char.isupper() or char.isdigit() or char in "._-" for char in code
    )


def _fragment(
    chunk: SemanticChunk, *, authority: str, semantic_score: float | None
) -> KnowledgeFragment:
    if chunk.source_type != "reference" or not isinstance(chunk.source_ref, KnowledgeId):
        raise ContextSelectionError("a Procedure cannot be projected as reference Knowledge")
    return KnowledgeFragment(
        citations=(
            KnowledgeCitation(
                knowledge_id=chunk.source_ref,
                version=chunk.version,
                chunk_id=chunk.chunk_id,
            ),
        ),
        title=chunk.title,
        heading_path=chunk.heading_path,
        document_ordinal=chunk.document_ordinal,
        source_text=chunk.source_text,
        status=chunk.status,
        provenance=chunk.provenance,
        source_sha256=chunk.source_sha256,
        semantic_score=semantic_score,
        authority=authority,
    )


def _semantic_source_order(hits: tuple[SemanticHit, ...]) -> tuple[SemanticHit, ...]:
    groups: dict[tuple[str, int], list[SemanticHit]] = defaultdict(list)
    for hit in hits:
        groups[(str(hit.chunk.source_ref), hit.chunk.version)].append(hit)
    return tuple(
        hit
        for group in groups.values()
        for hit in sorted(
            group, key=lambda item: (item.chunk.document_ordinal, item.chunk.chunk_id)
        )
    )


def _deduplicate(
    semantic: list[KnowledgeFragment], canonical: tuple[KnowledgeFragment, ...]
) -> tuple[KnowledgeFragment, ...]:
    seen = {
        (fragment.citations[0].knowledge_id, fragment.citations[0].version, fragment.source_text)
        for fragment in canonical
    }
    result: list[KnowledgeFragment] = []
    for fragment in semantic:
        identity = (
            fragment.citations[0].knowledge_id,
            fragment.citations[0].version,
            fragment.source_text,
        )
        if identity not in seen:
            result.append(fragment)
            seen.add(identity)
    return tuple(result)


class _Budget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0
        self.included: dict[str, int] = defaultdict(int)
        self.omitted: dict[str, int] = defaultdict(int)

    def require(self, category: str, item: CoreModel) -> None:
        if not self._include(category, item):
            raise ContextSelectionError("content budget cannot fit required Goal and Asset")

    def optional[T: CoreModel](self, category: str, item: T | None) -> T | None:
        if item is None or not self._include(category, item):
            return None
        return item

    def choose[T: CoreModel](self, category: str, items: Iterable[T]) -> tuple[T, ...]:
        selected: list[T] = []
        for item in items:
            if self._include(category, item):
                selected.append(item)
        return tuple(selected)

    def _include(self, category: str, item: CoreModel) -> bool:
        size = len(item.model_dump_json())
        if self.used + size > self.maximum:
            self.omitted[category] += 1
            return False
        self.used += size
        self.included[category] += 1
        return True

    def snapshot(self) -> ContextBudget:
        return ContextBudget(
            max_chars=self.maximum,
            included_chars=self.used,
            included_counts=dict(self.included),
            omitted_counts=dict(self.omitted),
        )
