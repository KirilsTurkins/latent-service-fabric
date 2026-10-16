#!/usr/bin/env python3
"""Create, compile and package an independent C# component using the pinned SDK."""
from __future__ import annotations
import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import sys
import tomllib
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, AUTHORING_TEMPLATES, fresh, read_file, snapshot, write_json
from tools.rust_capsule_build import Commands
from tools.build_observation import build_environment
from tools.dotnet_guest.project import create
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.dotnet_guest.runtime import ADAPTERS
from tools.dotnet_guest import http_errors


def install(directory: Path, wasi_sdk: Path):
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("the pinned NativeAOT toolchain requires Linux x86-64")
    wasi_sdk = wasi_sdk.resolve(strict=True)
    if read_file(wasi_sdk / "VERSION").decode().splitlines() != [
            "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
        raise ValueError("WASI SDK 29.0 with the pinned LLVM 21.1.4 toolchain is required")
    directory = fresh(directory)
    sdk = ROOT / "sdk/dotnet-guest"
    for source, destination in (("global.json", "global.json"), ("nuget.config", "nuget.config"),
            ("probes/smoke/Smoke.csproj", "Smoke.csproj"), ("probes/smoke/packages.lock.json", "packages.lock.json")):
        (directory / destination).write_bytes(read_file(sdk / source))
    environment = build_environment(directory)
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
        DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", DOTNET_ROLL_FORWARD="Disable",
        DOTNET_CLI_HOME=str(directory / "cli-home"), MSBUILDDISABLENODEREUSE="1")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode())["rust"]["toolchain"]
    command = Commands(directory, directory, environment)
    dotnet, wasm = shutil.which("dotnet"), shutil.which("wasm-tools")
    if not dotnet or command.run("dotnet-version", dotnet, "--version").strip() != b"10.0.100":
        raise ValueError(".NET SDK 10.0.100 is required")
    if not wasm or command.run("wasm-tools-version", wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
        raise ValueError("wasm-tools 1.254.0 is required")
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    before = runtime_inputs(ROOT)
    command.run("runtime-compiler-version", "rustc", "--version")
    command.run("locked-restore", dotnet, "restore", directory / "Smoke.csproj", "--configfile", directory / "nuget.config",
        "--locked-mode", "--packages", directory / "packages", "--disable-parallel")
    for name, data in snapshot(sdk / "tools/package-hash").items():
        path = directory / "package-hash-source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    command.run("package-hash-build", dotnet, "build", directory / "package-hash-source/PackageHash.csproj",
        "-c", "Release", "--output", directory / "package-hash", "--artifacts-path", directory / "package-hash-artifacts",
        "-p:NuGetAudit=false", "-nodeReuse:false")
    http_errors.install(sdk, directory, Path(dotnet), command.run)
    command.run("closed-runtime-compile", "cargo", "build", "--quiet", "--locked",
        "--manifest-path", ROOT / "tools/toolchain-smoke/Cargo.toml", "-p", "latent-toolchain-smoke",
        *(argument for example, _binary in ADAPTERS.values() for argument in ("--example", example)),
        "--target", "wasm32-unknown-unknown", "--release", "--target-dir", target)
    for profile, (example, binary) in ADAPTERS.items():
        command.run(profile + "-runtime-component", wasm, "component", "new",
            target / "wasm32-unknown-unknown/release/examples" / (example.replace("-", "_") + ".wasm"),
            "-o", directory / binary)
    if runtime_inputs(ROOT) != before:
        raise ValueError("runtime sources changed during compilation")
    (directory / "runtime-inputs.json").write_bytes(before)
    from tools.dotnet_guest.composer import install as install_composer
    install_composer(directory, sdk, command)
    write_json(directory / "wasi-sdk.json", {"path": str(wasi_sdk)})
    write_json(directory / "INSTALL-COMPLETE.json", {"commands": command.records})
    return directory


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tools = commands.add_parser("install-tools")
    tools.add_argument("directory", type=Path)
    tools.add_argument("--wasi-sdk", type=Path, required=True)
    new = commands.add_parser("new")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=AUTHORING_TEMPLATES, default="greeting")
    new.add_argument("--name")
    resolve_ = commands.add_parser('resolve')
    resolve_.add_argument('project', type=Path)
    resolve_.add_argument('--candidate', type=Path, required=True)
    resolve_.add_argument('--dotnet', type=Path, required=True)
    resolve_.add_argument('--tools', type=Path, required=True)
    resolve_.add_argument('--feed-config', type=Path)
    resolve_.add_argument('--update-lock', action='store_true')
    for operation in ('add', 'update', 'remove'):
        command = commands.add_parser(operation, help='Edit exact application PackageReference inputs without restoring')
        command.add_argument('project', type=Path)
        command.add_argument('identity')
        if operation in {'add', 'update'}:
            command.add_argument('--version', required=True)
    review = commands.add_parser('review-lock', help='Accept an exact reviewed captured NuGet candidate')
    review.add_argument('project', type=Path)
    review.add_argument('--candidate', type=Path, required=True)
    review.add_argument('--expect', required=True)
    status = commands.add_parser('dependencies', help='Verify original NuGet inputs offline')
    status.add_argument('project', type=Path)
    for operation in ('test', 'watch'):
        command = commands.add_parser(operation, help='Delegate reviewed inputs to the maintained frontend')
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
    compile_ = commands.add_parser("build")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--tools", type=Path, required=True)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True)
    compile_.add_argument('--executable-approval')
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    authoring = args.command in {'add', 'update', 'remove', 'resolve', 'review-lock', 'dependencies', 'test', 'watch'}
    try:
        if authoring:
            from tools import dotnet_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {'test', 'watch'}:
                from tools import guest_authoring_frontend
                from tools.guest_dependency_inputs import layout
                owner, _app, _descriptor = layout(args.project, 'dotnet')
                delegated = dependencies.frontend(owner, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, 'tool_root', None),
                    selections=tuple(args.select), environment=getattr(args, 'environment', 'node'))
                outcome = guest_authoring_frontend.execute(owner, args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                try:
                    dependencies.record(owner, {**outcome.evidence, 'stage': 'nuget-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('NuGet dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return outcome.exit_code
            if args.command in {'add', 'update', 'remove'}:
                result = dependencies.edit(args.project, args.command, identity=args.identity, version=getattr(args, 'version', None))
            elif args.command == 'resolve':
                from tools.application_dependency_store import DependencyError
                from tools.dotnet_application_dependencies import resolve
                candidate = dependencies.candidate_location(args.project, args.candidate)
                if any(os.path.lexists(candidate.with_name(candidate.name + suffix)) for suffix in ('.receipt.json', '.failed.json')):
                    raise DependencyError('nuget-dependency-candidate-use-fresh-attempt')
                lock = resolve(args.project, candidate, dotnet=args.dotnet, tools=args.tools,
                    policy=json.loads(read_file(args.feed_config)) if args.feed_config else None, update_lock=args.update_lock)
                result = dependencies.resolved(args.project, candidate, lock)
                paths.write_new(candidate.with_name(candidate.name + '.receipt.json'), canonical(result) + b'\n')
            elif args.command == 'review-lock':
                result = dependencies.review(args.project, args.candidate, args.expect)
            else:
                result = dependencies.status(args.project)
            receipt = dependencies.record(args.project, result)
            print(canonical({**result, 'receipt': str(receipt)}).decode())
            return 0
        if args.command == "install-tools":
            result = install(args.directory, args.wasi_sdk)
        elif args.command == "new":
            result = create(args.directory, args.template, args.name)
        else:
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository, tools=args.tools,
                executable_approval=args.executable_approval)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import dotnet_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == 'resolve' and result['reason'] not in {
                        'dependency-candidate-exists', 'nuget-dependency-candidate-use-fresh-attempt',
                        'nuget-candidate-cannot-overwrite-reviewed-input'}:
                    candidate = dependencies.candidate_location(args.project, args.candidate)
                    failed = candidate.with_name(candidate.name + '.failed.json')
                    if not os.path.lexists(failed):
                        failed.parent.mkdir(parents=True, exist_ok=True)
                        paths.write_new(failed, canonical(result) + b'\n')
            except (ValueError, OSError):
                pass
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"C# capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
