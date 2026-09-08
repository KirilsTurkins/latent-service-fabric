#!/usr/bin/env python3
"""Run a separate nine-case LSF-before/after profile; smoke never claims full evidence."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from tools.optimization_revision_runner.collect import execute
from tools.optimization_revision_runner.build import preflight_build_parent
from tools.optimization_revision_runner.model import CONTROL


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--control-ref", default=CONTROL)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--harness-ref", required=True)
    parser.add_argument("--target-root", type=Path,
                        help="build parent outside Cargo-configured ancestors; default: a private system temporary directory")
    parser.add_argument("--output", type=Path, required=True, help="new directory; retained on failure")
    parser.add_argument("--backend-build-output", type=Path, help="optional fresh sibling for separate backend collector inputs")
    try:
        args = parser.parse_args(argv)
        owner = (nullcontext(args.target_root) if args.target_root is not None
                 else tempfile.TemporaryDirectory(prefix="lsf-revision-parent-"))
        with owner as target:
            args.target_root = preflight_build_parent(Path(target))
            return execute(args, ROOT)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Revision benchmark failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
