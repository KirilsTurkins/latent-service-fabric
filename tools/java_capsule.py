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


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create an independent Java project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    add = commands.add_parser('add', help='Declare an exact Maven coordinate for explicit resolution and review')
    add.add_argument('project', type=Path)
    add.add_argument('coordinate', help='group:name:exact-version')
    add.add_argument('--scope', choices=('compile', 'runtime'), default='runtime')
    add.add_argument('--exclude', action='append', default=[], help='group:name exclusion')
    add.add_argument('--repository-id')
    add.add_argument('--repository-url')
    add.add_argument('--repository-ca', help='Project-relative public PEM certificate for the separately captured resolver truststore')
    local = commands.add_parser('add-local', help='Declare an explicit developer-selected local/private JAR')
    local.add_argument('project', type=Path)
    local.add_argument('--id', required=True)
    local.add_argument('--jar', type=Path, required=True)
    local.add_argument('--depends', action='append', default=[])
    update = commands.add_parser('update', help='Edit an exact declaration; resolve and review again before compilation')
    update.add_argument('project', type=Path)
    update.add_argument('identity', help='group:name or declared local JAR id')
    update.add_argument('--version')
    update.add_argument('--jar', type=Path)
    remove = commands.add_parser('remove', help='Remove one exact declaration; retain old reviewed bytes until fresh review')
    remove.add_argument('project', type=Path)
    remove.add_argument('identity')
    server = commands.add_parser("new-server", help="Create an ordinary HttpServer source project with an automatic finite profile")
    server.add_argument("directory", type=Path)
    server.add_argument("--name")
    resolve_ = commands.add_parser("resolve", help="Explicitly resolve Maven/local JAR closure and emit a reviewable lock candidate")
    resolve_.add_argument("project", type=Path)
    resolve_.add_argument("--candidate", type=Path, required=True)
    resolve_.add_argument("--gradle", default="gradle")
    review = commands.add_parser('review-lock', help='Accept the exact digest of a captured, verified Java candidate')
    review.add_argument('project', type=Path)
    review.add_argument('--candidate', type=Path, required=True)
    review.add_argument('--expect', required=True, help='sha256:<64 hex> of the reviewed candidate bytes')
    status = commands.add_parser('dependencies', help='Verify captured Java inputs offline')
    status.add_argument('project', type=Path)
    generator = commands.add_parser('generator-request', help='Request explicit approval for a contained Java source generator or processor launcher')
    generator.add_argument('project', type=Path)
    generator.add_argument('--candidate', type=Path, required=True)
    generator.add_argument('--tool', type=Path, required=True)
    generator.add_argument('--tool-version', required=True)
    generator.add_argument('--inputs', type=Path, required=True)
    generator.add_argument('--arg', action='append', default=[])
    generator.add_argument('--destination', default='src/generated')
    generator.add_argument('--timeout', type=float, default=60)
    generator.add_argument('--maximum-output-bytes', type=int, default=1024 * 1024)
    generate = commands.add_parser('generate', help='Run only the exact explicitly approved request and capture fresh Java source')
    generate.add_argument('project', type=Path)
    generate.add_argument('--candidate', type=Path, required=True)
    generate.add_argument('--expect', required=True)
    for operation in ('test', 'watch'):
        command = commands.add_parser(operation, help='Delegate reviewed Java inputs to the authenticated maintained frontend')
        command.add_argument('project', type=Path)
        command.add_argument('--workspace', required=True)
        command.add_argument('--state-root', type=Path)
        command.add_argument('--select', action='append', default=[])
        command.add_argument('--frontend', type=Path)
        command.add_argument('--frontend-sha256')
        command.add_argument('--frontend-timeout', type=int, default=600)
        if operation == 'test':
            command.add_argument('--environment', choices=('node', 'portable'), default='node')
        else:
            command.add_argument('--tool-root')
    compile_ = commands.add_parser("build", help="Compile, validate and package captured Java sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True, help="Public operator-asserted source label")
    compile_.add_argument("--wasi-sdk", type=Path, default=os.environ.get("WASI_SDK_PATH"))
    compile_.add_argument("--gradle", default="gradle")
    compile_.add_argument("--offline-cache", type=Path, help="Captured immutable Gradle compiler dependency cache")
    compile_.add_argument("--read-only-cache", type=Path, help="Verified immutable Gradle module cache; updates stay in the owned compiler home")
    compile_.add_argument("--runtime-profile", choices=("teavm-activation-fibers-v1",),
                          help="Explicit SDK activation runtime profile; WIT imports and operator grants remain required")
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    authoring = args.command not in {'new', 'new-server', 'build'}
    try:
        if authoring:
            from tools import java_dependency_authoring as dependencies
            from tools.application_dependency_store import DependencyError
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {'test', 'watch'}:
                from tools import guest_authoring_frontend
                owner, _app, _sdk = dependencies.seal(args.project)
                delegated = dependencies.frontend(owner, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, 'tool_root', None),
                    selections=tuple(args.select), environment=getattr(args, 'environment', 'node'))
                outcome = guest_authoring_frontend.execute(owner, args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                try:
                    dependencies.record(owner, {**outcome.evidence, 'stage': 'java-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('Java dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return outcome.exit_code
            if args.command in {'generator-request', 'generate'}:
                from tools import java_generator_authoring as generator
                result = (generator.request(args.project, args.candidate, tool=args.tool,
                            arguments=args.arg, inputs=args.inputs, destination=args.destination,
                            tool_version=args.tool_version, timeout_seconds=args.timeout,
                            maximum_output_bytes=args.maximum_output_bytes)
                          if args.command == 'generator-request'
                          else generator.run(args.project, args.candidate, args.expect))
            elif args.command == 'resolve':
                from tools.java_dependency_resolution import resolve
                candidate = dependencies.candidate_location(args.project, args.candidate)
                if any(os.path.lexists(candidate.with_name(candidate.name + suffix)) for suffix in ('.receipt.json', '.failed.json')):
                    raise DependencyError('java-dependency-candidate-use-fresh-attempt')
                lock = resolve(args.project, candidate, gradle=args.gradle)
                result = dependencies.resolved(args.project, candidate, lock)
                paths.write_new(candidate.with_name(candidate.name + '.receipt.json'), canonical(result) + b'\n')
            elif args.command == 'review-lock':
                result = dependencies.review(args.project, args.candidate, args.expect)
            elif args.command == 'dependencies':
                result = dependencies.status(args.project)
            else:
                repository = None
                if args.command == 'add' and (args.repository_id or args.repository_url):
                    if not args.repository_id or not args.repository_url:
                        raise DependencyError('java-repository-policy-invalid')
                    repository = args.repository_id, args.repository_url
                result = dependencies.edit(args.project, args.command,
                    coordinate=getattr(args, 'coordinate', None), local_id=getattr(args, 'id', None),
                    jar=getattr(args, 'jar', None), dependencies=tuple(getattr(args, 'depends', [])),
                    scope=getattr(args, 'scope', 'runtime'), exclusions=tuple(getattr(args, 'exclude', [])),
                    repository=repository, repository_ca=getattr(args, 'repository_ca', None),
                    identity=getattr(args, 'identity', None), version=getattr(args, 'version', None))
            receipt = dependencies.record(args.project, result)
            print(canonical({**result, 'receipt': str(receipt)}).decode())
            return 0
        elif args.command == "new": result = create(args.directory, args.template, args.name)
        elif args.command == "new-server":
            from tools.java_server_project import create_server
            result = create_server(args.directory, args.name)
        else:
            if args.wasi_sdk is None: raise ValueError("provide --wasi-sdk or WASI_SDK_PATH for pinned WASI-SDK 29")
            selection = {}
            if args.runtime_profile is not None: selection["runtime_profile"] = args.runtime_profile
            if args.read_only_cache is not None: selection["read_only_cache"] = args.read_only_cache
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository,
                           args.wasi_sdk, gradle=args.gradle, offline_cache=args.offline_cache, **selection)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import java_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == 'resolve' and result['reason'] not in {
                        'java-lock-candidate-exists', 'java-dependency-candidate-use-fresh-attempt',
                        'java-candidate-cannot-overwrite-reviewed-input'}:
                    candidate = dependencies.candidate_location(args.project, args.candidate)
                    failed = candidate.with_name(candidate.name + '.failed.json')
                    if not os.path.lexists(failed):
                        paths.write_new(failed, canonical(result) + b'\n')
            except (ValueError, OSError):
                pass
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"Java capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
