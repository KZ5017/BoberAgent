"""Fixed provider-owned program mounted read-only at /trusted/environment.py.

Executed ONLY by the native closed E5-E operation, never on acquired input. The
stdlib EnvBuilder owns layout/configuration; all its file writes are intercepted
before issue. An audit gate rejects unaccounted writes, process/network calls and
package bootstrap. This is NOT a hostile-Python sandbox or a public code API.
"""

import hashlib
import io
import json
import os
import stat
import struct
import sys
import sysconfig
import venv
from typing import BinaryIO, cast

PREFIX = "/work/venv"
WRITE_CAP = 32 * 1024**2
ENTRY_CAP = 256
EXPORT_CAP = WRITE_CAP + 65536
written_bytes = 0
created_entries = 0
issuing = False
original_open = open


def owned_path(value: object) -> str:
    if not isinstance(value, (str, bytes, os.PathLike)):
        raise ValueError("closed path required")
    path = os.fsdecode(value)
    if (
        not path.startswith(PREFIX + "/")
        or any(part in {".", "..", ""} for part in path.split("/")[1:])
        or len(path) > 128
    ):
        raise ValueError("environment write boundary")
    return path


def charge(data: bytes) -> None:
    global written_bytes
    if written_bytes + len(data) > WRITE_CAP:
        raise ValueError("construction write budget")
    written_bytes += len(data)


def audit(event: str, args: tuple[object, ...]) -> None:
    global created_entries
    if event in {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.fork",
        "os.forkpty",
    } or (event.startswith("socket.")):
        raise ValueError("non-action boundary")
    if (
        event == "import"
        and isinstance(args[0], str)
        and args[0].split(".")[0]
        in {"pip", "ensurepip", "tkinter", "sitecustomize", "usercustomize"}
    ):
        raise ValueError("excluded import")
    if event == "open":
        flags = args[2]
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            owned_path(args[0])
            if not issuing:
                raise ValueError("unaccounted write")
    if event in {"os.mkdir", "os.symlink"}:
        path = owned_path(args[1] if event == "os.symlink" else args[0])
        if event == "os.symlink" and (path != PREFIX + "/lib64" or args[0] != "lib"):
            raise ValueError("unexpected link")
        if created_entries >= ENTRY_CAP:
            raise ValueError("construction inode budget")
        created_entries += 1
    if event == "os.chmod":
        owned_path(args[0])
    if event in {"os.remove", "os.rmdir", "os.rename", "os.truncate", "os.link"}:
        raise ValueError("unexpected mutation")


class AccountedFile(io.BytesIO):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def write(self, data: bytes | bytearray) -> int:  # type: ignore[override]
        charge(bytes(data))
        return super().write(data)

    def close(self) -> None:
        global issuing, created_entries
        if self.closed:
            return
        if created_entries >= ENTRY_CAP or os.path.lexists(self.path):
            raise ValueError("fresh exclusive file required")
        created_entries += 1
        data = self.getvalue()
        issuing = True
        try:
            with original_open(self.path, "xb") as stream:
                stream.write(data)
        finally:
            issuing = False
        super().close()


def accounted_open(
    file: str, mode: str = "r", *, encoding: str | None = None
) -> BinaryIO | io.TextIOWrapper:
    if mode not in {"w", "wb"}:
        # EnvBuilder uses reads only for templates. No update/append mode exists.
        if mode != "rb":
            raise ValueError("unsupported stdlib file operation")
        return original_open(file, "rb")
    binary = AccountedFile(owned_path(file))
    return binary if mode == "wb" else io.TextIOWrapper(binary, encoding=encoding or "utf-8")


def copy_file(src: str, dst: str, *, follow_symlinks: bool = True) -> str:
    if not follow_symlinks:
        raise ValueError("copy semantics")
    with original_open(src, "rb") as source:
        data = source.read(WRITE_CAP + 1)
    with cast(BinaryIO, accounted_open(dst, "wb")) as destination:
        destination.write(data)
    return dst


def environment_manifest() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for parent, directories, files in os.walk(PREFIX, followlinks=False):
        for name in sorted((*directories, *files)):
            path = os.path.join(parent, name)
            info = os.lstat(path)
            relative = os.path.relpath(path, PREFIX)
            entry: dict[str, object] = {
                "path": relative,
                "mode": stat.S_IMODE(info.st_mode),
                "size": 0,
                "sha256": None,
                "target": None,
            }
            if stat.S_ISREG(info.st_mode):
                with original_open(path, "rb") as stream:
                    data = stream.read(WRITE_CAP + 1)
                if len(data) != info.st_size or len(data) > WRITE_CAP:
                    raise ValueError("file bound")
                entry.update(kind="file", size=len(data), sha256=hashlib.sha256(data).hexdigest())
            elif stat.S_ISDIR(info.st_mode):
                entry["kind"] = "directory"
            elif stat.S_ISLNK(info.st_mode) and relative == "lib64" and os.readlink(path) == "lib":
                entry.update(kind="symlink", target="lib")
            else:
                raise ValueError("unexpected filesystem object")
            entries.append(entry)
    return {
        "schema_version": "m20-e5-empty-environment@1",
        "entries": sorted(entries, key=lambda entry: str(entry["path"])),
        "written_bytes": written_bytes,
        "created_entries": created_entries,
    }


def create() -> None:
    if sys.prefix != "/runtime" or not sys.flags.no_site or os.listdir(PREFIX):
        raise ValueError("fresh isolated base required")
    import shutil

    # Localized stdlib interception: tested against the admitted, hash-pinned
    # CPython 3.12 implementation. Unknown future writes fail the audit gate.
    venv.__dict__["open"] = accounted_open
    shutil.__dict__["copyfile"] = copy_file
    sys.addaudithook(audit)
    builder = venv.EnvBuilder(
        system_site_packages=False,
        with_pip=False,
        symlinks=False,
        upgrade=False,
        upgrade_deps=False,
    )
    builder.create(PREFIX)
    manifest = environment_manifest()
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > 65532 or created_entries != len(cast(list[object], manifest["entries"])):
        raise ValueError("inventory bound")
    exported = 0

    def export_write(data: bytes) -> None:
        nonlocal exported
        if exported + len(data) > EXPORT_CAP:
            raise ValueError("export bound")
        exported += len(data)
        view = memoryview(data)
        while view:
            amount = os.write(3, view)
            if amount <= 0:
                raise ValueError("export write failed")
            view = view[amount:]

    export_write(struct.pack("!I", len(encoded)))
    export_write(encoded)
    for entry in cast(list[dict[str, object]], manifest["entries"]):
        if entry["kind"] == "file":
            with original_open(PREFIX + "/" + str(entry["path"]), "rb") as source:
                while data := source.read(65536):
                    export_write(data)
    size = os.lseek(3, 0, os.SEEK_CUR)
    if size > EXPORT_CAP:
        raise ValueError("export bound")
    print(
        json.dumps(
            dict(written_bytes=written_bytes, created_entries=created_entries, export_bytes=size),
            sort_keys=True,
        )
    )


def verify() -> None:
    import site

    print(
        json.dumps(
            dict(
                implementation=sys.implementation.name,
                version=".".join(map(str, sys.version_info[:3])),
                platform=sys.platform,
                architecture=os.uname().machine,
                cache_tag=sys.implementation.cache_tag,
                soabi=sysconfig.get_config_var("SOABI"),
                prefix=sys.prefix,
                base_prefix=sys.base_prefix,
                executable=sys.executable,
                paths=sys.path,
                isolated=sys.flags.isolated,
                no_site=sys.flags.no_site,
                no_bytecode=sys.dont_write_bytecode,
                user_site=site.ENABLE_USER_SITE,
                written_bytes=0,
                created_entries=0,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main() -> int:
    try:
        if sys.version_info[:2] != (3, 12) or sys.platform != "linux" or not sys.flags.isolated:
            raise ValueError("fixed CPython profile required")
        if sys.argv == ["/trusted/environment.py", "create"]:
            create()
        elif sys.argv == ["/trusted/environment.py", "verify"]:
            verify()
        else:
            raise ValueError("closed operation required")
        return 0
    except Exception:
        # No traceback/input/path contents leave the trusted child.
        print("EMPTY_ENVIRONMENT_OPERATION_FAILED", file=sys.stderr)
        return 95


if __name__ == "__main__":
    raise SystemExit(main())
