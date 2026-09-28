"""Core-private identity shared by immutable inspection profile documents."""

from boberagent_contracts.refs import DomainRef


class PoCInspectionRef(DomainRef):
    """Stable identity of one inspection attempt, not a source content hash."""
