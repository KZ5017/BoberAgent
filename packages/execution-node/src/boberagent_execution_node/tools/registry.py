"""Logical tool discovery independent from Capability identity."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from boberagent_execution_node.config import ToolConfiguration

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9._-]*$")
_VERSION = re.compile(r"\d+(?:\.\d+)+")


class ToolAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ToolRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=_TOOL_NAME.pattern)
    configured_executable: str
    resolved_path: Path | None = None
    availability: ToolAvailability
    version: str | None = None
    diagnostic: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._configurations: dict[str, ToolConfiguration] = {}
        self._records: dict[str, ToolRecord] = {}

    def register(self, name: str, configuration: ToolConfiguration) -> None:
        if _TOOL_NAME.fullmatch(name) is None:
            raise ValueError(f"invalid logical tool name: {name}")
        if name in self._configurations:
            raise ValueError(f"duplicate logical tool: {name}")
        self._configurations[name] = configuration

    async def refresh(self) -> None:
        for name, configuration in sorted(self._configurations.items()):
            self._records[name] = await _inspect_tool(name, configuration)

    def get(self, name: str) -> ToolRecord:
        try:
            return self._records[name]
        except KeyError as error:
            raise KeyError(f"unknown logical tool: {name}") from error

    def records(self) -> tuple[ToolRecord, ...]:
        return tuple(self._records[name] for name in sorted(self._records))


async def _inspect_tool(name: str, configuration: ToolConfiguration) -> ToolRecord:
    configured = configuration.executable
    candidate = Path(configured).expanduser()
    resolved: str | None
    if candidate.is_absolute() or candidate.parent != Path("."):
        resolved = str(candidate.resolve()) if candidate.is_file() else None
    else:
        resolved = shutil.which(configured)
    if resolved is None or not os.access(resolved, os.X_OK):
        return ToolRecord(
            name=name,
            configured_executable=configured,
            availability=ToolAvailability.UNAVAILABLE,
            diagnostic="executable not found or not executable",
        )

    version: str | None = None
    diagnostic: str | None = None
    if configuration.version_args:
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                resolved,
                *configuration.version_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            text = (stdout or stderr).decode(errors="replace").strip()
            match = _VERSION.search(text)
            version = None if match is None else match.group(0)
            if process.returncode != 0:
                diagnostic = f"version probe exited with code {process.returncode}"
        except TimeoutError as error:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            diagnostic = f"version probe failed: {type(error).__name__}"
        except OSError as error:
            diagnostic = f"version probe failed: {type(error).__name__}"
    return ToolRecord(
        name=name,
        configured_executable=configured,
        resolved_path=Path(resolved),
        availability=ToolAvailability.AVAILABLE,
        version=version,
        diagnostic=diagnostic,
    )
