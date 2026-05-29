"""Rebuild v0.3 summary artifacts from an existing run directory.

Usage:
    python scripts/replay_artifacts.py runs/<task_id>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cs_mvp.artifacts import write_summary_artifacts


def replay(run_dir: Path) -> dict[str, str]:
    paths = write_summary_artifacts(Path(run_dir))
    return {name: str(path) for name, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    outputs = replay(args.run_dir)
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
