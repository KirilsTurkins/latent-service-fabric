#!/usr/bin/env python3
"""Build exact backend comparison inputs without executing a benchmark."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
from tools.optimization_backend_revision.build import execute
from tools.optimization_revision_runner.build import preflight_build_parent


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile",choices=("smoke","full"),default="smoke")
    parser.add_argument("--experiment",choices=("warm","cold"),default="warm")
    for name in ("control","candidate","harness"):
        parser.add_argument("--"+name+"-ref",required=True,help="full immutable commit SHA")
    parser.add_argument("--output",type=Path,required=True,help="fresh retained backend-builds directory")
    parser.add_argument("--target-root",type=Path,help="external build parent; defaults to an owned system temporary directory")
    try:
        args=parser.parse_args(argv)
        owner=(nullcontext(args.target_root) if args.target_root is not None
               else tempfile.TemporaryDirectory(prefix="lsf-backend-build-parent-"))
        with owner as target:
            args.target_root=preflight_build_parent(Path(target))
            return execute(args,ROOT)
    except (OSError,ValueError,RuntimeError) as error:
        print(f"Backend comparison build failed: {error}",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
