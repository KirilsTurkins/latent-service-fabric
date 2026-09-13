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


def paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def stage(destination: Path, source: Path = DEFAULT_SOURCE) -> None:
    source = source.resolve()
    destination = destination.resolve()
    platform_wit = PLATFORM_WIT.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"WIT package source does not exist: {source}")
    for protected_name, protected_root in (
        ("source package", source),
        ("platform WIT dependency tree", platform_wit),
    ):
        if paths_overlap(destination, protected_root):
            raise ValueError(
                f"WIT staging destination must not overlap the {protected_name}: "
                f"{protected_root}"
            )

    if destination.exists():
        shutil.rmtree(destination)
    (destination / "deps").mkdir(parents=True)

    copy_wit_tree(source, destination)
    for package in sorted(path for path in platform_wit.iterdir() if path.is_dir()):
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
