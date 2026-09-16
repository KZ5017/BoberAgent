"""Core timestamp helpers."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return an unambiguous timezone-aware UTC timestamp."""

    return datetime.now(UTC)
