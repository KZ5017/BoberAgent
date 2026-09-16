"""Capability Contract version constants and validation helpers."""

from typing import Annotated

from pydantic import StringConstraints

CONTRACT_VERSION = "1.0"
CONTRACT_MAJOR_VERSION = 1

type VersionString = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=64,
        pattern=r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][0-9A-Za-z.-]+)?$",
    ),
]


def supports_contract_version(version: str) -> bool:
    """Return whether a semantic version belongs to supported Contract major v1."""

    major, separator, _remainder = version.partition(".")
    return bool(separator) and major.isdigit() and int(major) == CONTRACT_MAJOR_VERSION
