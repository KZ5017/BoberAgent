"""Exact fixed E5-E profile/accounting; historical @1 is not current authority."""

import ast
from pathlib import Path

import pytest
from boberagent_execution_node.preparation import _environment_helper
from boberagent_execution_node.preparation.environment_limits import (
    EXPORT_LIMIT,
    FILE_LIMIT,
    MANIFEST_FRAME_LIMIT,
    MEMORY_LIMIT,
    SCRATCH_LIMIT,
    WRITE_LIMIT,
)
from boberagent_execution_node.preparation.python_environment import (
    ConstructionSummary,
    _construction_reservations,
)
from boberagent_execution_node.preparation.resource_models import BudgetCategory
from boberagent_execution_node.preparation.runtime_confinement_models import (
    EnvironmentLimits,
    LegacyEnvironmentLimits,
    ProbeLimits,
)
from pydantic import ValidationError


def test_standalone_helper_provider_and_fixed_caps_cannot_drift() -> None:
    assert _environment_helper.WRITE_CAP == WRITE_LIMIT == 128 * 1024**2
    assert _environment_helper.EXPORT_CAP == EXPORT_LIMIT == WRITE_LIMIT + MANIFEST_FRAME_LIMIT
    assert _environment_helper.ENTRY_CAP == FILE_LIMIT == 256
    limits = EnvironmentLimits()
    assert limits.profile == "m20-e5-empty-environment-limits@2"
    assert limits.scratch_bytes == SCRATCH_LIMIT == WRITE_LIMIT + FILE_LIMIT * 65536
    assert limits.memory_bytes == MEMORY_LIMIT == 512 * 1024**2
    assert limits.scratch_inodes == FILE_LIMIT
    # Isolated helper must not import a provider module to obtain its literals.
    tree = ast.parse(Path(_environment_helper.__file__).read_text())
    assert all(not isinstance(node, ast.ImportFrom) or node.level == 0 for node in ast.walk(tree))
    with pytest.raises(ValidationError):
        EnvironmentLimits(scratch_bytes=WRITE_LIMIT)  # type: ignore[arg-type]


def test_reservations_cover_all_fixed_buffers_and_maximum_accepted_writes() -> None:
    reservation = _construction_reservations()
    # Capped tmpfs + anonymous export + Node export + published environment,
    # original control scratch allowance and the two 4 KiB tmp/home mounts.
    assert reservation[BudgetCategory.TEMPORARY_BYTES] == (
        SCRATCH_LIMIT + 2 * EXPORT_LIMIT + WRITE_LIMIT + 16 * 1024**2 + 8192
    )
    assert reservation[BudgetCategory.MEMORY_BYTES] == MEMORY_LIMIT + 8 * 1024**2
    # Logical payload can reach WRITE_LIMIT; framing is four bytes + bounded JSON.
    assert EXPORT_LIMIT == WRITE_LIMIT + 4 + 65532
    summary = ConstructionSummary(
        written_bytes=WRITE_LIMIT, created_entries=FILE_LIMIT, export_bytes=EXPORT_LIMIT
    )
    max_actual = 2 * summary.written_bytes + 2 * summary.export_bytes
    control_writes = 13 * (2 * 1024**2 + 8192) + 32 * 1024**2
    assert reservation[BudgetCategory.WRITE_BYTES] == control_writes + max_actual + 65536
    assert reservation[BudgetCategory.FILE_COUNT] >= 2 * FILE_LIMIT
    with pytest.raises(ValidationError):
        ConstructionSummary(written_bytes=WRITE_LIMIT + 1, created_entries=1, export_bytes=4)
    with pytest.raises(ValidationError):
        ConstructionSummary(written_bytes=1, created_entries=1, export_bytes=EXPORT_LIMIT + 1)


def test_old_limit_records_keep_their_exact_original_profile() -> None:
    legacy = LegacyEnvironmentLimits()
    assert legacy.profile == "m20-e5-empty-environment-limits@1"
    assert legacy.scratch_bytes == 32 * 1024**2
    assert legacy.memory_bytes == 128 * 1024**2
    assert LegacyEnvironmentLimits.model_validate_json(legacy.model_dump_json()) == legacy
    with pytest.raises(ValidationError):
        EnvironmentLimits.model_validate_json(legacy.model_dump_json())
    assert ProbeLimits().memory_bytes == 64 * 1024**2
    assert ProbeLimits().scratch_bytes == 1024**2
