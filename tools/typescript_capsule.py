#!/usr/bin/env python3
"""Create and build independent, typed TypeScript capsules."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, AUTHORING_TEMPLATES, fresh, read_file
from tools.rust_capsule_build import Commands
from tools.build_observation import build_environment
from tools.typescript_guest.project import create
from tools.typescript_guest.build import build
from tools.typescript_application_dependencies import resolve


def install(directory: Path):
    directory = fresh(directory)
    for name in ("package.json", "package-lock.json"):
        (directory / name).write_bytes(read_file(ROOT / "sdk/typescript-guest/tools" / name))
    command = Commands(directory, directory, build_environment(directory))
    node = shutil.which("node")
    if not node or command.run("node-version", node, "--version").strip() != b"v24.19.0":
        raise ValueError("Node 24.19.0 is required")
    npm = shutil.which("npm")
    if not npm:
        raise ValueError("npm is required to install the reviewed compiler lock")
    invocation = [npm]
    if Path(npm).suffix.lower() == ".cmd":
        entrypoint = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not entrypoint.is_file():
            raise ValueError("npm CLI entrypoint unavailable")
        invocation = [node, entrypoint]
    command.run("install-locked-compiler", *invocation, "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    return directory


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tools = commands.add_parser("install-tools", help="Install the exact compiler lock in a fresh directory")
    tools.add_argument("directory", type=Path)
    new = commands.add_parser("new", help="Create an independent editable project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=AUTHORING_TEMPLATES, default="greeting")
    new.add_argument("--name")
    new.add_argument('--runtime-profile', choices=('spidermonkey-public-sync-v1', 'spidermonkey-activation-promises-v1', 'spidermonkey-activation-promises-clocks-v1'),
                     help='Explicit compiler runtime selection; the Promise candidate remains unqualified')
    capture = commands.add_parser("resolve", help="Explicitly fetch a native application npm lock without package lifecycle scripts")
    capture.add_argument("project", type=Path)
    capture.add_argument("--candidate", type=Path, required=True)
    capture.add_argument("--node", type=Path)
    capture.add_argument("--npm", type=Path, help="Explicit npm-cli.js entrypoint")
    capture.add_argument("--registry-config", type=Path)
    capture.add_argument("--condition", action="append", default=[])
    review = commands.add_parser("review-lock", help="Accept an exact reviewed immutable npm closure")
    review.add_argument("project", type=Path)
    review.add_argument("--candidate", type=Path, required=True)
    review.add_argument("--expect", required=True, help="Exact sha256:<64 hex> of reviewed candidate bytes")
    status = commands.add_parser("dependencies", help="Verify captured npm inputs offline")
    status.add_argument("project", type=Path)
    generator = commands.add_parser('generator-request', help='Request explicit approval for a contained TypeScript source generator or script launcher')
    generator.add_argument('project', type=Path)
    generator.add_argument('--candidate', type=Path, required=True)
    generator.add_argument('--tool', type=Path, required=True)
    generator.add_argument('--tool-version', required=True)
    generator.add_argument('--inputs', type=Path, required=True)
    generator.add_argument('--arg', action='append', default=[])
    generator.add_argument('--destination', default='src/generated')
    generator.add_argument('--timeout', type=float, default=60)
    generator.add_argument('--maximum-output-bytes', type=int, default=1024 * 1024)
    generate = commands.add_parser('generate', help='Run only the exact approved request and capture fresh TypeScript source')
    generate.add_argument('project', type=Path)
    generate.add_argument('--candidate', type=Path, required=True)
    generate.add_argument('--expect', required=True)
    for operation in ("test", "watch"):
        command = commands.add_parser(operation, help="Delegate reviewed inputs to the maintained frontend")
        command.add_argument("project", type=Path)
        command.add_argument("--workspace", required=True)
        command.add_argument("--state-root", type=Path)
        command.add_argument("--select", action="append", default=[])
        command.add_argument("--frontend", type=Path)
        command.add_argument("--frontend-sha256")
        command.add_argument("--frontend-timeout", type=int, default=600)
        if operation == "test":
            command.add_argument("--environment", choices=("node", "portable"), default="node")
        else:
            command.add_argument("--tool-root")
    compile_ = commands.add_parser("build", help="Typecheck, compile and package captured sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--tools", type=Path, required=True)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True)
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    compile_.add_argument('--runtime-engine', type=Path, help='Source-bound engine input for the selected Promise candidate')
    compile_.add_argument('--runtime-engine-receipt', type=Path, help='Exact engine provenance envelope; never API qualification')
    return parser


def main(argv: list[str] | None = None):
    args = parser().parse_args(argv)
    authoring = args.command in {'resolve', 'review-lock', 'dependencies', 'test', 'watch', 'generator-request', 'generate'}
    try:
        if args.command == "install-tools":
            result = install(args.directory)
        elif args.command == "new":
            result = create(args.directory, args.template, args.name,
                            **({'runtime_profile': args.runtime_profile} if args.runtime_profile is not None else {}))
        elif authoring:
            from tools import typescript_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {'test', 'watch'}:
                from tools import guest_authoring_frontend
                from tools.guest_dependency_inputs import layout
                owner, _app, _descriptor = layout(args.project, 'typescript')
                delegated = dependencies.frontend(owner, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, 'tool_root', None),
                    selections=tuple(args.select), environment=getattr(args, 'environment', 'node'))
                outcome = guest_authoring_frontend.execute(owner, args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                try:
                    dependencies.record(owner, {**outcome.evidence, 'stage': 'npm-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('TypeScript dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return outcome.exit_code
            if args.command in {'generator-request', 'generate'}:
                from tools import typescript_generator_authoring as generator
                result = (generator.request(args.project, args.candidate, tool=args.tool,
                            arguments=args.arg, inputs=args.inputs, destination=args.destination,
                            tool_version=args.tool_version, timeout_seconds=args.timeout,
                            maximum_output_bytes=args.maximum_output_bytes)
                          if args.command == 'generator-request'
                          else generator.run(args.project, args.candidate, args.expect))
            elif args.command == 'resolve':
                import os
                from tools.application_dependency_store import DependencyError
                candidate = dependencies.candidate_location(args.project, args.candidate)
                if any(os.path.lexists(candidate.with_name(candidate.name + suffix)) for suffix in ('.receipt.json', '.failed.json')):
                    raise DependencyError('npm-dependency-candidate-use-fresh-attempt')
                from tools.typescript_guest.runtime_profile import selected_profile
                from tools.guest_dependency_inputs import layout
                _owner, captured_app, _descriptor = layout(args.project, 'typescript')
                import json
                profile = selected_profile(json.loads(read_file(captured_app/'capsule-project.json')))
                lock = resolve(args.project, candidate, node=args.node, npm=args.npm, registry_config=args.registry_config,
                               selected={'conditions': args.condition, 'runtimeProfile': profile})
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
            runtime_inputs = ({'runtime_engine': args.runtime_engine,
                               'runtime_engine_receipt': args.runtime_engine_receipt}
                              if args.runtime_engine is not None or args.runtime_engine_receipt is not None else {})
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository,
                           tools=args.tools, **runtime_inputs)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import typescript_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == 'resolve' and result['reason'] not in {
                        'dependency-candidate-exists', 'npm-dependency-candidate-use-fresh-attempt',
                        'npm-candidate-cannot-overwrite-reviewed-input', 'npm-candidate-inside-captured-source'}:
                    import os
                    candidate = dependencies.candidate_location(args.project, args.candidate)
                    failed = candidate.with_name(candidate.name + '.failed.json')
                    if not os.path.lexists(failed):
                        paths.write_new(failed, canonical(result) + b'\n')
            except (ValueError, OSError):
                pass
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"TypeScript capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
