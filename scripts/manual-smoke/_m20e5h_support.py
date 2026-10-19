"""Bounded, private manual-acceptance records, never platform authority."""

import json
import os
import stat
from pathlib import Path
from typing import Literal

from boberagent_contracts import PythonInterpreterIdentity, Sha256Digest
from pydantic import BaseModel, ConfigDict

MAX_RECORD_BYTES = 2 * 1024 * 1024


class AcceptanceFailure(ValueError):
    """Only fixed harness reason codes are rendered, never exception payloads."""


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreflightRecord(Record):
    schema_version: Literal["m20-e5h-preflight@1"] = "m20-e5h-preflight@1"
    result: Literal["PASS"] = "PASS"
    node_id: str
    helper_sha256: Sha256Digest
    bubblewrap_sha256: Sha256Digest
    environment_helper_sha256: Sha256Digest
    interpreter: PythonInterpreterIdentity
    kernel: str
    profile: Literal["m20-e5-linux-bwrap-cgroup@1"]
    delegation: dict[str, str]
    probes: list[dict[str, object]]
    node_configuration: dict[str, object]
    execution_authorized: Literal[False] = False
    resource_created: Literal[False] = False
    ready: Literal[False] = False


def fresh_directory(root: Path) -> None:
    if not root.is_absolute() or root.is_symlink():
        raise AcceptanceFailure("EXPLICIT_FRESH_RUNTIME_REQUIRED")
    # No parents=True, exist_ok, chmod, cleanup, repair or adoption of old runtimes.
    root.mkdir(mode=0o700)


def read_record[T: BaseModel](path: Path, model: type[T]) -> T:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AcceptanceFailure("REGULAR_RECORD_REQUIRED")
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise AcceptanceFailure("ACCEPTANCE_RECORD_TOO_LARGE")
    return model.model_validate_json(data)


def write_record(root: Path, name: str, value: BaseModel | dict[str, object]) -> None:
    data = (
        value.model_dump_json(indent=2)
        if isinstance(value, BaseModel)
        else json.dumps(value, indent=2, sort_keys=True)
    ).encode() + b"\n"
    if len(data) > MAX_RECORD_BYTES:
        raise AcceptanceFailure("ACCEPTANCE_RECORD_TOO_LARGE")
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def require(condition: object, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def non_actions() -> dict[str, bool]:
    return dict(
        execution_authorized=False,
        preparation_terminal=False,
        acquired_source_executed=False,
        package_installation=False,
        secret_delivery=False,
        target_activity=False,
    )
