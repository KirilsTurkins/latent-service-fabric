#!/usr/bin/env python3
"""Compile one shared proposed WIT contract with a maintained language owner.

This is definition feasibility, with actual source and generated bindings. It
does not instantiate a transaction host, sign a release, or qualify #389/#401.
Failures retain bounded diagnostics and never become a successful receipt.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.java_guest.surface import surface as wit_surface
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.stage_runtime_wit import copy_wit_tree, dependencies

WORLD = "tests:transaction-contract/service@1.0.0"
FIXTURE = ROOT / "sdk/transaction-contract"
LANGUAGES = ("rust", "c", "typescript", "go", "java", "dotnet")


def definition_report_details(language: str, details: dict) -> dict:
    """Label public .NET binding checksums without changing compiler evidence.

    The maintained compiler owns its raw inventory and reproducibility checks.
    This report projection only spells the algorithm on its SHA256 fields.
    """
    if language != "dotnet":
        return details
    result = copy.deepcopy(details)
    bindings = result["bindings"]["bindings"]

    def checksum(value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value) is None:
            raise ValueError("invalid public .NET binding SHA256")
        return value if value.startswith("sha256:") else "sha256:" + value

    bindings["authoritativeWitSha256"] = checksum(bindings["authoritativeWitSha256"])
    bindings["outputs"] = {name: checksum(value) for name, value in bindings["outputs"].items()}
    return result


def check_surface(expected: dict, actual: dict) -> None:
    # Native linkers can omit unused runtime-support imports. Every proposed
    # state/intent operation, imported owner and reused type must survive with
    # its exact async signature. An actually imported runtime operation must
    # match the declared narrow support signature; no extra authority is allowed.
    mandatory = {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
    if actual["exports"] != expected["exports"] or not mandatory <= actual["imports"].keys():
        raise ValueError("compiled component changed the proposed transaction surface")
    for name, interface in actual["imports"].items():
        declared = expected["imports"].get(name)
        if declared is None:
            raise ValueError("undeclared runtime or business import survived compilation")
        if name in mandatory:
            if interface != declared:
                raise ValueError("compiled transaction ownership, async or reused types changed")
        else:
            for category in ("types", "functions"):
                if any(declared[category].get(key) != value for key, value in interface[category].items()):
                    raise ValueError("compiled narrow runtime-support signature changed")


def stage(destination: Path) -> None:
    # The destination is a new compiler-owned project; preserve its existing
    # clock dependencies and copy only the exact additional imported versions.
    source = FIXTURE / "wit"
    copy_wit_tree(source, destination)
    for package in dependencies(source, ROOT / "wit/platform"):
        copy_wit_tree(package, destination / "deps" / package.name)


def project(language: str, output: Path) -> Path:
    if language == "go":
        from tools.go_capsule_project import create
        source_name = "main.go"
    elif language == "typescript":
        from tools.typescript_guest.project import create
        source_name = "main.ts"
    elif language == "dotnet":
        from tools.dotnet_guest.project import create
        source_name = "Main.cs"
    else:
        raise ValueError("no managed project recipe for " + language)
    work = create(output / "project", "greeting", "transaction-contract")
    stage(work / "wit")
    (work / "src" / source_name).write_bytes(read_file(FIXTURE / language / source_name))
    return work


def compile_contract(language: str, output: Path, commands: Commands, *, tools: Path | None,
                     wasi_sdk: Path | None) -> tuple[Path, dict]:
    if language == "rust":
        required = {"cargo": "cargo 1.97.1", "rustc": "rustc 1.97.1",
                    "wit-bindgen": "wit-bindgen-cli 0.62.0", "wasm-tools": "wasm-tools 1.254.0"}
        # Resolving a Unix cargo/rustc proxy symlink executes rustup itself and
        # observes the proxy's version. Reuse the maintained authoring selector
        # to obtain the exact pinned compiler binaries, independently of PATH's
        # default toolchain and the invoking repository's configuration.
        selected, _ = resolve_tools(tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode()),
                                    ROOT, commands.environment)
        commands.environment["RUSTC"] = str(selected["rustc"])
        observed = {}
        for name, prefix in required.items():
            path = selected.get(name) or Path(shutil.which(name, path=commands.environment["PATH"])
                                              or "missing-" + name).resolve(strict=True)
            version = commands.run(name + "-version", path, "--version").decode().strip()
            if version.split()[:2] != prefix.split():
                raise ValueError("unreviewed Rust definition tool: " + name)
            observed[name] = (path, file_identity(path, name))
        wit = output / "wit"
        stage(wit)
        for name in ("bindings", "bindings-check"):
            commands.run(name, observed["wit-bindgen"][0], "rust", wit, "--world", WORLD,
                         "--generate-all", "--out-dir", output / name)
        first = snapshot(output / "bindings")
        if first != snapshot(output / "bindings-check"):
            raise ValueError("non-reproducible Rust bindings")
        target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
        commands.run("actual-rust-compile", observed["cargo"][0], "build", "--locked", "-p", "latent-toolchain-smoke",
                     "--example", "transaction-contract", "--target", "wasm32-unknown-unknown", "--release")
        core = target / "wasm32-unknown-unknown/release/examples/transaction_contract.wasm"
        component = output / "component.wasm"
        commands.run("compose", observed["wasm-tools"][0], "component", "new", core, "-o", component)
        for name, (path, identity) in observed.items():
            if file_identity(path, name) != identity:
                raise ValueError("Rust compiler changed during definition build")
        return component, {"bindings": json.loads(inventory(first)),
                           "tools": {name: row for name, (_, row) in observed.items()}}
    if language == "c":
        from tools.c_guest.bindings import generate
        from tools.c_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", 900, commands=commands)
        component, bindings = compiler.compile([FIXTURE / "c/probe.c"], FIXTURE / "wit", WORLD, output / "compiled")
        _, independent = generate(compiler.run, FIXTURE / "wit", WORLD, output / "bindings-check")
        if bindings != independent:
            raise ValueError("non-reproducible C bindings")
        compiler.check_unchanged()
        return component, {"bindings": bindings, "tools": compiler.materials}
    if language == "java":
        from tools.java_guest.compiler import Compiler
        if wasi_sdk is None:
            raise ValueError("Java definition qualification requires --wasi-sdk")
        compiler = Compiler(output / "compiler", wasi_sdk)
        component, details = compiler.compile(FIXTURE / "java", FIXTURE / "wit", WORLD, output / "compiled")
        compiler.check_unchanged()
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
        return component, {**details, "tools": compiler.materials, "commands": compiler.records}
    work = project(language, output)
    # The captured project owns global.json/go.mod and its exact SDK selection.
    # Running managed compiler probes in ROOT can instead select the operator's
    # .NET SDK 8.0.425; execute from the same source root as its maintained build.
    commands.root = work
    if language == "go":
        from tools.go_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", work / "vendor/lsf/sdk/go-guest", commands)
    elif language == "typescript":
        from tools.typescript_guest.compiler import Compiler
        if tools is None:
            raise ValueError("TypeScript definition qualification requires --tools")
        expected = {name: read_file(work / "vendor/lsf/sdk/typescript-guest/tools" / name)
                    for name in ("package.json", "package-lock.json")}
        compiler = Compiler(tools, commands, expected)
    else:
        from tools.dotnet_guest.compiler import Compiler
        if tools is None:
            raise ValueError(".NET definition qualification requires --tools")
        compiler = Compiler(tools, commands, work / "vendor/lsf")
    if language == "go":
        component, bindings = compiler.compile(work / "src", work / "wit", WORLD, output / "compiled")
    else:
        component, bindings = compiler.compile(work, WORLD, output / "compiled")
    compiler.check_unchanged()
    details = {"bindings": bindings}
    if hasattr(compiler, "materials"):
        details["tools"] = compiler.materials
    if hasattr(compiler, "before"):
        details["compilerClosureDigest"] = digest(json.dumps(compiler.before, sort_keys=True, separators=(",", ":")).encode())
    return component, details


def qualify(language: str, output: Path, *, tools: Path | None = None, wasi_sdk: Path | None = None) -> None:
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=900)
    report = {"schemaVersion": "latent.transaction-contract.compiler.v1", "language": language,
              "evidenceKind": "compiler-definition", "compilerDefinitionQualified": False,
              "runtimeExecutionQualified": False, "externalClientExecutionQualified": False,
              "status": "running", "world": WORLD,
              "hostAbiDigest": json.loads(read_file(ROOT / "wit/host-abi-phase4-v1.json"))["digest"],
              "preparationProfileDigest": json.loads(read_file(ROOT / "sdk/profile/transaction-preparation-v1.json"))["digest"],
              "source": json.loads(inventory(snapshot(FIXTURE)))}
    started = time.monotonic()
    try:
        report["sourceRevision"] = commands.run("source-revision", "git", "rev-parse", "HEAD").decode().strip()
        changed = commands.run("source-status", "git", "status", "--porcelain", "--untracked-files=normal")
        report["workingTreeChanged"] = bool(changed.strip())
        archive = output / "source.tar.gz"
        commands.run("retained-shared-source", "git", "archive", "--format=tar.gz", "--output", archive, "HEAD", "--",
                     "sdk/transaction-contract", "sdk/profile", "wit/host-abi-phase4-v1.json")
        if archive.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("shared transaction definition source archive exceeds its bound")
        report["sourceArchiveDigest"] = digest(read_file(archive, 16 * 1024 * 1024))
        component, details = compile_contract(language, output, commands, tools=tools, wasi_sdk=wasi_sdk)
        wasm = Path(shutil.which("wasm-tools", path=commands.environment["PATH"]) or "missing-validator").resolve(strict=True)
        commands.run("validate-authoritative-component", wasm, "validate", "--features", "all", component)
        staged = output / "authoritative-wit"
        stage(staged)
        expected = wit_surface(json.loads(commands.run("authoritative-surface", wasm, "component", "wit", staged, "--json")), WORLD)
        actual = wit_surface(json.loads(commands.run("compiled-surface", wasm, "component", "wit", component, "--json")))
        check_surface(expected, actual)
        surface = commands.run("retained-surface", wasm, "component", "wit", component)
        if b"import wasi:" in surface or b"wasi_snapshot_preview1" in surface:
            raise ValueError("ambient WASI escaped the maintained closed-runtime profile")
        (output / "component.wit").write_bytes(surface)
        report.update(status="compiler-definition-qualified", compilerDefinitionQualified=True,
                      componentDigest=digest(read_file(component, 64 * 1024 * 1024)), componentBytes=component.stat().st_size,
                      semanticSurfaceDigest=digest(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()),
                      details=definition_report_details(language, details))
    except BaseException as error:
        report.update(status="failed", reason=str(error))
        raise
    finally:
        report.update(seconds=round(time.monotonic() - started, 6), commands=commands.records)
        write_json(output / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=LANGUAGES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tools", type=Path)
    parser.add_argument("--wasi-sdk", type=Path)
    args = parser.parse_args()
    qualify(args.language, args.output, tools=args.tools, wasi_sdk=args.wasi_sdk)


if __name__ == "__main__":
    main()
