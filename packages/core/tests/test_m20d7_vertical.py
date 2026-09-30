"""Each D7 vertical case uses persisted synthetic evidence and production Core pumps."""

from pathlib import Path

import pytest
from m20d7_vertical_harness import CASES, CaseName, run_case


@pytest.mark.parametrize("case", CASES)
def test_d7_synthetic_vertical_case(case: CaseName, tmp_path: Path) -> None:
    report = run_case(case, tmp_path / case)
    assert report.case == case
    assert report.mission_ref.startswith("mission-")
    assert report.planning_attempt_ref.startswith("planning-attempt-")
    assert report.authorization == "NONE"
    assert report.readiness == "NOT_ASSESSED"
    assert report.safe_output()["case"] == case
