#!/usr/bin/env python3
"""Stage a WIT package with the repository-local platform dependencies it imports."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_WIT = ROOT / "wit" / "platform"
DEFAULT_SOURCE = PLATFORM_WIT / "runtime"


def copy_wit_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*.wit")):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def stage(destination: Path, source: Path = DEFAULT_SOURCE) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"WIT package source does not exist: {source}")
    if destination == source or source in destination.parents:
        raise ValueError("WIT staging destination must not be inside the source package")

    if destination.exists():
        shutil.rmtree(destination)
    (destination / "deps").mkdir(parents=True)

    copy_wit_tree(source, destination)
    for package in sorted(path for path in PLATFORM_WIT.iterdir() if path.is_dir()):
        if package.name == "runtime" or package.resolve() == source:
            continue
        copy_wit_tree(package, destination / "deps" / package.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    arguments = parser.parse_args()
    stage(arguments.destination, arguments.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
