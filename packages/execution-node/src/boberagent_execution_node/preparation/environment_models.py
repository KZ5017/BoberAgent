"""Node-private closed E5-E evidence; no readiness or execution authority."""

from typing import Literal, Self

from boberagent_contracts import (
    PythonEnvironmentInventory,
    PythonProviderOperation,
    PythonRuntimeBinding,
    PythonRuntimeEvidence,
    Sha256Digest,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation
from pydantic import AwareDatetime, Field, StrictInt, model_validator

from .runtime_confinement_models import (
    EnvironmentLimits,
    ProbeEvidence,
    Record,
    TrustedPythonOperation,
)

EXPORT_LIMIT = 32 * 1024**2 + 65536
WRITE_LIMIT = 32 * 1024**2
FILE_LIMIT = 256


class EnvironmentEntry(Record):
    path: str = Field(min_length=1, max_length=128)
    kind: Literal["file", "directory", "symlink"]
    mode: StrictInt
    size: StrictInt = Field(ge=0, le=WRITE_LIMIT)
    sha256: Sha256Digest | None = None
    target: Literal["lib"] | None = None


class EnvironmentManifest(Record):
    schema_version: Literal["m20-e5-empty-environment@1"] = "m20-e5-empty-environment@1"
    entries: tuple[EnvironmentEntry, ...] = Field(min_length=1, max_length=FILE_LIMIT)
    written_bytes: StrictInt = Field(ge=0, le=WRITE_LIMIT)
    created_entries: StrictInt = Field(ge=0, le=FILE_LIMIT)


class EnvironmentIdentity(Record):
    implementation: Literal["cpython"]
    version: str
    platform: Literal["linux"]
    architecture: Literal["x86_64"]
    cache_tag: Literal["cpython-312"]
    soabi: Literal["cpython-312-x86_64-linux-gnu"]
    prefix: Literal["/work/venv"]
    base_prefix: Literal["/runtime"]
    executable: Literal["/work/venv/bin/python3.12"]
    paths: tuple[str, ...]
    isolated: Literal[1]
    no_site: Literal[0]
    no_bytecode: Literal[True]
    user_site: Literal[False]
    written_bytes: Literal[0]
    created_entries: Literal[0]


class EmptyEnvironmentEvidence(Record):
    schema_version: Literal["m20-e5-empty-environment-evidence@1"] = (
        "m20-e5-empty-environment-evidence@1"
    )
    binding: PythonRuntimeBinding
    operation_id: RuntimeCorrelation
    operation: Literal[PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT] = (
        PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT
    )
    generation: StrictInt = Field(gt=0)
    construction_version: Literal["python-stdlib@1"] = "python-stdlib@1"
    mechanism: Literal["ACCOUNTED_CPYTHON_ENVBUILDER_WITHOUT_PIP_COPIES"] = (
        "ACCOUNTED_CPYTHON_ENVBUILDER_WITHOUT_PIP_COPIES"
    )
    helper_sha256: Sha256Digest
    provenance: PythonRuntimeEvidence
    manifest: EnvironmentManifest
    environment: PythonEnvironmentInventory
    construction: ProbeEvidence
    verification: ProbeEvidence
    committed_write_bytes: StrictInt = Field(ge=0)
    committed_file_count: StrictInt = Field(ge=0)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    state: Literal["CREATING"] = "CREATING"
    phase: Literal["VERIFYING"] = "VERIFYING"
    validity: Literal["UNCHECKED"] = "UNCHECKED"

    @model_validator(mode="after")
    def complete_closed_proof(self) -> Self:
        if (
            self.binding != self.provenance.binding
            or self.provenance.verification != "PROVENANCE_VERIFIED"
            or self.completed_at < self.started_at
            or self.construction.probe is not TrustedPythonOperation.CREATE_ENVIRONMENT
            or self.verification.probe is not TrustedPythonOperation.VERIFY_ENVIRONMENT
        ):
            raise ValueError("construction provenance/operation mismatch")
        for probe in (self.construction, self.verification):
            if (
                not isinstance(probe.limits, EnvironmentLimits)
                or not probe.passed
                or not probe.group_empty
                or not probe.attached_before_exec
                or probe.exit_code != 0
                or probe.pids_events
                or probe.oom_events
                or probe.stderr_hex
                or probe.helper_sha256 != self.binding.backend.helper_sha256
                or probe.bubblewrap_sha256 != self.binding.backend.binary_sha256
                or probe.memory_peak > probe.limits.memory_bytes
                or probe.duration_milliseconds > probe.limits.seconds * 1000
            ):
                raise ValueError("incomplete environment confinement proof")
        if self.construction.boot_generation != self.verification.boot_generation:
            raise ValueError("construction generation changed")
        return self
