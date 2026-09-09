#!/usr/bin/env python3
"""Build matched private-cache and actual-node collectors without running them."""
import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tools.optimization_cache_lookup.build import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), required=True)
    for arm in ("control", "candidate", "harness"):
        parser.add_argument("--" + arm + "-ref", required=True)
    parser.add_argument("--lookup-output", type=Path, required=True)
    parser.add_argument("--behavior-output", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, default=Path(tempfile.gettempdir()) / "latent-cache-builds-owned")
    try:
        return execute(parser.parse_args(), ROOT)
    except (OSError, ValueError, TimeoutError) as error:
        parser.exit(1, f"cache build failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
