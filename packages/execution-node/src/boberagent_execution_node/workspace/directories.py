"""Create owned workspace ancestors privately; never repair existing permissions."""

import os
import stat
from contextlib import suppress
from pathlib import Path


class WorkspaceDirectoryError(ValueError):
    """Bounded composition failure before any preparation constructor starts."""

    code = "WORKSPACE_STORAGE_UNTRUSTED"

    def __init__(self) -> None:
        super().__init__(self.code)


def prepare_owned_directory(path: Path) -> Path:
    """No-follow traversal with 0700 creation for every missing component.

    Existing ancestors follow storage's owner/non-writable trust rule (sticky
    shared parents are permitted). The configured leaf must be owned by this
    user and non-group/world-writable. No chmod or permission repair occurs.
    A restrictive umask may deny creation/access, but can never broaden modes.
    """
    path = path.absolute()
    if ".." in path.parts or path == Path("/"):
        raise WorkspaceDirectoryError()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:], start=1):
            with suppress(FileExistsError):
                os.mkdir(part, mode=0o700, dir_fd=fd)
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = following
            info = os.fstat(fd)
            sticky = bool(info.st_mode & stat.S_ISVTX)
            if (info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022) and not sticky:
                raise WorkspaceDirectoryError()
            if index == len(path.parts) - 1 and (
                info.st_uid != os.getuid() or info.st_mode & 0o022
            ):
                raise WorkspaceDirectoryError()
        return path
    except OSError as error:
        raise WorkspaceDirectoryError() from error
    finally:
        os.close(fd)
