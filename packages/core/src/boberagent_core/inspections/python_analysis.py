"""Bounded Python AST observations. No module import or expression evaluation."""

from __future__ import annotations

import ast
import sys
from typing import Literal

from .extraction import FileExtractor, ParserCoverageError, SemanticLimit, parameter_role, safe_name
from .filesystem_scope import literal_scope
from .semantic_models import (
    BehaviorKind,
    DependencyKind,
    DependencyObservation,
    EntrypointCandidate,
    ImportKind,
    ParameterCandidate,
    ParameterRole,
    Requirement,
    RequirementKind,
    RiskKind,
    SourceFact,
)


def _span(extractor: FileExtractor, node: ast.AST) -> tuple[int, int]:
    if (
        not isinstance(node, ast.expr | ast.stmt)
        or node.end_lineno is None
        or node.end_col_offset is None
    ):
        raise ValueError("AST node has no source location")
    return (
        extractor.decoded.ast_position(node.lineno, node.col_offset),
        extractor.decoded.ast_position(node.end_lineno, node.end_col_offset),
    )


def _constant(node: ast.AST | None) -> str | int | float | bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str | int | float | bool):
        return node.value
    return None


def analyze_python(extractor: FileExtractor) -> None:
    text = extractor.decoded.text
    try:
        tree = ast.parse(text, filename="<retained-source>")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ParserCoverageError("PYTHON_SYNTAX_ERROR") from error
    nodes: list[ast.AST] = []
    for node in ast.walk(tree):
        extractor.items.check_time()
        if len(nodes) >= extractor.items.limits.max_ast_nodes:
            raise SemanticLimit("AST_NODE_LIMIT")
        nodes.append(node)
    aliases: dict[str, str] = {}
    sockets: set[str] = set()
    parsers: set[str] = set()
    paths: set[str] = set()
    local_names = {
        path.rsplit("/", 1)[-1][:-3]
        for path in extractor.items.source.entries
        if path.endswith(".py")
    }

    def qualified(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            prefix = qualified(node.value)
            return f"{prefix}.{node.attr}" if prefix else ""
        if isinstance(node, ast.Call):
            return qualified(node.func) + "()"
        return ""

    # Imports are observed syntax, not proof of an installed package. No resolver.
    for node in nodes:
        if isinstance(node, ast.Import | ast.ImportFrom):
            start, end = _span(extractor, node)
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or "relative"]
            )
            for name in names:
                root = name.split(".", 1)[0]
                relative = isinstance(node, ast.ImportFrom) and node.level > 0
                kind = (
                    ImportKind.LOCAL_RELATIVE
                    if relative or root in local_names
                    else ImportKind.STDLIB_LOOKING
                    if root in sys.stdlib_module_names
                    else ImportKind.THIRD_PARTY_LOOKING
                    if root in {"requests", "aiohttp", "click"}
                    else ImportKind.UNKNOWN
                )
                if safe_name(name):
                    extractor.items.add(
                        DependencyObservation(
                            **extractor.evidence(start, end, "IMPORT_SYNTAX", name),
                            kind=DependencyKind.IMPORTED_MODULE,
                            name=name,
                            import_kind=kind,
                        )
                    )
            for alias in node.names:
                if isinstance(node, ast.Import):
                    aliases[alias.asname or alias.name.split(".", 1)[0]] = (
                        alias.name if alias.asname else alias.name.split(".", 1)[0]
                    )
                elif node.level == 0:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    for node in nodes:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            name = qualified(node.value.func)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if name == "socket.socket":
                        sockets.add(target.id)
                    if name == "argparse.ArgumentParser":
                        parsers.add(target.id)
                    if name == "pathlib.Path":
                        paths.add(target.id)

    if tree.body:
        first = tree.body[0]
        start, end = _span(extractor, first)
        # Cite the first syntactic token, not an arbitrary entire source file.
        end = min(end, start + 1)
        extractor.items.add(
            SourceFact(**extractor.evidence(start, end, "PYTHON_AST_PARSED"), kind="PYTHON_SOURCE")
        )
    if text.startswith("#!"):
        end = text.find("\n") if "\n" in text else len(text)
        extractor.items.add(
            SourceFact(**extractor.evidence(0, end, "SHEBANG_PRESENT"), kind="SHEBANG")
        )
    main_guards: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            start, _ = _span(extractor, node)
            end = text.find("\n", start)
            end = len(text) if end < 0 else end
            fact_kind: Literal["CLASS", "ASYNC_FUNCTION", "FUNCTION"] = (
                "CLASS"
                if isinstance(node, ast.ClassDef)
                else "ASYNC_FUNCTION"
                if isinstance(node, ast.AsyncFunctionDef)
                else "FUNCTION"
            )
            if safe_name(node.name):
                extractor.items.add(
                    SourceFact(
                        **extractor.evidence(start, end, "TOP_LEVEL_DEFINITION", fact_kind),
                        kind=fact_kind,
                        name=node.name,
                    )
                )
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and _constant(node.test.comparators[0]) == "__main__"
        ):
            start, end = _span(extractor, node.test)
            extractor.items.add(
                SourceFact(**extractor.evidence(start, end, "MAIN_GUARD_SYNTAX"), kind="MAIN_GUARD")
            )
            main_guards.append((start, end))

    for node in nodes:
        extractor.items.check_time()
        if isinstance(node, ast.Attribute) and qualified(node) in {"os.environ", "sys.argv"}:
            start, end = _span(extractor, node)
            if qualified(node) == "sys.argv":
                extractor.items.add(
                    SourceFact(**extractor.evidence(start, end, "ARGV_REFERENCE"), kind="ARGV")
                )
                extractor.unknown(start, end, "DYNAMIC_PARAMETER_VALUES")
            else:
                extractor.indicator(start, end, BehaviorKind.ENVIRONMENT_ACCESS)
                extractor.items.add(
                    Requirement(
                        **extractor.evidence(start, end, "ENVIRONMENT_REFERENCE"),
                        kind=RequirementKind.ENVIRONMENT,
                        name="environment",
                    )
                )
        if not isinstance(node, ast.Call):
            continue
        start, end = _span(extractor, node)
        fn_start, fn_end = _span(extractor, node.func)
        name = qualified(node.func)
        if name == "argparse.ArgumentParser":
            extractor.items.add(
                SourceFact(
                    **extractor.evidence(fn_start, fn_end, "ARGPARSE_CONSTRUCTOR"), kind="ARGPARSE"
                )
            )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in parsers
        ):
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            flags = [_constant(arg) for arg in node.args]
            if not flags or any(not isinstance(flag, str) for flag in flags):
                extractor.unknown(fn_start, fn_end, "DYNAMIC_PARAMETER_DECLARATION")
            else:
                for flag in flags:
                    assert isinstance(flag, str)
                    if not safe_name(flag.lstrip("-")) or len(flag) > 128:
                        extractor.unknown(fn_start, fn_end, "UNSUPPORTED_PARAMETER_NAME")
                        continue
                    role = parameter_role(flag)
                    required_value = _constant(keywords.get("required"))
                    required = required_value if isinstance(required_value, bool) else None
                    if not flag.startswith("-"):
                        nargs = _constant(keywords.get("nargs"))
                        required = (
                            nargs not in {"?", "*"}
                            if "nargs" not in keywords or nargs is not None
                            else None
                        )
                    default = _constant(keywords.get("default"))
                    # String defaults may be credentials/targets: preserve only a redaction flag.
                    extractor.items.add(
                        ParameterCandidate(
                            **extractor.evidence(start, end, "ARGPARSE_LITERAL_PARAMETER", flag),
                            name=flag,
                            role=role,
                            required=required,
                            default_literal=default
                            if isinstance(default, int | float | bool)
                            and role is not ParameterRole.CREDENTIAL
                            else None,
                            default_redacted=isinstance(default, str)
                            or (role is ParameterRole.CREDENTIAL and default is not None),
                        )
                    )
                    if role is ParameterRole.UNKNOWN:
                        extractor.items.gap(
                            extractor.path, extractor.origin, "AMBIGUOUS_PARAMETER_ROLE"
                        )
                    if role is ParameterRole.CREDENTIAL:
                        extractor.items.add(
                            Requirement(
                                **extractor.evidence(start, end, "CREDENTIAL_PARAMETER"),
                                kind=RequirementKind.CREDENTIAL,
                                name="credential",
                            )
                        )
        behavior: BehaviorKind | None = None
        file_target: ast.AST | None = node.args[0] if node.args else None
        recursive = False
        if name.startswith(("requests.", "aiohttp.", "urllib.request.", "http.client.")):
            behavior = BehaviorKind.NETWORK_CONNECT
        elif name in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
            behavior = BehaviorKind.NETWORK_RESOLUTION
        elif name in {"socket.socket().connect", "socket.create_connection"} or (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in sockets
            and node.func.attr == "connect"
        ):
            behavior = BehaviorKind.NETWORK_CONNECT
        elif name in {"socket.socket().bind", "socket.socket().listen"} or (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in sockets
            and node.func.attr in {"bind", "listen"}
        ):
            behavior = BehaviorKind.NETWORK_BIND_LISTEN
        elif name.startswith("subprocess."):
            behavior = BehaviorKind.SUBPROCESS_EXECUTION
        elif name in {"os.system", "os.popen"}:
            behavior = BehaviorKind.SHELL_EXECUTION
        elif name == "os.getenv":
            behavior = BehaviorKind.ENVIRONMENT_ACCESS
            extractor.items.add(
                Requirement(
                    **extractor.evidence(fn_start, fn_end, "ENVIRONMENT_REFERENCE"),
                    kind=RequirementKind.ENVIRONMENT,
                    name="environment",
                )
            )
        elif name in {"os.getuid", "os.geteuid"}:
            behavior = BehaviorKind.PRIVILEGE_CHECK
        elif name in {"os.remove", "os.unlink", "shutil.rmtree"}:
            behavior = BehaviorKind.FILE_DELETE
            recursive = name == "shutil.rmtree"
        elif name == "open":
            mode = (
                _constant(node.args[1])
                if len(node.args) > 1
                else _constant(next((kw.value for kw in node.keywords if kw.arg == "mode"), None))
            )
            if isinstance(mode, str) and any(char in mode for char in "wax+"):
                behavior = BehaviorKind.FILE_WRITE
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"write_text", "write_bytes", "unlink"}
            and (
                name.startswith("pathlib.Path().")
                or (isinstance(node.func.value, ast.Name) and node.func.value.id in paths)
            )
        ):
            behavior = (
                BehaviorKind.FILE_DELETE if node.func.attr == "unlink" else BehaviorKind.FILE_WRITE
            )
            receiver = node.func.value
            file_target = (
                receiver.args[0] if isinstance(receiver, ast.Call) and receiver.args else None
            )
        if behavior in {BehaviorKind.FILE_WRITE, BehaviorKind.FILE_DELETE}:
            file_target_value = _constant(file_target)
            extractor.filesystem_effect(
                start,
                end,
                behavior,
                literal_scope(
                    file_target_value if isinstance(file_target_value, str) else None,
                    recursive=recursive,
                ),
            )
        elif behavior is not None:
            extractor.indicator(fn_start, fn_end, behavior)
        if name in {"exec", "eval", "os.system", "os.popen"}:
            extractor.indicator(fn_start, fn_end, RiskKind.ARBITRARY_COMMAND_EXECUTION)
        if name.startswith("subprocess.") and any(
            kw.arg == "shell" and _constant(kw.value) is True for kw in node.keywords
        ):
            extractor.indicator(start, end, RiskKind.ARBITRARY_COMMAND_EXECUTION)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"connect", "bind", "listen"}
            and behavior is None
        ):
            extractor.unknown(fn_start, fn_end, "UNRESOLVED_NETWORK_RECEIVER")
    parameter_ids = tuple(
        item.item_id for item in extractor.items.parameters if item.source_path == extractor.path
    )
    for start, end in main_guards:
        extractor.items.add(
            EntrypointCandidate(
                **extractor.evidence(start, end, "MAIN_GUARD_ENTRY_CANDIDATE"),
                runtime="python",
                invocation_style="SCRIPT_MAIN_GUARD",
                parameter_candidate_refs=parameter_ids,
            )
        )
    if not main_guards:
        extractor.items.gap(extractor.path, extractor.origin, "ENTRYPOINT_UNRESOLVED")
