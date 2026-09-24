"""Deterministic, versioned Procedure Registry; never an execution engine."""

from __future__ import annotations

from collections.abc import Iterable

from .markdown import CuratedMarkdownLoader
from .models import KnowledgeStatus, ProcedureDefinition, ProcedureId
from .repository import KnowledgeConflict


class ProcedureRegistry:
    def __init__(
        self,
        procedures: Iterable[ProcedureDefinition],
        *,
        known_capability_ids: frozenset[str] | None = None,
    ) -> None:
        by_version: dict[tuple[ProcedureId, int], ProcedureDefinition] = {}
        canonical: dict[ProcedureId, ProcedureDefinition] = {}
        for procedure in procedures:
            key = procedure.procedure_id, procedure.version
            if key in by_version:
                raise KnowledgeConflict(f"duplicate Procedure identity/version: {key}")
            if known_capability_ids is not None:
                unknown = set(procedure.candidate_capability_ids) - known_capability_ids
                if unknown:
                    raise KnowledgeConflict(
                        f"Procedure {procedure.procedure_id} references unknown Capabilities: "
                        f"{', '.join(sorted(unknown))}"
                    )
            by_version[key] = procedure
            if procedure.status is KnowledgeStatus.CANONICAL:
                if procedure.procedure_id in canonical:
                    raise KnowledgeConflict(
                        f"multiple current canonical Procedure versions: {procedure.procedure_id}"
                    )
                canonical[procedure.procedure_id] = procedure
        self._by_version = by_version
        self._canonical = canonical

    @classmethod
    def from_directory(
        cls,
        loader: CuratedMarkdownLoader,
        *,
        known_capability_ids: frozenset[str] | None = None,
    ) -> ProcedureRegistry:
        return cls(
            (loader.load_procedure(path) for path in loader.files("procedures")),
            known_capability_ids=known_capability_ids,
        )

    def get(
        self, procedure_id: ProcedureId, *, version: int | None = None
    ) -> ProcedureDefinition | None:
        """Current canonical by default; explicit versions include historical items."""

        if version is None:
            return self._canonical.get(procedure_id)
        return self._by_version.get((procedure_id, version))

    def find(
        self,
        *,
        status: KnowledgeStatus | None = KnowledgeStatus.CANONICAL,
        goal_type: str | None = None,
        environment: str | None = None,
        technology: str | None = None,
        required_state: str | None = None,
        produced_state: str | None = None,
        capability_id: str | None = None,
    ) -> tuple[ProcedureDefinition, ...]:
        """Return all exact metadata candidates; no implicit ranking or selection."""

        values = (
            self._by_version.values()
            if status is None
            else (item for item in self._by_version.values() if item.status is status)
        )
        return tuple(
            sorted(
                (
                    item
                    for item in values
                    if (goal_type is None or item.goal_type == goal_type)
                    and (environment is None or item.environment == environment)
                    and (technology is None or item.technology == technology)
                    and (required_state is None or required_state in item.required_state)
                    and (produced_state is None or produced_state in item.produced_state)
                    and (capability_id is None or capability_id in item.candidate_capability_ids)
                ),
                key=lambda item: (item.procedure_id, item.version),
            )
        )

    def versions(self, procedure_id: ProcedureId) -> tuple[ProcedureDefinition, ...]:
        return tuple(
            sorted(
                (
                    item
                    for (item_id, _), item in self._by_version.items()
                    if item_id == procedure_id
                ),
                key=lambda item: item.version,
            )
        )
