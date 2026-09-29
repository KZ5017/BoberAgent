"""Safe persistence errors: never render untrusted document values or SQL parameters."""

from boberagent_core.persistence.repositories import PersistenceIntegrityError


class PlanningPersistenceError(PersistenceIntegrityError):
    """Unknown schema, corrupted document or inconsistent stored identity."""


class PlanningConflict(PlanningPersistenceError):
    """Identity collision, stale revision or forbidden historical rewrite."""
