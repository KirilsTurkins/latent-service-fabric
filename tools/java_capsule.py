#!/usr/bin/env python3
"""Create and build independent Java capsules with typed current WIT bindings."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_capsule_project import ROOT, TEMPLATES, create
from tools.java_capsule_build import build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an independent Java project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build", help="Compile, validate and package captured Java sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True, help="Public operator-asserted source label")
    compile_.add_argument("--wasi-sdk", type=Path, default=os.environ.get("WASI_SDK_PATH"))
    compile_.add_argument("--gradle", default="gradle")
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    args = parser.parse_args()
    try:
        if args.command == "new": result = create(args.directory, args.template, args.name)
        else:
            if args.wasi_sdk is None: raise ValueError("provide --wasi-sdk or WASI_SDK_PATH for pinned WASI-SDK 29")
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository,
                           args.wasi_sdk, gradle=args.gradle)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Java capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
