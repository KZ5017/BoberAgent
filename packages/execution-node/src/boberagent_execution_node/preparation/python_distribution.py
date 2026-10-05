"""Non-executing, bounded inventory of an explicitly provisioned runtime closure.

uv is an operator installation source, never a production dependency/discovery API.
Nothing in this module executes the candidate, source, installer or ELF tooling.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import struct
import time
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Literal, NamedTuple, Self, TypedDict

from boberagent_contracts import PythonRuntimeFailure, PythonRuntimeReason, Sha256Digest
from boberagent_contracts.plan_canonical import canonical_digest, canonical_json, canonical_value
from boberagent_contracts.python_runtime import (
    PythonDistributionEvidence,
    PythonDistributionIdentity,
    PythonProjectedDistributionIdentity,
    PythonRuntimeProjectionIdentity,
    PythonRuntimeProjectionProfile,
)
from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, model_validator

MANIFEST_VERSION: Literal["m20-e5-python-distribution@1"] = "m20-e5-python-distribution@1"


class EntryFields(TypedDict):
    path: str
    mode: int
    uid: int
    gid: int


def digest_value(value: object) -> str:
    return hashlib.sha256(canonical_json(canonical_value(value)).encode()).hexdigest()


class ProvenanceStage(StrEnum):
    FILESYSTEM_TRUST = "filesystem_trust"
    PARENT_TRUST = "parent_trust"
    FILE_BOUND = "file_bound"
    FILE_CHANGED = "file_changed"
    DISTRIBUTION_INVENTORY = "distribution_inventory"
    INTERPRETER_MISSING = "interpreter_missing"
    CONFIGURED_DIGEST = "configured_digest"
    CURRENT_DISTRIBUTION = "current_distribution"
    IDENTITY_RESULT = "identity_result"
    EVIDENCE_BINDING = "evidence_binding"
    EVIDENCE_REPLAY = "evidence_replay"
    RESOURCE_BINDING = "resource_binding"
    SEALED_BINDING = "sealed_binding"
    RETAINED_EVIDENCE = "retained_evidence"
    FRESH_CONTROLS = "fresh_controls"
    AUTHORITY_TIME = "authority_time"
    POST_IDENTITY = "post_identity"
    BACKEND_BINDING = "backend_binding"
    OPERATION_INTERRUPTED = "operation_interrupted"
    OPERATION_DEADLINE = "operation_deadline"


class ProvenanceFailure(RuntimeError):
    """Closed diagnostics only: no path, environment, metadata or captured output."""

    def __init__(self, reason: PythonRuntimeReason, stage: str) -> None:
        self.failure = PythonRuntimeFailure(
            reason_code=reason.preparation_reason, runtime_reason=reason
        )
        self.stage = ProvenanceStage(stage)
        super().__init__(reason.value)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PythonDistributionConfiguration(Record):
    """Private operator configuration. No PATH/default/fallback or caller code."""

    distribution_root: Path
    system_library_root: Path
    expected_manifest_sha256: Sha256Digest
    expected_interpreter_sha256: Sha256Digest
    max_entries: StrictInt = Field(default=25000, ge=1, le=100000)
    max_runtime_bytes: StrictInt = Field(default=1024**3, ge=1, le=4 * 1024**3)
    max_metadata_bytes: StrictInt = Field(default=128 * 1024, ge=1, le=1024**2)

    @model_validator(mode="after")
    def absolute_sources(self) -> Self:
        for path in (self.distribution_root, self.system_library_root):
            if not path.is_absolute() or ".." in path.parts or path == Path("/"):
                raise ValueError("explicit absolute distribution/support root required")
        return self


class ManifestEntry(Record):
    path: str
    kind: Literal["file", "directory", "symlink"]
    mode: int
    uid: int
    gid: int
    size: int = 0
    sha256: Sha256Digest | None = None
    target: str | None = None


class DistributionManifest(Record):
    schema_version: Literal["m20-e5-python-distribution@1"] = MANIFEST_VERSION
    root_binding_sha256: Sha256Digest
    interpreter_relative_path: Literal["bin/python3.12"] = "bin/python3.12"
    interpreter_sha256: Sha256Digest
    entries: tuple[ManifestEntry, ...]
    support_entries: tuple[ManifestEntry, ...]
    metadata_sha256: Sha256Digest | None

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def identity(self) -> PythonDistributionIdentity:
        return PythonDistributionIdentity(
            manifest_version=MANIFEST_VERSION,
            provisioning="OPERATOR_PREPROVISIONED_UV",
            interpreter_relative_path="bin/python3.12",
            manifest_sha256=self.digest,
            root_binding_sha256=self.root_binding_sha256,
            support_manifest_sha256=digest_value(self.support_entries),
            metadata_sha256=self.metadata_sha256,
            entry_count=len(self.entries) + len(self.support_entries),
            runtime_bytes=sum(e.size for e in (*self.entries, *self.support_entries)),
        )


class ExcludedRuntimeEntry(Record):
    entry: ManifestEntry
    feature: Literal["TKINTER_TCL_TK", "PACKAGE_MANAGER"] = "TKINTER_TCL_TK"
    role: Literal[
        "NATIVE_MODULE",
        "PYTHON_PACKAGE",
        "EXCLUSIVE_LIBRARY",
        "FEATURE_DATA",
        "PROVISIONING_NAMESPACE",
        "STDLIB_BOOTSTRAP",
        "LAUNCHER",
    ]


class ProjectedDistributionManifest(Record):
    """v2 is a new, explicit executable view, never a reinterpretation of v1."""

    schema_version: Literal["m20-e5-python-distribution@2"] = "m20-e5-python-distribution@2"
    root_binding_sha256: Sha256Digest
    interpreter_relative_path: Literal["bin/python3.12"] = "bin/python3.12"
    interpreter_sha256: Sha256Digest
    entries: tuple[ManifestEntry, ...]
    excluded_entries: tuple[ExcludedRuntimeEntry, ...]
    support_entries: tuple[ManifestEntry, ...]
    metadata_sha256: Sha256Digest | None
    projection: PythonRuntimeProjectionIdentity

    @model_validator(mode="after")
    def exact_membership(self) -> Self:
        base = tuple(
            sorted((*self.entries, *(e.entry for e in self.excluded_entries)), key=lambda e: e.path)
        )
        if (
            len({e.path for e in base}) != len(base)
            or any(
                e.feature not in self.projection.profile.unsupported_optional
                for e in self.excluded_entries
            )
            or self.projection.base_manifest_sha256 != digest_value(base)
            or self.projection.selected_manifest_sha256
            != digest_value((self.entries, self.support_entries))
            or self.projection.excluded_manifest_sha256 != digest_value(self.excluded_entries)
        ):
            raise ValueError("projection manifest mismatch")
        if "PACKAGE_MANAGER" in self.projection.profile.unsupported_optional and any(
            _package_manager_path(e.path) for e in self.entries
        ):
            raise ValueError("package-manager namespace in selected projection")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def identity(self) -> PythonProjectedDistributionIdentity:
        return PythonProjectedDistributionIdentity(
            manifest_version=self.schema_version,
            provisioning="OPERATOR_PREPROVISIONED_UV",
            interpreter_relative_path=self.interpreter_relative_path,
            manifest_sha256=self.digest,
            root_binding_sha256=self.root_binding_sha256,
            support_manifest_sha256=digest_value(self.support_entries),
            metadata_sha256=self.metadata_sha256,
            entry_count=len(self.entries) + len(self.support_entries),
            runtime_bytes=sum(e.size for e in (*self.entries, *self.support_entries)),
            projection=self.projection,
        )


type DistributionEvidenceManifest = DistributionManifest | ProjectedDistributionManifest
MANIFEST_ADAPTER: TypeAdapter[DistributionEvidenceManifest] = TypeAdapter(
    DistributionEvidenceManifest
)


def _trust(info: os.stat_result, *, link: bool = False) -> None:
    if info.st_uid not in {0, os.getuid()} or (not link and info.st_mode & 0o6022):
        raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "filesystem_trust")


def _parents(path: Path) -> list[tuple[str, int, int, int, int, int]]:
    pins = []
    for directory in (path, *path.parents):
        info = directory.lstat()
        _trust(info)
        if not stat.S_ISDIR(info.st_mode):
            raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "parent_trust")
        pins.append(
            (
                str(directory),
                info.st_dev,
                info.st_ino,
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            )
        )
    return pins


def _bytes(path: Path, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _trust(before)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "file_bound")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())

        def stable(i: os.stat_result) -> tuple[int, ...]:
            return (
                i.st_dev,
                i.st_ino,
                i.st_mode,
                i.st_uid,
                i.st_gid,
                i.st_size,
                i.st_mtime_ns,
                i.st_ctime_ns,
            )

        if stable(before) != stable(after) or len(data) != before.st_size:
            raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "file_changed")
        return data


class _LoadSegment(NamedTuple):
    file_offset: int
    address: int
    file_size: int


class _DependencyKind(StrEnum):
    BARE_SONAME = "BARE_SONAME"
    PATH_DEPENDENCY = "PATH_DEPENDENCY"


class _ELFDependency(NamedTuple):
    owner: Path
    raw: str
    kind: _DependencyKind
    resolved: Path | None


def _dependency(name: str, owner: Path, boundary: Path) -> _ELFDependency:
    """Closed DT_NEEDED syntax; lexical resolution performs no filesystem access."""
    if not owner.is_absolute() or not boundary.is_absolute() or not owner.is_relative_to(boundary):
        raise ValueError("dependency owner boundary")
    if "/" not in name:
        if re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", name) is None or name in {".", ".."}:
            raise ValueError("invalid dependency name")
        return _ELFDependency(owner, name, _DependencyKind.BARE_SONAME, None)
    if len(name) > 1024:
        raise ValueError("dependency pathname bound")
    prefix = next((p for p in ("$ORIGIN/", "${ORIGIN}/") if name.startswith(p)), None)
    if prefix is None:
        raise ValueError("unsupported dependency pathname")
    components = name.removeprefix(prefix).split("/")
    if any(re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", part) is None for part in components):
        raise ValueError("invalid dependency pathname")
    resolved = owner.parent
    for part in components:
        resolved = Path(os.path.normpath(resolved / part))
        if not resolved.is_relative_to(boundary):
            raise ValueError("dependency pathname escape")
    return _ELFDependency(owner, name, _DependencyKind.PATH_DEPENDENCY, resolved)


def _read_file_backed_vaddr_range(
    data: bytes, loads: tuple[_LoadSegment, ...], address: int, size: int
) -> bytes:
    """Resolve bounded ELF64 bytes, never zero-fill, across independent mappings.

    Split at every mapping start/end, including overlapping starts. Every active
    mapping must supply identical bytes; segment order cannot hide ambiguity.
    Adjacent virtual addresses need not correspond to adjacent file offsets.
    """
    maximum = 2**64 - 1
    if not 0 <= address <= maximum or not 1 <= size <= 4 * 1024**2 or address + size > maximum:
        raise ValueError("ELF virtual range bounds")
    if not 1 <= len(loads) <= 128:
        raise ValueError("ELF load count")
    end = address + size
    boundaries = {address, end}
    for segment in loads:
        if (
            not 0 <= segment.address <= maximum
            or not 0 <= segment.file_offset <= maximum
            or not 0 <= segment.file_size <= maximum
            or segment.address + segment.file_size > maximum
            or segment.file_offset + segment.file_size > min(maximum, len(data))
        ):
            raise ValueError("ELF load bounds")
        for boundary in (segment.address, segment.address + segment.file_size):
            if address < boundary < end:
                boundaries.add(boundary)
    ordered = sorted(boundaries)
    result = bytearray()
    for start, stop in pairwise(ordered):
        resolved = None
        for segment in loads:
            if segment.address <= start and stop <= segment.address + segment.file_size:
                offset = segment.file_offset + start - segment.address
                chunk = data[offset : offset + stop - start]
                if resolved is not None and chunk != resolved:
                    raise ValueError("ELF ambiguous load mappings")
                resolved = chunk
        if resolved is None:
            raise ValueError("ELF mapped strings gap")
        result.extend(resolved)
    return bytes(result)


class _ELFMetadata(NamedTuple):
    needed: tuple[_ELFDependency, ...] = ()
    interpreter: str | None = None
    soname: str | None = None
    search_paths: tuple[str, ...] = ()
    python_exports: tuple[str, ...] = ()


def _python_exports(data: bytes) -> tuple[str, ...]:
    """Bounded ELF64 dynamic-symbol identities, not filename inference or execution."""
    offset = struct.unpack_from("<Q", data, 40)[0]
    width, count = struct.unpack_from("<HH", data, 58)
    if not offset and not count:
        return ()
    if width != 64 or not 1 <= count <= 4096 or offset + width * count > len(data):
        raise ValueError("ELF section bounds")
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * width) for i in range(count)]
    exports = set()
    symbol_count = 0
    for section in sections:
        _, kind, _, _, start, size, link, _, _, entry_size = section
        if kind != 11:  # SHT_DYNSYM
            continue
        symbol_count += size // 24
        if (
            entry_size != 24
            or size % 24
            or symbol_count > 65536
            or start + size > len(data)
            or link >= count
        ):
            raise ValueError("ELF symbol bounds")
        strings = sections[link]
        if strings[1] != 3 or strings[5] > 4 * 1024**2 or strings[4] + strings[5] > len(data):
            raise ValueError("ELF symbol strings")
        table = data[strings[4] : strings[4] + strings[5]]
        for position in range(start, start + size, 24):
            name, info, _, index, _, _ = struct.unpack_from("<IBBHQQ", data, position)
            end = table.find(b"\0", name, name + 4097)
            if name >= len(table) or end < 0:
                raise ValueError("ELF symbol name")
            if index and info >> 4 in {1, 2} and table.startswith(b"PyInit_", name):
                if end - name > 135:
                    raise ValueError("ELF Python module identity bound")
                raw = table[name:end]
                value = raw.decode("ascii")
                if re.fullmatch(r"PyInit_[A-Za-z0-9_]{1,128}", value) is None:
                    raise ValueError("ELF Python module identity")
                exports.add(value)
    return tuple(sorted(exports))


def _inspect_elf(data: bytes, *, owner: Path, boundary: Path) -> _ELFMetadata:
    """Validate structure for EVERY ELF; eligibility is separate from membership."""
    if not data.startswith(b"\x7fELF"):
        return _ELFMetadata()
    if (
        len(data) < 64
        or data[:6] != b"\x7fELF\x02\x01"
        or struct.unpack_from("<H", data, 18)[0] != 62
    ):
        raise ValueError("unsupported ELF")
    offset = struct.unpack_from("<Q", data, 32)[0]
    width, count = struct.unpack_from("<HH", data, 54)
    if struct.unpack_from("<H", data, 16)[0] == 1 and count == 0:
        # Inert config/*.o files may be retained in the install-only tree;
        # inventory them, but never mistake them for executable/library closure.
        _python_exports(data)
        return _ELFMetadata()
    if width != 56 or not 1 <= count <= 128 or offset + count * width > len(data):
        raise ValueError("ELF bounds")
    segments = [struct.unpack_from("<IIQQQQQQ", data, offset + i * width) for i in range(count)]
    for _, _, file_offset, _, _, size, _, _ in segments:
        if file_offset + size > len(data):
            raise ValueError("ELF segment bounds")
    loads = tuple(
        _LoadSegment(file_offset, address, size)
        for kind, _, file_offset, address, _, size, _, _ in segments
        if kind == 1
    )
    for kind, _, _, address, _, size, memory_size, _ in segments:
        if kind == 1 and (size > memory_size or address + memory_size > 2**64 - 1):
            raise ValueError("ELF load structure bounds")
    interpreter = None
    dynamic: list[tuple[int, int]] = []
    for kind, _, file_offset, _, _, size, _, _ in segments:
        if kind == 3:
            if size > 256:
                raise ValueError("ELF loader bound")
            interpreter = data[file_offset : file_offset + size].rstrip(b"\0").decode("ascii")
            if interpreter != "/lib64/ld-linux-x86-64.so.2":
                raise ValueError("unsupported loader")
        if kind == 2:
            if size > 65536 or size % 16:
                raise ValueError("ELF dynamic bound")
            dynamic = [
                struct.unpack_from("<qQ", data, i)
                for i in range(file_offset, file_offset + size, 16)
            ]
    if not dynamic:
        return _ELFMetadata(interpreter=interpreter, python_exports=_python_exports(data))
    string_addresses = [value for key, value in dynamic if key == 5]
    string_sizes = [value for key, value in dynamic if key == 10]
    if (
        len(string_addresses) != 1
        or len(string_sizes) != 1
        or not 1 <= string_sizes[0] <= 4 * 1024**2
    ):
        raise ValueError("ELF string table")
    table = _read_file_backed_vaddr_range(data, loads, string_addresses[0], string_sizes[0])
    needed = []
    search_paths = []
    sonames = []
    for key, value in dynamic:
        if key not in {1, 14, 15, 29}:
            continue
        if value >= len(table) or b"\0" not in table[value:]:
            raise ValueError("ELF string bounds")
        name = table[value : table.index(0, value)].decode("ascii")
        if key == 1:
            needed.append(_dependency(name, owner, boundary))
        elif key == 14:
            if _dependency(name, owner, boundary).kind is not _DependencyKind.BARE_SONAME:
                raise ValueError("ELF SONAME identity")
            sonames.append(name)
        else:
            # Syntax stays bounded even for excluded optional components. Only
            # executable eligibility (absolute vs confined ORIGIN) is deferred.
            if (
                len(name) > 4096
                or not name
                or any(
                    not part or re.fullmatch(r"[A-Za-z0-9_./${}+-]+", part) is None
                    for part in name.split(":")
                )
            ):
                raise ValueError("ELF search path syntax")
            search_paths.append(name)
    if len(sonames) > 1:
        raise ValueError("ELF ambiguous SONAME")
    return _ELFMetadata(
        tuple(needed),
        interpreter,
        sonames[0] if sonames else None,
        tuple(search_paths),
        _python_exports(data),
    )


def _eligible(metadata: _ELFMetadata, *, owner: Path, boundary: Path) -> None:
    for name in metadata.search_paths:
        if any(part != "$ORIGIN" and not part.startswith("$ORIGIN/") for part in name.split(":")):
            raise ValueError("external runtime search path")
        else:
            for part in name.split(":"):
                resolved = Path(
                    os.path.normpath(owner.parent / part.removeprefix("$ORIGIN").lstrip("/"))
                )
                if not resolved.is_relative_to(boundary):
                    raise ValueError("runtime search path escape")


def _elf(
    data: bytes, *, owner: Path, boundary: Path
) -> tuple[tuple[_ELFDependency, ...], str | None]:
    metadata = _inspect_elf(data, owner=owner, boundary=boundary)
    _eligible(metadata, owner=owner, boundary=boundary)
    return metadata.needed, metadata.interpreter


def _package_manager_path(path: str) -> bool:
    return any(
        path == namespace or path.startswith(namespace + "/")
        for namespace in ("lib/python3.12/site-packages", "lib/python3.12/ensurepip")
    )


class _ScriptFacts(NamedTuple):
    modules: frozenset[str]
    console_modules: frozenset[str]


def _script_facts(data: bytes, *, launcher: bool) -> _ScriptFacts:
    """Parse source as data, never import it. Closed, bounded console-wrapper facts."""
    if len(data) > 256 * 1024:
        raise ValueError("launcher source bound")
    tree = ast.parse(data)
    nodes = list(ast.walk(tree))
    if len(nodes) > 20000:
        raise ValueError("launcher syntax bound")
    imports: dict[str, str] = {}
    dynamic_names = {"__import__", "import_module", "run_module"}
    modules: set[str] = set()
    console: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                imports[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules.add(node.module)
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module
                if alias.name in {"__import__", "import_module", "run_module"}:
                    dynamic_names.add(alias.asname or alias.name)

    def referenced(call: ast.Call) -> str | None:
        name = call.func
        while isinstance(name, ast.Attribute):
            name = name.value
        return imports.get(name.id) if isinstance(name, ast.Name) else None

    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        # A literal dynamic module invocation is a dependency, not a certified
        # console wrapper. Such a launcher must reject if that module is excluded.
        function = node.func
        if isinstance(function, ast.Name | ast.Attribute):
            method = function.id if isinstance(function, ast.Name) else function.attr
            if method == "load_entry_point" and launcher:
                raise ValueError("unsupported metadata-based launcher")
            if method in dynamic_names:
                if not node.args or not isinstance(node.args[0], ast.Constant):
                    if launcher:
                        raise ValueError("unresolved launcher module")
                    continue
                value = node.args[0].value
                if not isinstance(value, str):
                    if launcher:
                        raise ValueError("unresolved launcher module")
                    continue
                modules.add(value)
        # Ordinary distlib/pip wrappers call a directly imported entry point
        # through sys.exit(...). No launcher name or pip version is consulted.
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "exit"
            and isinstance(function.value, ast.Name)
            and imports.get(function.value.id) == "sys"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and (module := referenced(node.args[0])) is not None
        ):
            console.add(module)
    for node in nodes:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == "__main__"
        ):
            for child in node.body:
                if (
                    isinstance(child, ast.Expr)
                    and isinstance(child.value, ast.Call)
                    and (module := referenced(child.value)) is not None
                ):
                    console.add(module)
    return _ScriptFacts(frozenset(modules), frozenset(console))


def _launcher_features(
    root: Path, base: tuple[ManifestEntry, ...], excluded: set[str], native_files: set[Path]
) -> dict[str, Literal["PACKAGE_MANAGER", "TKINTER_TCL_TK"]]:
    """Bounded static launcher dependencies; no source execution/installer probing.

    Module imports bind a wrapper to an inventoried excluded namespace. For GUI
    stdlib entry points, follow only imports within that entry point's own family,
    not a speculative whole-stdlib dependency graph. Unknown wrappers fail closed.
    """
    entries = {e.path: e for e in base}
    cache: dict[str, _ScriptFacts] = {}
    total = 0

    def facts(path: str) -> _ScriptFacts:
        nonlocal total
        if path not in cache:
            if len(cache) >= 128:
                raise ValueError("launcher inspection record bound")
            entry = entries[path]
            data = _bytes(root / path, 256 * 1024)
            total += len(data)
            if total > 2 * 1024**2 or hashlib.sha256(data).hexdigest() != entry.sha256:
                raise ValueError("launcher inspection content bound/binding")
            cache[path] = _script_facts(data, launcher=path.startswith("bin/"))
        return cache[path]

    site = "lib/python3.12/site-packages/"
    third_party = {
        e.path.removeprefix(site).split("/")[0].split(".")[0]
        for e in base
        if e.path.startswith(site)
        and (e.kind == "directory" or e.path.endswith((".py", ".pyc", ".so")))
    }

    def feature(module: str) -> Literal["PACKAGE_MANAGER", "TKINTER_TCL_TK"] | None:
        family = module.split(".")[0]
        if family in third_party or family == "ensurepip":
            return "PACKAGE_MANAGER"
        pending = [module]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            if len(seen) > 64:
                raise ValueError("launcher dependency bound")
            if current.split(".")[0] in third_party | {"ensurepip"}:
                return "PACKAGE_MANAGER"
            if current.split(".")[0] in {"tkinter", "_tkinter"}:
                return "TKINTER_TCL_TK"
            prefix = "lib/python3.12/" + current.replace(".", "/")
            for path in (prefix + ".py", prefix + "/__init__.py"):
                if path in excluded:
                    return "TKINTER_TCL_TK"
                if path in entries and entries[path].kind == "file":
                    pending.extend(
                        m
                        for m in sorted(facts(path).modules)
                        if m.split(".")[0]
                        in third_party | {family, "tkinter", "_tkinter", "ensurepip"}
                    )
        return None

    result: dict[str, Literal["PACKAGE_MANAGER", "TKINTER_TCL_TK"]] = {}
    for entry in base:
        if (
            not entry.path.startswith("bin/")
            or entry.kind != "file"
            or root / entry.path in native_files
        ):
            continue
        data = _bytes(root / entry.path, 256 * 1024)
        total += len(data)
        if total > 2 * 1024**2 or hashlib.sha256(data).hexdigest() != entry.sha256:
            raise ValueError("launcher content binding")
        if not data.startswith(b"#!"):
            continue
        if b"python" not in data.split(b"\n", 1)[0]:
            # Shell config tooling is retained; literal references into excluded
            # namespaces are not an alternative launcher/exposure escape hatch.
            if any(p.encode() in data for p in (site.rstrip("/"), "ensurepip", "tkinter")):
                raise ValueError("unsupported launcher into excluded namespace")
            continue
        script = facts(entry.path)
        dependencies = {m: f for m in sorted(script.modules) if (f := feature(m)) is not None}
        if dependencies:
            if (
                not set(dependencies) <= script.console_modules
                or len(set(dependencies.values())) != 1
            ):
                raise ValueError("selected launcher depends on excluded feature")
            result[entry.path] = next(iter(dependencies.values()))
    return result


def _project(
    root: Path,
    base: tuple[ManifestEntry, ...],
    metadata: dict[Path, _ELFMetadata],
    links: dict[Path, Path],
    native_files: set[Path],
) -> tuple[tuple[ManifestEntry, ...], tuple[ExcludedRuntimeEntry, ...]]:
    """Closed feature selector: import identity + native dependency ownership.

    No caller excludes paths. SONAME and exported PyInit identity establish the
    native feature. Libraries with any retained consumer stay selected and must
    pass normal eligibility. Unknown native material is never silently removed.
    """
    package_manager = {e.path for e in base if _package_manager_path(e.path)}
    native = {
        path
        for path, facts in metadata.items()
        if path.relative_to(root).as_posix() not in package_manager
        if facts.python_exports == ("PyInit__tkinter",)
        and path.parent == root / "lib/python3.12/lib-dynload"
        and path.name
        in {"_tkinter.cpython-312-x86_64-linux-gnu.so", "_tkinter.abi3.so", "_tkinter.so"}
    }

    def local(dependency: _ELFDependency) -> Path | None:
        target = (
            dependency.resolved
            if dependency.resolved is not None
            else root / "lib" / dependency.raw
        )
        target = links.get(target, target)
        facts = metadata.get(target)
        if facts is None:
            return None
        if dependency.kind is _DependencyKind.BARE_SONAME and facts.soname != dependency.raw:
            return None
        return target

    graph = {
        path: {target for d in facts.needed if (target := local(d)) is not None}
        for path, facts in metadata.items()
    }
    closure = set(native)
    pending = list(native)
    while pending:
        for target in graph[pending.pop()]:
            if target not in closure:
                closure.add(target)
                pending.append(target)
    # Importable non-Tk modules and the interpreter are never feature-private.
    exclusive = closure - {
        path
        for path in closure - native
        if metadata[path].python_exports or metadata[path].interpreter or not metadata[path].soname
    }
    while shared := {
        target
        for path, targets in graph.items()
        if path not in exclusive and path.relative_to(root).as_posix() not in package_manager
        for target in targets
        if target in exclusive
    }:
        exclusive -= shared
    if not native <= exclusive:
        raise ValueError("unsupported native feature has retained consumer")
    roles: dict[
        str,
        Literal[
            "NATIVE_MODULE",
            "PYTHON_PACKAGE",
            "EXCLUSIVE_LIBRARY",
            "FEATURE_DATA",
            "PROVISIONING_NAMESPACE",
            "STDLIB_BOOTSTRAP",
            "LAUNCHER",
        ],
    ] = {
        path.relative_to(root).as_posix(): "NATIVE_MODULE"
        if path in native
        else "EXCLUSIVE_LIBRARY"
        for path in exclusive
    }
    for alias, target in links.items():
        if target in exclusive:
            roles[alias.relative_to(root).as_posix()] = roles[target.relative_to(root).as_posix()]
    package = "lib/python3.12/tkinter"
    if any(e.path == package for e in base) and not any(
        e.path == package + "/__init__.py" and e.kind == "file" for e in base
    ):
        raise ValueError("unsupported optional Python package layout")
    if any(e.path == package + "/__init__.py" and e.kind == "file" for e in base):
        for entry in base:
            if entry.path == package or entry.path.startswith(package + "/"):
                roles[entry.path] = "PYTHON_PACKAGE"
    # Data selectors are tied to the proven private native SONAME/version AND
    # a feature sentinel, not a filename blacklist. Unknown data remains visible.
    for path in exclusive - native:
        soname = metadata[path].soname
        assert soname is not None
        match = re.fullmatch(
            r"lib(tcl|tk)([0-9]+\.[0-9]+)(?:tk[0-9]+\.[0-9]+)?\.so(?:\.[0-9.]+)?", soname
        )
        combined = re.fullmatch(r"libtcl[0-9]+tk([0-9]+\.[0-9]+)\.so(?:\.[0-9.]+)?", soname)
        if combined is not None:
            feature, version = "tk", combined.group(1)
        elif match is not None:
            feature, version = match.groups()
        else:
            continue
        directory = f"lib/{feature}{version}"
        sentinel = "init.tcl" if feature == "tcl" else "tk.tcl"
        if any(e.path == directory + "/" + sentinel and e.kind == "file" for e in base):
            for entry in base:
                if entry.path == directory or entry.path.startswith(directory + "/"):
                    roles[entry.path] = "FEATURE_DATA"
    features: dict[str, Literal["TKINTER_TCL_TK", "PACKAGE_MANAGER"]] = {
        path: "TKINTER_TCL_TK" for path in roles
    }
    for relative in package_manager:
        roles[relative] = (
            "PROVISIONING_NAMESPACE"
            if relative.startswith("lib/python3.12/site-packages")
            else "STDLIB_BOOTSTRAP"
        )
        features[relative] = "PACKAGE_MANAGER"
    launchers = _launcher_features(root, base, set(roles), native_files)
    for relative, feature in launchers.items():
        roles[relative], features[relative] = "LAUNCHER", feature
    # Only aliases of structurally identified unsupported launchers are excluded.
    # An arbitrary retained alias into excluded package content must reject.
    for alias, target in links.items():
        target_name = target.relative_to(root).as_posix()
        if target_name in launchers and alias.parent == root / "bin":
            relative = alias.relative_to(root).as_posix()
            roles[relative], features[relative] = "LAUNCHER", launchers[target_name]
    selected = tuple(e for e in base if e.path not in roles)
    excluded = tuple(
        ExcludedRuntimeEntry(entry=e, role=roles[e.path], feature=features[e.path])
        for e in base
        if e.path in roles
    )
    # Retained links must not reach excluded bytes through a different import path.
    for entry in selected:
        if (
            entry.kind == "symlink"
            and links[root / entry.path].relative_to(root).as_posix() in roles
        ):
            raise ValueError("projection symlink reaches unsupported feature")
    for required in (
        "bin/python3.12",
        "lib/python3.12/venv/__init__.py",
        "lib/python3.12/lib-dynload",
    ):
        if not any(e.path == required for e in selected):
            raise ValueError("required projection material removed")
    # Alternative import roots cannot reintroduce an excluded feature.
    for entry in selected:
        if (
            entry.path == "lib/python312.zip"
            or entry.path
            in {
                "lib/python3.12/tkinter.py",
                "lib/python3.12/tkinter.pyc",
                "lib/python3.12/ensurepip.py",
                "lib/python3.12/ensurepip.pyc",
            }
            or any(
                entry.path.startswith(prefix) and entry.path.endswith((".py", ".pyc"))
                for prefix in ("lib/python3.12/_tkinter", "lib/python3.12/lib-dynload/_tkinter")
            )
        ):
            raise ValueError("unsupported import-visible projection material")
    return selected, excluded


def inventory(
    configuration: PythonDistributionConfiguration, *, verify_pins: bool = True
) -> ProjectedDistributionManifest:
    """Full fresh rehash. Operator inventory mode does not authorize candidate execution."""
    try:
        configuration = PythonDistributionConfiguration.model_validate(configuration.model_dump())
        return _inventory(configuration, verify_pins=verify_pins)
    except ProvenanceFailure:
        raise
    except (OSError, ValueError, SyntaxError, UnicodeError, struct.error, RecursionError):
        raise ProvenanceFailure(
            PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "distribution_inventory"
        ) from None


def _inventory(
    configuration: PythonDistributionConfiguration, *, verify_pins: bool
) -> ProjectedDistributionManifest:
    root, support = configuration.distribution_root, configuration.system_library_root
    if not (root / "bin/python3.12").is_file():
        raise ProvenanceFailure(
            PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE, "interpreter_missing"
        )
    roots = (_parents(root), _parents(support))
    entries: list[ManifestEntry] = []
    dependencies: set[_ELFDependency] = set()
    inspected_dependencies: set[_ELFDependency] = set()
    elf_metadata: dict[Path, _ELFMetadata] = {}
    regular_files: set[Path] = set()
    elf_files: set[Path] = set()
    links: dict[Path, Path] = {}
    directories: set[Path] = {root, support}
    total = 0
    deadline = time.monotonic() + 60
    entry_count = 0

    def visit(path: Path, relative: str, *, library: bool = False) -> bytes | None:
        nonlocal total, entry_count
        if entry_count >= configuration.max_entries or time.monotonic() > deadline:
            raise ValueError("entry bound")
        entry_count += 1
        info = path.lstat()
        _trust(info, link=stat.S_ISLNK(info.st_mode))
        fields: EntryFields = dict(
            path=relative, mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid
        )
        if stat.S_ISDIR(info.st_mode):
            directories.add(path)
            entries.append(ManifestEntry(kind="directory", **fields))
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(child, relative + "/" + child.name)
            return None
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            resolved = Path(os.path.normpath(path.parent / target))
            boundary = support if library else root
            if (
                Path(target).is_absolute()
                or not resolved.is_relative_to(boundary)
                or resolved.is_symlink()
                or not resolved.is_file()
            ):
                raise ValueError("link must be one-hop internal regular file")
            _trust(resolved.lstat())
            entries.append(ManifestEntry(kind="symlink", target=target, **fields))
            links[path] = resolved
            return visit(resolved, relative + "#target", library=library) if library else None
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("special file")
        data = _bytes(path, min(64 * 1024**2, configuration.max_runtime_bytes - total))
        total += len(data)
        entries.append(
            ManifestEntry(
                kind="file", size=len(data), sha256=hashlib.sha256(data).hexdigest(), **fields
            )
        )
        regular_files.add(path)
        facts = _inspect_elf(data, owner=path, boundary=support if library else root)
        inspected_dependencies.update(facts.needed)
        if len(inspected_dependencies) > configuration.max_entries:
            raise ValueError("base dependency record bound")
        elf_metadata[path] = facts
        if library:
            _eligible(facts, owner=path, boundary=support)
            dependencies.update(facts.needed)
        if len(dependencies) > configuration.max_entries:
            raise ValueError("dependency record bound")
        if data.startswith(b"\x7fELF"):
            elf_files.add(path)
        return data

    # Only these trees are mounted. Every import-visible cache is runtime material,
    # including pyc/__pycache__; -B suppresses writes, not reads. include/share noise
    # is excluded AND absent from the identity namespace.
    for tree in ("bin", "lib"):
        if not (root / tree).is_dir() or (root / tree).is_symlink():
            raise ValueError("missing trusted runtime layout")
        visit(root / tree, tree)
    for required in ("lib/python3.12/venv/__init__.py", "lib/python3.12/lib-dynload"):
        if not any(
            e.path == required and e.kind == ("file" if required.endswith(".py") else "directory")
            for e in entries
        ):
            raise ValueError("required stdlib/venv layout missing")
    interpreter = next(e for e in entries if e.path == "bin/python3.12")
    if interpreter.kind != "file" or not interpreter.mode & 0o111 or interpreter.sha256 is None:
        raise ValueError("interpreter must be an executable regular file")
    interpreter_data = _bytes(root / "bin/python3.12", configuration.max_runtime_bytes)
    if (
        not interpreter_data.startswith(b"\x7fELF")
        or _elf(interpreter_data, owner=root / "bin/python3.12", boundary=root)[1] is None
    ):
        raise ValueError("interpreter ELF required")
    metadata_hash = None
    metadata_path = root / "PYTHON.json"
    if metadata_path.exists() or metadata_path.is_symlink():
        if metadata_path.lstat().st_size > configuration.max_metadata_bytes:
            raise ValueError("metadata bound")
        data = visit(metadata_path, "PYTHON.json")
        if data is None or len(data) > configuration.max_metadata_bytes:
            raise ValueError("metadata bound")
        metadata = json.loads(data)
        if not isinstance(metadata, dict) or len(metadata) > 256:
            raise ValueError("distribution metadata object required")
        metadata_hash = hashlib.sha256(data).hexdigest()
    distribution_entries = tuple(entries)
    for entry in distribution_entries:
        if entry.kind == "symlink":
            assert entry.target is not None
            target = os.path.relpath(
                os.path.normpath(root / entry.path / ".." / entry.target), root
            )
            if not any(e.path == target and e.kind == "file" for e in distribution_entries):
                raise ValueError("symlink target not inventoried/mounted")
    base_entries = tuple(sorted(distribution_entries, key=lambda e: e.path))
    distribution_entries, excluded_entries = _project(
        root, base_entries, elf_metadata, links, elf_files
    )
    selected_paths = {root / e.path for e in distribution_entries}
    regular_files &= selected_paths
    elf_files &= selected_paths
    directories = {p for p in directories if p in selected_paths or p in {root, support}}
    for path in sorted(selected_paths):
        if path in elf_metadata:
            _eligible(elf_metadata[path], owner=path, boundary=root)
            dependencies.update(elf_metadata[path].needed)
    if len(dependencies) > configuration.max_entries:
        raise ValueError("dependency record bound")
    entries.clear()
    loaded: set[str] = set()

    def path_target(dependency: _ELFDependency) -> Path:
        assert dependency.resolved is not None
        # Normalize only through inventoried real directories, never through a
        # symlink/file followed by '..' or an unmounted/untrusted path component.
        prefix = "$ORIGIN/" if dependency.raw.startswith("$ORIGIN/") else "${ORIGIN}/"
        current = dependency.owner.parent
        for component in dependency.raw.removeprefix(prefix).split("/")[:-1]:
            current = Path(os.path.normpath(current / component))
            if current not in directories:
                raise ValueError("dependency parent not inventoried directory")
        return links.get(dependency.resolved, dependency.resolved)

    def support_names() -> set[str]:
        names = {"ld-linux-x86-64.so.2"}
        for dependency in dependencies:
            if dependency.kind is _DependencyKind.BARE_SONAME:
                names.add(dependency.raw)
            else:
                assert dependency.resolved is not None
                target = path_target(dependency)
                if dependency.owner.is_relative_to(support):
                    # The existing namespace mounts support files at /support/<name>.
                    # Do not claim support for nested support layouts not mounted there.
                    if dependency.resolved.parent != support:
                        raise ValueError("unsupported support pathname layout")
                    names.add(dependency.resolved.name)
                else:
                    if target not in regular_files or target not in elf_files:
                        raise ValueError("dependency target not inventoried ELF")
        return names

    while pending := sorted(support_names() - loaded):
        name = pending[0]
        if len(loaded) >= 32:
            raise ValueError("library closure bound")
        visit(support / name, name, library=True)
        loaded.add(name)
    for dependency in dependencies:
        if dependency.kind is _DependencyKind.PATH_DEPENDENCY:
            assert dependency.resolved is not None
            resolved_target = path_target(dependency)
            if resolved_target not in regular_files or resolved_target not in elf_files:
                raise ValueError("dependency target not inventoried ELF")
    if roots != (_parents(root), _parents(support)):
        raise ValueError("substitution parent changed")
    selected_entries = tuple(sorted(distribution_entries, key=lambda e: e.path))
    support_entries = tuple(sorted(entries, key=lambda e: e.path))
    profile = PythonRuntimeProjectionProfile()
    projection_fields = dict(
        profile=profile,
        profile_sha256=canonical_digest(profile),
        base_manifest_sha256=digest_value(base_entries),
        selected_manifest_sha256=digest_value((selected_entries, support_entries)),
        excluded_manifest_sha256=digest_value(excluded_entries),
    )
    projection = PythonRuntimeProjectionIdentity(
        profile=profile,
        profile_sha256=canonical_digest(profile),
        base_manifest_sha256=digest_value(base_entries),
        selected_manifest_sha256=digest_value((selected_entries, support_entries)),
        excluded_manifest_sha256=digest_value(excluded_entries),
        projection_sha256=digest_value(projection_fields),
    )
    manifest = ProjectedDistributionManifest(
        root_binding_sha256=digest_value(roots),
        interpreter_sha256=interpreter.sha256,
        entries=selected_entries,
        excluded_entries=excluded_entries,
        support_entries=support_entries,
        metadata_sha256=metadata_hash,
        projection=projection,
    )
    # Certify representability BEFORE any fixed candidate probe, not merely hash
    # a selection that the native namespace would later be unable to expose.
    from .python_projection import mount_descriptor

    mount_descriptor(manifest)
    if verify_pins and (
        manifest.digest != configuration.expected_manifest_sha256
        or interpreter.sha256 != configuration.expected_interpreter_sha256
    ):
        raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "configured_digest")
    return manifest


def revalidate(
    configuration: PythonDistributionConfiguration, retained: PythonDistributionEvidence
) -> ProjectedDistributionManifest:
    try:
        manifest = inventory(configuration)
        if manifest.identity() != retained:
            raise ValueError("changed distribution")
        return manifest
    except (ProvenanceFailure, ValueError):
        raise ProvenanceFailure(
            PythonRuntimeReason.RUNTIME_REVALIDATION_FAILED, "current_distribution"
        ) from None
