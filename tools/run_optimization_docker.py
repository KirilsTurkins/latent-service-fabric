#!/usr/bin/env python3
"""Build, collect and independently replay the finite Docker comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    build = sub.add_parser("build", help="one clean pinned Linux release build")
    build.add_argument("--source-ref", required=True)
    build.add_argument("--target-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    transfer = sub.add_parser("import", help="import only a retained build closure through the Engine socket")
    transfer.add_argument("--implementation-id", required=True)
    transfer.add_argument("--source-path", required=True)
    transfer.add_argument("--output", type=Path, required=True)
    images = sub.add_parser("images", help="build the three pinned local images without network build steps")
    images.add_argument("--build-root", type=Path, required=True)
    run = sub.add_parser("run", help="explicit smoke or full finite campaign")
    run.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    run.add_argument("--run-id", required=True)
    run.add_argument("--source-ref", required=True)
    run.add_argument("--build-root", type=Path, required=True)
    run.add_argument("--volume", required=True)
    run.add_argument("--controller-id", required=True)
    run.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate", help="offline raw evidence replay and exact aggregate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--build-root", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "build":
        from tools.optimization_docker.build import execute
        return execute(args, ROOT)
    if args.operation in ("import", "images"):
        from tools.optimization_docker.engine import Engine
        from tools.optimization_docker import setup
        engine = Engine()
        value = (setup.import_build(engine, args.implementation_id, args.source_path, args.output, ROOT)
                 if args.operation == "import" else setup.prepare_images(engine, args.build_root, ROOT))
        print(json.dumps(value, separators=(",", ":")))
        return 0
    if args.operation == "run":
        from tools.optimization_docker.collect import execute
        return execute(args, ROOT)
    from tools.optimization_docker import aggregate, evidence
    derived = evidence.validate(args.root, args.build_root)
    aggregate.write(derived, args.output)
    print(json.dumps({"qualified": derived["qualified"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
