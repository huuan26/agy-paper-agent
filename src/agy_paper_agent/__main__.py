"""CLI entrypoint for exporting or verifying canonical JSON Schemas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agy_paper_agent.contracts import export_all_schemas


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or verify AGY Paper Co-Author schemas.")
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "schemas",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify schemas on disk match Pydantic contract models.",
    )
    args = parser.parse_args()
    export_all_schemas(args.schemas_dir, check_only=args.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
