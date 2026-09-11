#!/usr/bin/env python3
"""Collect or replay the bounded actual Kubernetes infrastructure comparison."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selected = commands.add_parser("bootstrap", help="Connect a verified owned kind cluster; no guest work")
    selected.add_argument("--setup", type=Path, required=True)
    selected.add_argument("--original-setup", type=Path, required=True)
    selected.add_argument("--kubeconfig", type=Path, required=True)
    selected.add_argument("--output", type=Path, required=True)
    selected = commands.add_parser("validate", help="Offline source, raw protocol and paired report replay")
    for name in ("root", "build-root", "docker-run", "bootstrap-root", "output"):
        selected.add_argument("--" + name, type=Path, required=True)
    selected = commands.add_parser("run", help="Run the finite smoke or seven-pair comparison")
    selected.add_argument("--profile", choices=("smoke", "full"), required=True)
    selected.add_argument("--source-ref", required=True)
    selected.add_argument("--run-id", required=True)
    for name in ("bootstrap", "build-root", "docker-run", "output"):
        selected.add_argument("--" + name, type=Path, required=True)
    selected = commands.add_parser("cleanup", help="Remove only the recorded owned kind cluster")
    selected.add_argument("--bootstrap", type=Path, required=True)
    selected.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        from tools.optimization_kubernetes import bootstrap
        return bootstrap.execute(args, REPOSITORY)
    if args.command == "run":
        from tools.optimization_kubernetes import collect
        return collect.execute(args, REPOSITORY)
    if args.command == "cleanup":
        from tools.optimization_kubernetes import bootstrap
        return bootstrap.cleanup(args, REPOSITORY)
    if args.command == "validate":
        from tools.optimization_kubernetes import aggregate, replay
        derived, original = replay.validate(args.root, args.build_root, args.docker_run, args.bootstrap_root)
        result = aggregate.write(derived, original, args.output)
        print(json.dumps({"status": "passed", "profile": result["profile"], "output": str(args.output)}))
        return 0
    raise ValueError("unknown Kubernetes command")


if __name__ == "__main__":
    raise SystemExit(main())
