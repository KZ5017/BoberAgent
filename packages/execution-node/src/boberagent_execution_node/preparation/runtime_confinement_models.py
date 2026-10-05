"""E5-C Node-private enforcement records. These are not runtime readiness claims."""

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from boberagent_contracts import ConfinementFeature, Sha256Digest
from boberagent_contracts.python_runtime import RuntimeCorrelation
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ClosedProbe(StrEnum):
    ISOLATION = "isolation"
    PIDS = "pids"
    MEMORY = "memory"
    BYTES = "bytes"
    INODES = "inodes"
    OUTPUT = "output"
    DEADLINE = "deadline"
    DESCENDANTS = "descendants"
    SETSID = "setsid"
    DOUBLE_FORK = "double_fork"
    CANCEL = "cancel"
    REQUESTER_DEATH = "requester_death"
    SUPERVISOR_DEATH = "supervisor_death"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuntimeConfinementConfiguration(Record):
    """Operator inputs only, never caller-supplied per-operation mount/argv inputs."""

    delegated_parent: Path
    helper_sha256: Sha256Digest
    bubblewrap_sha256: Sha256Digest
    helper_tool: Literal["runtime-confinement-helper"] = "runtime-confinement-helper"
    bubblewrap_tool: Literal["runtime-confinement-bwrap"] = "runtime-confinement-bwrap"

    @model_validator(mode="after")
    def explicit_parent(self) -> Self:
        if not self.delegated_parent.is_absolute():
            raise ValueError("explicit absolute delegated cgroup parent required")
        return self


class ProbeLimits(Record):
    """Tiny fixed synthetic probes; caller can reduce authority, never enlarge fixtures."""

    processes: StrictInt = Field(default=8, ge=6, le=8)
    memory_bytes: StrictInt = Field(
        default=64 * 1024 * 1024, ge=64 * 1024 * 1024, le=64 * 1024 * 1024
    )
    scratch_bytes: StrictInt = Field(default=1024 * 1024, ge=1024 * 1024, le=1024 * 1024)
    scratch_inodes: StrictInt = Field(default=32, ge=32, le=32)
    output_bytes: StrictInt = Field(default=4096, ge=1024, le=4096)
    seconds: StrictInt = Field(default=3, ge=1, le=3)


class StopReason(StrEnum):
    EXITED = "EXITED"
    TIMEOUT = "TIMEOUT"
    OUTPUT = "OUTPUT"
    CANCELLED = "CANCELLED"
    OWNER_LOST = "OWNER_LOST"
    SUPERVISOR_LOST = "SUPERVISOR_LOST"
    START_FAILED = "START_FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


class ConfinementFailureStage(StrEnum):
    REPORT_OR_CLEANUP = "report_or_cleanup"
    PROBE = "probe"


class ProbeEvidence(Record):
    """Expected probe limit hits are evidence, not positive constructor verification.

    Kept separate from PythonRuntimeEnforcement, which correctly forbids OOM/pids
    events on a successful future constructor. No interpreter/binding is invented.
    """

    schema_version: Literal["runtime-confinement-probe-v1"] = "runtime-confinement-probe-v1"
    profile: Literal["m20-e5-linux-bwrap-cgroup@1"] = "m20-e5-linux-bwrap-cgroup@1"
    operation_id: RuntimeCorrelation
    boot_generation: RuntimeCorrelation
    probe: ClosedProbe
    helper_sha256: Sha256Digest
    bubblewrap_sha256: Sha256Digest
    kernel: str = Field(min_length=1, max_length=128)
    limits: ProbeLimits
    attached_before_exec: bool
    exit_code: int | None
    # Direct synthetic requester's wait status, distinct from the payload exit.
    # Optional so immutable pre-fix historical evidence still deserializes.
    requester_exit_code: int | None = None
    stop_reason: StopReason
    pids_events: StrictInt = Field(ge=0)
    oom_events: StrictInt = Field(ge=0)
    memory_peak: StrictInt = Field(ge=0)
    # Some supported kernels lack pids.peak; use an identified conservative cap.
    process_peak_upper_bound: StrictInt = Field(ge=0)
    duration_milliseconds: StrictInt = Field(ge=0)
    stdout_hex: str = Field(max_length=8192)
    stderr_hex: str = Field(max_length=8192)
    group_empty: bool
    passed: bool


class ConfinementCheck(Record):
    profile: Literal["m20-e5-linux-bwrap-cgroup@1"] = "m20-e5-linux-bwrap-cgroup@1"
    features: tuple[ConfinementFeature, ...]
    probes: tuple[ProbeEvidence, ...]
