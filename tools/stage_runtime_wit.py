#!/usr/bin/env python3
"""Stage the platform runtime WIT package with all repository-local dependencies."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_WIT = ROOT / "wit" / "platform"


def copy_wit_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*.wit")):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def stage(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    (destination / "deps").mkdir(parents=True)

    copy_wit_tree(PLATFORM_WIT / "runtime", destination)
    for package in sorted(path for path in PLATFORM_WIT.iterdir() if path.is_dir()):
        if package.name == "runtime":
            continue
        copy_wit_tree(package, destination / "deps" / package.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    stage(arguments.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
