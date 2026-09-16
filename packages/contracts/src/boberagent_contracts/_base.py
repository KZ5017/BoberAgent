"""Shared validation primitives for Contract models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

type NonEmptyStr = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
type ShortStr = Annotated[str, StringConstraints(min_length=1, max_length=255)]
type SymbolicName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=255, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]


class ContractModel(BaseModel):
    """Base for strict-envelope, assignment-validated Contract value objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class FrozenContractModel(ContractModel):
    """Base for immutable Contract records."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
