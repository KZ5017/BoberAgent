"""Core-owned, explicit D5 policy configuration and authority snapshots.

These values describe policy, not runtime readiness or execution permission.
"""

from typing import Literal, Self

from boberagent_contracts import AssetRef, MissionRef, ServiceRef, Sha256Digest
from boberagent_contracts._base import FrozenContractModel
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import (
    EffectScope,
    ExecutionLimits,
    ExecutionLocation,
    FilesystemOperation,
    PlanDependencyKind,
)
from boberagent_contracts.plan_values import TargetRole
from pydantic import Field, StrictBool, model_validator

from .records import PlanDecisionRecord


class NarrowPolicyProfile(FrozenContractModel):
    """Explicit Mission/target allowlist; never inferred from Mission ownership."""

    profile: Literal["m20-python-single-target"] = "m20-python-single-target"
    version: Literal["1"] = "1"
    mission_ref: MissionRef
    allowed_asset_refs: tuple[AssetRef, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )
    allowed_service_refs: tuple[ServiceRef, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    allowed_target_roles: tuple[Literal[TargetRole.SERVICE_ENDPOINT], ...] = (
        TargetRole.SERVICE_ENDPOINT,
    )
    runtime_kind: Literal["python"] = "python"
    execution_location: Literal[ExecutionLocation.ATTACKER_NODE] = ExecutionLocation.ATTACKER_NODE
    platform: Literal["LINUX"] = "LINUX"
    platform_variant: Literal["kali"] = "kali"
    require_user_space: Literal[True] = True
    require_noninteractive: Literal[True] = True
    require_source_visible: Literal[True] = True
    allowed_dependency_kinds: tuple[
        Literal[PlanDependencyKind.STDLIB_MODULE, PlanDependencyKind.LOCAL_MODULE], ...
    ] = (PlanDependencyKind.STDLIB_MODULE, PlanDependencyKind.LOCAL_MODULE)
    allowed_filesystem_scope: Literal[EffectScope.BOUNDED] = EffectScope.BOUNDED
    allowed_filesystem_operations: tuple[Literal[FilesystemOperation.READ], ...] = (
        FilesystemOperation.READ,
    )
    allowed_network_transport: Literal["tcp"] = "tcp"
    allow_public_egress: Literal[False] = False
    allow_callback: Literal[False] = False
    allow_listener: Literal[False] = False
    allow_multi_target: Literal[False] = False
    allow_secrets: Literal[False] = False
    allow_resources: Literal[False] = False
    allow_sessions: Literal[False] = False
    maximum_limits: ExecutionLimits
    require_operator_approval: StrictBool = True

    @model_validator(mode="after")
    def unique_scope(self) -> Self:
        if len(set(self.allowed_asset_refs)) != len(self.allowed_asset_refs) or len(
            set(self.allowed_service_refs)
        ) != len(self.allowed_service_refs):
            raise ValueError("policy scope references must be unique")
        if self.maximum_limits.process_count != 1 or self.maximum_limits.disk_write_bytes != 0:
            raise ValueError("initial policy permits one process and zero disk writes")
        return self

    @property
    def digest(self) -> Sha256Digest:
        return canonical_digest(self)


class PolicyScopeSnapshot(FrozenContractModel):
    """Reference/status metadata loaded from Core, never supplied by the planner."""

    mission_ref: MissionRef
    mission_status: str
    mission_assets: tuple[tuple[AssetRef, str], ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )
    target_asset_ref: AssetRef | None
    target_asset_mission_ref: MissionRef | None
    target_asset_address: str | None
    target_service_ref: ServiceRef | None
    target_service_asset_ref: AssetRef | None
    target_service_transport: str | None
    target_service_port: int | None
    target_service_state: str | None


class PolicyEvaluation(FrozenContractModel):
    decision: Literal["ALLOW", "DENY", "REQUIRES_APPROVAL"]
    reason_codes: tuple[str, ...] = Field(min_length=1)


class PolicyAssessmentResult(FrozenContractModel):
    record: PlanDecisionRecord
    policy_sha256: Sha256Digest
    execution_readiness: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    authorization: Literal["NONE"] = "NONE"
