"""Harmless manual-only proof of an explicitly granted SecretRef."""

from __future__ import annotations

import hashlib
import hmac

from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    SecretRef,
)
from boberagent_sdk import Capability, ExecutionContext
from pydantic import BaseModel, ConfigDict, Field


class SecretConsumerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    secret_ref: SecretRef
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecretConsumerCapability(Capability):
    capability_id = "test.secret_consumer"

    async def execute(
        self, operation: str, ctx: ExecutionContext, inputs: BaseModel
    ) -> CapabilityResult:
        if operation != "verify" or not isinstance(inputs, SecretConsumerInput):
            raise ValueError("unsupported Secret consumer operation/input")
        secret = await ctx.secrets.resolve(
            inputs.secret_ref,
            purpose="test.secret_consumer:verify",
        )
        actual_sha256 = hashlib.sha256(secret.reveal_bytes()).hexdigest()
        verified = hmac.compare_digest(actual_sha256, inputs.expected_sha256)
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=(
                    CapabilityOutcomeCategory.SUCCESS
                    if verified
                    else CapabilityOutcomeCategory.NEGATIVE
                )
            ),
        )
