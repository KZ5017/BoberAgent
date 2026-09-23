"""Validated normalized input for candidate Credential materialization."""

from __future__ import annotations

from typing import Annotated, Self

from boberagent_contracts import DomainRef, IdentityRef, JsonObject, SecretRef
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

_Symbol = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class CandidateSecretBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: _Symbol
    secret_ref: SecretRef


class CredentialCandidateValue(BaseModel):
    """Safe normalized payload for a ``credential.candidate`` Observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_type: _Symbol
    username: str | None = Field(default=None, min_length=1, max_length=255)
    identity_ref: IdentityRef | None = None
    secrets: tuple[CandidateSecretBinding, ...] = Field(min_length=1)
    scope_refs: tuple[DomainRef, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unique_roles(self) -> Self:
        roles = [binding.role for binding in self.secrets]
        if len(roles) != len(set(roles)):
            raise ValueError("candidate Credential secret roles must be unique")
        if len(self.scope_refs) != len(set(self.scope_refs)):
            raise ValueError("candidate Credential scope refs must be unique")
        return self
