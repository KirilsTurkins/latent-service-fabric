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


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a new independent Cargo project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=project.TEMPLATES, default="greeting")
    new.add_argument("--name")
    resolve_ = commands.add_parser("resolve", help="Capture the locked native Cargo graph and vendor closure")
    resolve_.add_argument("project", type=Path)
    resolve_.add_argument("--candidate", type=Path, required=True)
    resolve_.add_argument("--cargo", type=Path)
    resolve_.add_argument("--registry-config", type=Path, help="Explicit HTTPS private registry aliases; credentials stay in resolver environment")
    resolve_.add_argument("--features", action="append", default=[])
    resolve_.add_argument("--all-features", action="store_true")
    resolve_.add_argument("--no-default-features", action="store_true")
    review = commands.add_parser("review-lock", help="Verify and accept an explicitly reviewed Cargo capture")
    review.add_argument("project", type=Path)
    review.add_argument("--candidate", type=Path, required=True)
    review.add_argument("--expect", required=True, help="Exact sha256:<64 hex> of the reviewed candidate bytes")
    status = commands.add_parser("dependencies", help="Verify the reviewed closure offline without running application hooks")
    status.add_argument("project", type=Path)
    for operation in ("test", "watch"):
        command = commands.add_parser(operation, help="Run the maintained latent-dev command for a reviewed Rust project")
        command.add_argument("project", type=Path)
        command.add_argument("--workspace", required=True)
        command.add_argument("--state-root", type=Path)
        command.add_argument("--select", action="append", default=[])
        command.add_argument("--frontend", type=Path, help="Absolute executable from the authenticated standalone frontend installation")
        command.add_argument("--frontend-sha256", help="Exact reviewed sha256:<64 hex> of the selected executable")
        command.add_argument("--frontend-timeout", type=int, default=600, help="Wrapper lifetime, 1..3600 seconds; original remote budgets are preserved")
        if operation == "test":
            command.add_argument("--environment", choices=("node", "portable"), default="node")
        else:
            command.add_argument("--tool-root")
    compile_ = commands.add_parser("build", help="Compile, validate and package actual project sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True, help="Fresh directory; failed attempts are retained")
    compile_.add_argument("--repository", required=True, help="Public source label asserted by the builder; not authenticated")
    compile_.add_argument("--contracts-tool", type=Path, default=project.ROOT / "target/debug/examples/capsule_contracts")
    packaging = compile_.add_mutually_exclusive_group()
    packaging.add_argument("--packager", type=Path, default=project.ROOT / "target/debug/examples/package")
    packaging.add_argument("--package-inputs-only", action="store_true", help="Emit checked bytes for a separately invoked packager")
    compile_.add_argument("--offline", action="store_true", help="Use already-cached pinned Cargo dependencies only")
    compile_.add_argument("--executable-approval", help="Exact captured build-script/proc-macro compiler/profile approval digest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    authoring = args.command in {"resolve", "review-lock", "dependencies", "test", "watch"}
    try:
        if args.command == "new":
            result = project.create(args.directory, args.template, args.name)
        elif authoring:
            from tools import rust_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {"test", "watch"}:
                from tools import guest_authoring_frontend
                from tools.guest_dependency_inputs import layout
                owner, _app, _descriptor = layout(args.project, 'rust')
                delegated = dependencies.frontend(owner, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, 'tool_root', None),
                    selections=tuple(args.select), environment=getattr(args, 'environment', 'node'))
                outcome = guest_authoring_frontend.execute(owner, args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                try:
                    dependencies.record(owner, {**outcome.evidence, 'stage': 'cargo-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('Rust dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return outcome.exit_code
            if args.command == 'resolve':
                import os
                from tools.application_dependency_store import DependencyError
                from tools.rust_application_dependencies import resolve
                candidate = dependencies.candidate_location(args.project, args.candidate)
                if any(os.path.lexists(candidate.with_name(candidate.name + suffix)) for suffix in ('.receipt.json', '.failed.json')):
                    raise DependencyError('cargo-dependency-candidate-use-fresh-attempt')
                lock = resolve(args.project, candidate, cargo=args.cargo, registry_config=args.registry_config,
                    selection={'features': args.features, 'allFeatures': args.all_features,
                               'noDefaultFeatures': args.no_default_features})
                result = dependencies.resolved(args.project, candidate, lock)
                paths.write_new(candidate.with_name(candidate.name + '.receipt.json'), canonical(result) + b'\n')
            elif args.command == 'review-lock':
                result = dependencies.review(args.project, args.candidate, args.expect)
            else:
                result = dependencies.status(args.project)
            receipt = dependencies.record(args.project, result)
            print(canonical({**result, 'receipt': str(receipt)}).decode())
            return 0
        else:
            result = build(args.project, args.output, args.contracts_tool, None if args.package_inputs_only else args.packager,
                           args.repository, offline=args.offline, executable_approval=args.executable_approval)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import rust_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == 'resolve' and result['reason'] not in {
                        'dependency-candidate-exists', 'cargo-dependency-candidate-use-fresh-attempt',
                        'cargo-candidate-cannot-overwrite-reviewed-input', 'cargo-candidate-inside-captured-source'}:
                    import os
                    candidate = dependencies.candidate_location(args.project, args.candidate)
                    failed = candidate.with_name(candidate.name + '.failed.json')
                    if not os.path.lexists(failed):
                        paths.write_new(failed, canonical(result) + b'\n')
            except (ValueError, OSError):
                pass  # An unavailable local receipt never authorizes replay.
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"Rust capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
