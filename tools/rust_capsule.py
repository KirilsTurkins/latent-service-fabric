#!/usr/bin/env python3
"""Create and build standalone Rust capsules with the existing pinned guest SDK."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import rust_capsule_project as project
from tools.rust_capsule_build import build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a new independent Cargo project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=project.TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build", help="Compile, validate and package actual project sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True, help="Fresh directory; failed attempts are retained")
    compile_.add_argument("--repository", required=True, help="Public source label asserted by the builder; not authenticated")
    compile_.add_argument("--contracts-tool", type=Path, default=project.ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=project.ROOT / "target/debug/examples/package")
    compile_.add_argument("--offline", action="store_true", help="Use already-cached pinned Cargo dependencies only")
    args = parser.parse_args()
    try:
        if args.command == "new":
            result = project.create(args.directory, args.template, args.name)
        else:
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository, offline=args.offline)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Rust capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
