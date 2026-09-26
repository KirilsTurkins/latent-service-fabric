#!/usr/bin/env python3
"""Create and build editable Go Component Model capsule projects."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.go_capsule_project import ROOT, TEMPLATES, create
from tools.go_capsule_build import build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an independent Go project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build", help="Compile, validate and package captured Go sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True, help="Public operator-asserted source label")
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    args = parser.parse_args()
    try:
        result = (create(args.directory, args.template, args.name) if args.command == "new" else
                  build(args.project, args.output, args.contracts_tool, args.packager, args.repository))
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Go capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
