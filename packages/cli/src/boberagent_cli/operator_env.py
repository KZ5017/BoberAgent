"""Explicit operator-entrypoint loading of project-local environment configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE_OVERRIDE = "BOBERAGENT_ENV_FILE"
DEFAULT_ENV_FILE = ".env.local"


def operator_environment(environment: Mapping[str, str], *, project_root: Path) -> dict[str, str]:
    """Merge a local env file without mutating process globals or overriding existing values.

    The caller chooses the project root at an operator entrypoint. A missing default file is
    harmless; an explicitly selected missing file is an operator configuration error.
    """

    merged = dict(environment)
    override = environment.get(ENV_FILE_OVERRIDE)
    if override is not None and override.strip():
        selected = Path(override).expanduser()
        path = selected if selected.is_absolute() else project_root / selected
        explicit = True
    else:
        path = project_root / DEFAULT_ENV_FILE
        explicit = False
    if not path.exists():
        if explicit:
            raise ValueError(f"explicit local environment file does not exist: {path}")
        return merged
    if not path.is_file():
        raise ValueError(f"local environment path is not a regular file: {path}")
    for name, value in dotenv_values(path, interpolate=False).items():
        if value is not None:
            merged.setdefault(name, value)
    return merged
