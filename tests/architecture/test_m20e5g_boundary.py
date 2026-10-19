"""A portable fake proof must not become G's configured production-positive proof."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_g_positive_has_no_provider_substitution_or_private_work_shortcut() -> None:
    source = (ROOT / "packages/core/tests/test_m20e5g_vertical.py").read_text()
    tree = ast.parse(source)
    assert "type(case.node.runtime_confinement) is LinuxRuntimeConfinementBackend" in source
    assert "BOBERAGENT_E5G_CONFIGURATION" in source
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not {item.name for item in node.names} & {
                "FakeEnvironmentBackend",
                "FakeIdentityBackend",
                "GenerationBackend",
                "ControlledConfinement",
                "PythonEnvironmentProvider",
                "NodePythonRuntimeService",
            }
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                "create_empty_environment",
                "run_environment_create",
                "run_environment_verify",
                "reserve_budget",
                "mark_building",
                "settle_budget",
                "complete",
                "_run",
            }
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    assert target.attr not in {
                        "python_runtime_service",
                        "runtime_confinement",
                        "_boot",
                    }
