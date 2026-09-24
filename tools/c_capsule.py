#!/usr/bin/env python3
"""Create and build independent C capsules with pinned WIT-generated bindings."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.c_capsule_project import ROOT, TEMPLATES, create
from tools.c_capsule_build import build


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an independent C project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build", help="Compile, validate and package captured C sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True, help="Public operator-asserted source label")
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    packaging = compile_.add_mutually_exclusive_group()
    packaging.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    packaging.add_argument("--package-inputs-only", action="store_true", help="Leave package assembly to the calling controller")
    args = parser.parse_args()
    try:
        result = (create(args.directory, args.template, args.name) if args.command == "new" else
                  build(args.project, args.output, args.contracts_tool, None if args.package_inputs_only else args.packager, args.repository))
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"C capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
