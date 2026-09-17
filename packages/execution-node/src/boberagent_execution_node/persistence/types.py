"""SQLite-safe UTC timestamp type."""

from datetime import UTC, datetime

from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import String, TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution Node timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat()

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("persisted Execution Node timestamp is not timezone-aware")
        return parsed.astimezone(UTC)
