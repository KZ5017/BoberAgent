"""Deliberately partial shell/PowerShell lexical observations, not interpreters."""

import re

from .extraction import FileExtractor
from .filesystem_scope import lexical_scope
from .semantic_models import (
    BehaviorKind,
    DependencyKind,
    DependencyObservation,
    EntrypointCandidate,
    RiskKind,
    SourceFact,
)


def _mask_comments(text: str, *, powershell: bool) -> str:
    result = list(text)
    quote = ""
    comment = False
    block = False
    escaped = False
    for index, char in enumerate(text):
        if block:
            if text[index - 1 : index + 1] == "#>":
                block = False
            if char != "\n":
                result[index] = " "
            continue
        if powershell and not quote and text[index : index + 2] == "<#":
            block = True
            result[index] = " "
            continue
        if comment:
            if char == "\n":
                comment = False
            else:
                result[index] = " "
            continue
        if escaped:
            escaped = False
            continue
        if char == ("`" if powershell else "\\"):
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            comment = True
            result[index] = " "
    return "".join(result)


def _mask_literals(text: str, *, powershell: bool) -> str:
    """Suppress ordinary quoted words; parameter-use scanning has its own view."""
    result = list(text)
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if char != "\n":
                result[index] = " "
            if escaped:
                escaped = False
            elif char == ("`" if powershell else "\\"):
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            result[index] = " "
    return "".join(result)


def analyze_lexical(extractor: FileExtractor, *, powershell: bool) -> None:
    text = extractor.decoded.text
    masked = _mask_comments(text, powershell=powershell)
    extractor.items.gap(extractor.path, extractor.origin, "LEXICAL_ONLY_NO_COMPLETE_SEMANTICS")
    if text.startswith("#!"):
        end = text.find("\n") if "\n" in text else len(text)
        extractor.items.add(
            SourceFact(**extractor.evidence(0, end, "SHEBANG_PRESENT"), kind="SHEBANG")
        )
        extractor.items.add(
            EntrypointCandidate(
                **extractor.evidence(0, end, "SHEBANG_SCRIPT_CANDIDATE"),
                runtime="powershell" if powershell else "shell",
                invocation_style="SCRIPT_LEXICAL",
            )
        )
    if powershell:
        block = re.search(r"\bparam\s*\(([^()]*)\)", masked, re.IGNORECASE)
        if block:
            for match in re.finditer(
                r"(?:^|,)\s*(?:\[[A-Za-z0-9_.]+\]\s*)?(\$[A-Za-z_][A-Za-z0-9_]{0,126})",
                block.group(1),
            ):
                start = block.start(1) + match.start(1)
                end = block.start(1) + match.end(1)
                extractor.parameter(start, end, match.group(1))
        elif re.search(r"\bparam\s*\(", masked, re.IGNORECASE):
            extractor.items.gap(extractor.path, extractor.origin, "AMBIGUOUS_PARAM_BLOCK")
        patterns: tuple[tuple[str, BehaviorKind | RiskKind], ...] = (
            (
                r"\b(?:Invoke-WebRequest|Invoke-RestMethod|System\.Net\.[\w.]+|TcpClient)\b",
                BehaviorKind.NETWORK_CONNECT,
            ),
            (r"\bTcpListener\b", BehaviorKind.NETWORK_BIND_LISTEN),
            (r"\bStart-Process\b", BehaviorKind.SUBPROCESS_EXECUTION),
            (r"\b(?:Invoke-Expression|IEX)\b", RiskKind.ARBITRARY_COMMAND_EXECUTION),
            (r"\bRemove-Item\b", BehaviorKind.FILE_DELETE),
            (r"\b(?:Set-Content|Add-Content|Out-File)\b", BehaviorKind.FILE_WRITE),
            (r"\b(?:Get|Set|New|Remove)-ItemProperty\b", BehaviorKind.REGISTRY_ACCESS),
            (r"\b(?:Start|Stop|Restart|Set)-Service\b", BehaviorKind.SERVICE_CONTROL),
            (r"\b(?:IsInRole|WindowsBuiltInRole\.Administrator)\b", BehaviorKind.PRIVILEGE_CHECK),
        )
        for match in re.finditer(r"\$args\b", masked, re.IGNORECASE):
            extractor.unknown(match.start(), match.end(), "DYNAMIC_PARAMETER_VALUES")
    else:
        for match in re.finditer(r"\$[1-9][0-9]*|\$[@*]", masked):
            extractor.parameter(match.start(), match.end(), match.group())
        for match in re.finditer(r"\bgetopts\s+['\"]([A-Za-z:]+)['\"]", masked):
            for index, char in enumerate(match.group(1)):
                if char != ":":
                    start = match.start(1) + index
                    extractor.parameter(start, start + 1, "-" + char)
        patterns = (
            (r"\b(?:curl|wget)\b", BehaviorKind.NETWORK_CONNECT),
            (r"\b(?:nc|netcat)\b", BehaviorKind.NETWORK_CONNECT),
            (r"\b(?:bash|sh)\b", BehaviorKind.SHELL_EXECUTION),
            (r"\bpython[0-9.]*\b", BehaviorKind.SUBPROCESS_EXECUTION),
            (r"\brm\b", BehaviorKind.FILE_DELETE),
            (r"\b(?:mv|cp)\b", BehaviorKind.FILE_WRITE),
            (r"\b(?:chmod|chown|sudo|su)\b", RiskKind.PRIVILEGED_EXECUTION),
            (r"\b(?:systemctl|service)\b", BehaviorKind.SERVICE_CONTROL),
            (r"(?<![<>])>>?(?![>&])", BehaviorKind.FILE_WRITE),
        )
    token_text = _mask_literals(masked, powershell=powershell)
    for pattern, kind in patterns:
        for match in re.finditer(pattern, token_text, re.IGNORECASE if powershell else 0):
            if isinstance(kind, BehaviorKind) and kind in {
                BehaviorKind.FILE_DELETE,
                BehaviorKind.FILE_WRITE,
            }:
                end = masked.find("\n", match.end())
                end = len(masked) if end < 0 else end
                extractor.filesystem_effect(
                    match.start(),
                    end,
                    kind,
                    lexical_scope(
                        masked[match.end() : end],
                        powershell=powershell,
                        command_position=(
                            not token_text[
                                token_text.rfind("\n", 0, match.start()) + 1 : match.start()
                            ].strip()
                            or match.group() in {">", ">>"}
                        ),
                        deletion=kind is BehaviorKind.FILE_DELETE,
                    ),
                )
            else:
                extractor.indicator(match.start(), match.end(), kind)
            if not powershell and re.fullmatch(
                r"curl|wget|nc|netcat|bash|sh|python[0-9.]*|rm|mv|cp|chmod|chown|sudo|su|systemctl|service",
                match.group(),
            ):
                extractor.items.add(
                    DependencyObservation(
                        **extractor.evidence(
                            match.start(), match.end(), "LEXICAL_TOOL_TOKEN", match.group()
                        ),
                        kind=DependencyKind.INVOKED_SYSTEM_TOOL,
                        name=match.group(),
                    )
                )
