#!/usr/bin/env python3
"""Run paired LSF revision profiles with bounded smoke/full populations."""
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
    parser.add_argument("--experiment", choices=("warm", "budget", "recovery"), default="warm")
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--control-ref")
    parser.add_argument("--candidate-ref")
    parser.add_argument("--harness-ref")
    parser.add_argument("--target-root", type=Path,
                        help="build parent outside Cargo-configured ancestors; default: a private system temporary directory")
    parser.add_argument("--output", type=Path, help="new directory; retained on failure")
    parser.add_argument("--build-only", action="store_true", help="budget/recovery: retain collectors/inputs without measuring")
    parser.add_argument("--builds", type=Path, help="budget/recovery: collect beside a fresh copied revision-builds.json")
    parser.add_argument("--backend-build-output", type=Path, help="optional fresh sibling for separate backend collector inputs")
    try:
        args = parser.parse_args(argv)
        if args.builds:
            if args.experiment not in ("budget", "recovery") or any((args.build_only, args.output, args.control_ref, args.candidate_ref,
                                                   args.harness_ref, args.backend_build_output)):
                parser.error("--builds requires budget/recovery mode and cannot be combined with output/build/ref options")
        elif not all((args.candidate_ref, args.harness_ref, args.output)):
            parser.error("fresh builds require --candidate-ref, --harness-ref and --output")
        elif args.control_ref is None:
            args.control_ref = CONTROL
        if args.build_only and args.experiment not in ("budget", "recovery"):
            parser.error("--build-only is available only for budget/recovery experiments")
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
