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


def parser() -> argparse.ArgumentParser:
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
    for operation in ("add", "update", "remove"):
        command = commands.add_parser(operation, help="Edit application declarations; preserve the reviewed lock")
        command.add_argument("project", type=Path)
        command.add_argument("--expect-manifest", help="Reject edits if the reviewed manifest digest changed")
        if operation != "remove":
            command.add_argument("--artifact", type=Path, action="append", required=True,
                                 help="One complete artifact declaration JSON file; repeat for a closed add graph")
        if operation != "add":
            command.add_argument("--id", action="append", required=True, help="Exact artifact ID; repeat for closed removal")
    review = commands.add_parser("review-lock", help="Verify captured bytes and atomically accept an explicitly reviewed candidate")
    review.add_argument("project", type=Path)
    review.add_argument("--candidate", type=Path, required=True)
    review.add_argument("--expect", required=True, help="Exact sha256:<64 hex> of the reviewed candidate bytes")
    status = commands.add_parser("dependencies", help="Verify the offline reviewed closure without opening original feeds")
    status.add_argument("project", type=Path)
    for operation in ("test", "watch"):
        command = commands.add_parser(operation, help="Run the maintained latent-dev command for an authenticated C project")
        command.add_argument("project", type=Path)
        command.add_argument("--workspace", required=True)
        command.add_argument("--state-root", type=Path)
        command.add_argument("--select", action="append", default=[])
        command.add_argument("--frontend", type=Path, help="Absolute executable from the authenticated standalone frontend installation")
        command.add_argument("--frontend-sha256", help="Exact reviewed sha256:<64 hex> of the selected frontend executable")
        command.add_argument("--frontend-timeout", type=int, default=600, help="Standalone wrapper lifetime, 1..3600 seconds; remote operations keep their original budgets")
        if operation == "test":
            command.add_argument("--environment", choices=("node", "portable"), default="node")
        else:
            command.add_argument("--tool-root")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    authoring = args.command in {"add", "update", "remove", "resolve", "review-lock", "dependencies", "test", "watch"}
    try:
        if args.command == "new":
            result = create(args.directory, args.template, args.name)
        elif authoring:
            from tools import c_dependency_authoring as dependencies
            from tools.application_dependencies import document
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {"test", "watch"}:
                from tools import guest_authoring_frontend
                delegated = dependencies.frontend(args.project, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, "tool_root", None),
                    selections=tuple(args.select), environment=getattr(args, "environment", "node"))
                outcome = guest_authoring_frontend.execute(args.project.absolute(), args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                code = outcome.exit_code
                try:
                    dependencies.record(args.project, {**outcome.evidence, 'stage': 'c-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('C dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return code
            if args.command in {"add", "update", "remove"}:
                result = dependencies.edit(args.project, args.command,
                    [document(path) for path in getattr(args, "artifact", [])], getattr(args, "id", []),
                    expected=args.expect_manifest)
            elif args.command == "resolve":
                from tools.application_dependency_store import DependencyError
                import os
                if args.repositories is not None and args.repositories.absolute().is_relative_to(args.project.absolute()):
                    raise DependencyError("c-private-repository-config-must-stay-outside-project")
                if any(os.path.lexists(args.candidate.with_name(args.candidate.name + suffix))
                       for suffix in (".receipt.json", ".failed.json")):
                    raise DependencyError("c-dependency-candidate-use-fresh-attempt")
                result = dependencies.resolve(args.project, args.candidate,
                    repositories=document(args.repositories) if args.repositories else {})
                paths.write_new(args.candidate.with_name(args.candidate.name + ".receipt.json"), canonical(result) + b"\n")
            elif args.command == "review-lock":
                result = dependencies.review(args.project, args.candidate, args.expect)
            else:
                result = dependencies.status(args.project)
            receipt = dependencies.record(args.project, result)
            print(canonical({**result, 'receipt': str(receipt)}).decode())
            return 0
        elif args.command == "archive":
            from tools.c_static_archive_build import build as build_archive
            from tools.c_dependency_authoring import application_root
            result = build_archive(application_root(args.project), args.output, args.repository)
        else:
            from tools.c_dependency_authoring import application_root
            result = build(application_root(args.project), args.output, args.contracts_tool, None if args.package_inputs_only else args.packager, args.repository)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import c_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == "resolve":
                    failed = args.candidate.with_name(args.candidate.name + ".failed.json")
                    if not failed.exists():
                        paths.write_new(failed, canonical(result) + b"\n")
            except (ValueError, OSError):
                pass  # Preserve the first outcome; an unavailable receipt never permits replay.
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"C capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
