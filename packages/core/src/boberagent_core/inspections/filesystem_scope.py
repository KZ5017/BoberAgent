"""Narrow syntactic filesystem extent checks; never resolve paths or variables."""

import re
import shlex

from .semantic_models import FileEffectScope


def literal_scope(
    target: str | None, *, recursive: bool = False, wildcard: bool = False
) -> FileEffectScope:
    """Only a single literal basename is bounded; recursion remains unknown.

    BOUNDED describes syntax, not safe location, symlinks, runtime behavior, or
    policy permission. Broad deletion requires an explicit recursive root/root
    wildcard target. No variable propagation or filesystem inspection is done.
    """
    if target is None:
        return FileEffectScope.UNKNOWN
    if recursive and (
        target in {"/", "\\"}
        or re.fullmatch(r"[A-Za-z]:[\\/]", target)
        or (wildcard and (target in {"/*", "\\*"} or re.fullmatch(r"[A-Za-z]:[\\/][*]", target)))
    ):
        return FileEffectScope.BROAD
    if not recursive and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", target):
        return FileEffectScope.BOUNDED
    return FileEffectScope.UNKNOWN


def lexical_scope(
    tail: str, *, powershell: bool, deletion: bool, command_position: bool = True
) -> FileEffectScope:
    """Accept a deliberately tiny literal argument grammar, fail closed otherwise."""
    if not command_position:
        return FileEffectScope.UNKNOWN
    # Compound commands, substitution, expansions and redirections need analysis
    # we do not provide. Do not infer a variable's value from an earlier assignment.
    if any(char in tail for char in "$\x60;&|<>()\n"):
        return FileEffectScope.UNKNOWN
    try:
        if powershell:
            # Single/double quoted literal paths and ordinary whitespace tokens.
            tokens = re.findall(r"'[^']*'|\"[^\"]*\"|[^\s'\"\x60]+", tail)
            if sum(len(token) for token in tokens) != len(re.sub(r"\s", "", tail)):
                return FileEffectScope.UNKNOWN
            tokens = [token[1:-1] if token.startswith(("'", '"')) else token for token in tokens]
        else:
            tokens = shlex.split(tail, posix=True)
    except ValueError:
        return FileEffectScope.UNKNOWN
    flags = [token.lower() for token in tokens if token.startswith("-")]
    recursive = deletion and any(
        flag in {"--recursive", "-recurse"}
        or (not powershell and re.fullmatch(r"-[rRfFiIvVd]+", flag) and "r" in flag)
        for flag in flags
    )
    allowed = (
        {"-path", "-literalpath", "-recurse", "-force", "--"}
        if powershell
        else {"--", "--recursive", "--force"}
    )
    if any(
        flag not in allowed and not (not powershell and re.fullmatch(r"-[rRfFiIvVd]+", flag))
        for flag in flags
    ):
        return FileEffectScope.UNKNOWN
    targets = [token for token in tokens if not token.startswith("-")]
    if len(targets) != 1:
        return FileEffectScope.UNKNOWN
    wildcard = (
        "-literalpath" not in flags
        if powershell
        else not any(char in tail for char in ("'", '"', "\\"))
    )
    return literal_scope(targets[0], recursive=recursive, wildcard=wildcard)
