"""Validated local Execution Node configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolConfiguration(BaseModel):
    """Explicit discovery hints for one logical tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executable: str = Field(min_length=1)
    version_args: tuple[str, ...] = ()


class NodeConfiguration(BaseModel):
    """All filesystem locations are explicit and testable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_directory: Path
    database_path: Path
    identity_path: Path
    workspace_root: Path
    artifact_spool_root: Path
    configured_node_id: str | None = Field(
        default=None, min_length=3, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    capability_paths: tuple[Path, ...] = ()
    tools: dict[str, ToolConfiguration] = Field(default_factory=dict)
    process_terminate_grace_seconds: float = Field(default=1.0, gt=0, le=30)
    max_inline_process_output_bytes: int = Field(default=1024 * 1024, ge=0)

    @property
    def process_output_root(self) -> Path:
        """Managed staging area used before large output becomes an Artifact."""

        return self.runtime_directory / "process-output"

    @field_validator(
        "runtime_directory",
        "database_path",
        "identity_path",
        "workspace_root",
        "artifact_spool_root",
        "capability_paths",
        mode="before",
    )
    @classmethod
    def expand_paths(cls, value: object) -> object:
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, (list, tuple)):
            return tuple(path.expanduser() if isinstance(path, Path) else path for path in value)
        return value

    @classmethod
    def for_runtime_directory(
        cls,
        runtime_directory: Path,
        *,
        capability_paths: tuple[Path, ...] = (),
        tools: dict[str, ToolConfiguration] | None = None,
        configured_node_id: str | None = None,
    ) -> NodeConfiguration:
        root = runtime_directory.expanduser().resolve()
        return cls(
            runtime_directory=root,
            database_path=root / "runtime.sqlite3",
            identity_path=root / "node-identity.json",
            workspace_root=root / "workspaces",
            artifact_spool_root=root / "artifacts",
            configured_node_id=configured_node_id,
            capability_paths=capability_paths,
            tools={} if tools is None else tools,
        )

    def prepare_directories(self) -> None:
        """Create only directories owned by this configured runtime."""

        self.runtime_directory.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.artifact_spool_root.mkdir(parents=True, exist_ok=True)
        self.process_output_root.mkdir(parents=True, exist_ok=True)
