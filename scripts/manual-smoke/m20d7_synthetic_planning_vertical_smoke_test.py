"""Manual-only, offline synthetic D3→D6 acceptance; no execution or network."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# Reuse the migration-backed synthetic fixture and the same assertions as pytest.
_TEST_FIXTURES = Path(__file__).resolve().parents[2] / "packages/core/tests"
sys.path.insert(0, str(_TEST_FIXTURES))

from m20d7_vertical_harness import run_all  # noqa: E402


def _run(root: Path) -> None:
    reports = run_all(root)
    print(json.dumps([report.safe_output() for report in reports], indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-directory",
        type=Path,
        help="New empty directory to retain six isolated Core SQLite databases and fixture Artifacts.",
    )
    args = parser.parse_args()
    root: Path | None = args.runtime_directory
    if root is None:
        with TemporaryDirectory(prefix="boberagent-m20d7-") as temporary:
            _run(Path(temporary))
        return
    if root.exists() and any(root.iterdir()):
        parser.error("--runtime-directory must be new or empty")
    root.mkdir(parents=True, exist_ok=True)
    _run(root)


if __name__ == "__main__":
    main()
