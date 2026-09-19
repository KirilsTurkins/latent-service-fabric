#!/usr/bin/env python3
"""Stage debug-stripped copies for the frozen Phase 2 binary identity bound."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys


NAMES = ("latent", "latentd")


def prepare(build: Path, destination: Path, maximum: int) -> dict[str, int]:
    """Never modify Cargo outputs or reuse an existing fixture directory."""
    if not build.is_absolute() or not destination.is_absolute() or maximum <= 0:
        raise ValueError("resource-binary-arguments")
    sources = [build / name for name in NAMES]
    for source in sources:
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or not os.access(source, os.X_OK):
            raise ValueError("resource-binary-source")
    # A fresh directory prevents stale copies, symlink outputs and in-place
    # stripping. Its caller owns cleanup, including a partially failed stage.
    destination.mkdir(mode=0o700)
    sizes = {}
    for name, source in zip(NAMES, sources):
        target = destination / name
        subprocess.run(["objcopy", "--strip-debug", str(source), str(target)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=60)
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or not os.access(target, os.X_OK)
                or not 0 < info.st_size <= maximum):
            raise ValueError("resource-binary-output-bound")
        sizes[name] = info.st_size
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    # Use the collector's frozen limit rather than introducing an override or
    # making its runtime/receipt profile depend on the size of DWARF sections.
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.phase2_gate_resource_profile import PROFILE

    for name, size in prepare(args.build_directory, args.output_directory,
                              PROFILE["maximumBinaryBytes"]).items():
        print(f"Phase 2 resource binary {name}: {size} bytes (debug sections removed)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Phase 2 resource binary preparation failed", file=sys.stderr)
        sys.exit(1)
