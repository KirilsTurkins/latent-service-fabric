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
    resolve_ = commands.add_parser("resolve", help="Explicitly capture declared C source/static library closure")
    resolve_.add_argument("project", type=Path)
    resolve_.add_argument("--candidate", type=Path, required=True)
    resolve_.add_argument("--repositories", type=Path)
    compile_ = commands.add_parser("build", help="Compile, validate and package captured C sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True, help="Public operator-asserted source label")
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    packaging = compile_.add_mutually_exclusive_group()
    packaging.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    packaging.add_argument("--package-inputs-only", action="store_true", help="Leave package assembly to the calling controller")
    archive = commands.add_parser("archive", help="Compile declared captured library sources into an observed Wasm archive")
    archive.add_argument("project", type=Path)
    archive.add_argument("--output", type=Path, required=True)
    archive.add_argument("--repository", required=True, help="Public operator-asserted source label")
    args = parser.parse_args()
    try:
        if args.command == "new":
            result = create(args.directory, args.template, args.name)
        elif args.command == "resolve":
            from tools.application_dependencies import capture, document
            from tools.build_snapshot import canonical
            from tools.application_dependency_store import DependencyError
            if args.candidate.exists():
                raise DependencyError("dependency-candidate-exists")
            repositories = document(args.repositories) if args.repositories else {}
            try:
                lock = capture(args.project, repositories=repositories)
                with args.candidate.open("xb") as output:
                    output.write(canonical(lock) + b"\n")
            except (DependencyError, OSError) as error:
                failed = args.candidate.with_name(args.candidate.name + ".failed.json")
                reason = str(error) if isinstance(error, DependencyError) else "dependency-resolution-io-failed"
                if not failed.exists():
                    with failed.open("xb") as output:
                        output.write(canonical({"formatVersion": 1, "stage": "c-resolution-capture", "status": "failed", "reason": reason}) + b"\n")
                raise DependencyError(reason) from None
            result = args.candidate
        elif args.command == "archive":
            from tools.c_static_archive_build import build as build_archive
            result = build_archive(args.project, args.output, args.repository)
        else:
            result = build(args.project, args.output, args.contracts_tool, None if args.package_inputs_only else args.packager, args.repository)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"C capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
