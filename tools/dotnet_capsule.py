#!/usr/bin/env python3
"""Create, compile and package an independent C# component using the pinned SDK."""
from __future__ import annotations
import argparse
import os
import platform
from pathlib import Path
import shutil
import sys
import tomllib
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, read_file, snapshot, write_json
from tools.rust_capsule_build import Commands
from tools.build_observation import build_environment
from tools.dotnet_guest.project import create
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs


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
    command.run("closed-runtime-compile", "cargo", "build", "--quiet", "--locked",
        "--manifest-path", ROOT / "tools/toolchain-smoke/Cargo.toml", "-p", "latent-toolchain-smoke",
        "--example", "dotnet-closed-runtime", "--target", "wasm32-unknown-unknown", "--release", "--target-dir", target)
    command.run("closed-runtime-component", wasm, "component", "new",
        target / "wasm32-unknown-unknown/release/examples/dotnet_closed_runtime.wasm", "-o", directory / "runtime.wasm")
    if runtime_inputs(ROOT) != before:
        raise ValueError("closed runtime sources changed during compilation")
    (directory / "runtime-inputs.json").write_bytes(before)
    write_json(directory / "wasi-sdk.json", {"path": str(wasi_sdk)})
    write_json(directory / "INSTALL-COMPLETE.json", {"commands": command.records})
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tools = commands.add_parser("install-tools")
    tools.add_argument("directory", type=Path)
    tools.add_argument("--wasi-sdk", type=Path, required=True)
    new = commands.add_parser("new")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--tools", type=Path, required=True)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True)
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    args = parser.parse_args()
    try:
        if args.command == "install-tools":
            result = install(args.directory, args.wasi_sdk)
        elif args.command == "new":
            result = create(args.directory, args.template, args.name)
        else:
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository, tools=args.tools)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"C# capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
