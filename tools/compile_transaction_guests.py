#!/usr/bin/env python3
"""Build authored transaction guests with the maintained language compilers.

The positive aggregate and actual forbidden-HTTP variant retain independent
captured projects, SDK locks, components and bounded failure diagnostics.
These receipts establish compilation, not signing, admission or node execution.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.java_guest.surface import surface
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.transaction_guest_project import TEMPLATE
from tools.transaction_guest_variants import HTTP, LANGUAGES, SOURCES, create as variant_project

WORLD = "examples:transactional-aggregate/service@1.0.0"
VARIANTS = ("aggregate", "forbidden-http")


def authored_project(language: str, variant: str, output: Path) -> Path:
    if variant == "forbidden-http":
        return variant_project(output, language, variant)
    if variant != "aggregate":
        raise ValueError("unknown authored transaction variant")
    if language == "rust":
        from tools.rust_capsule_project import create
    elif language == "c":
        from tools.c_capsule_project import create
    elif language == "typescript":
        from tools.typescript_guest.project import create
    elif language == "go":
        from tools.go_capsule_project import create
    elif language == "java":
        from tools.java_capsule_project import create
    elif language == "dotnet":
        from tools.dotnet_guest.project import create
    else:
        raise ValueError("unknown transaction guest language")
    return create(output, TEMPLATE, "transaction-" + language + "-aggregate")


def check_surface(expected: dict, actual: dict, variant: str) -> None:
    if variant not in VARIANTS or actual["exports"] != expected["exports"]:
        raise ValueError("authored transaction export or variant changed")
    mandatory = {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
    if not mandatory <= actual["imports"].keys() or (HTTP in actual["imports"]) != (variant == "forbidden-http"):
        raise ValueError("authored transaction or forbidden effect import missing")
    for name, imported in actual["imports"].items():
        declared = expected["imports"].get(name)
        if declared is None:
            raise ValueError("undeclared runtime or application authority survived compilation")
        # Native dead-code elimination can omit unused operations/types. Every
        # retained function and canonical owner must preserve its exact shape.
        for category in ("types", "functions"):
            if any(declared[category].get(key) != value for key, value in imported[category].items()):
                raise ValueError("authored transaction nominal type or async signature changed")
    if variant == "forbidden-http" and actual["imports"][HTTP]["functions"].get("send") != expected["imports"][HTTP]["functions"]["send"]:
        raise ValueError("actual forbidden asynchronous HTTP call missing")


def compile_project(language: str, work: Path, output: Path, command: Commands,
                    *, tools: Path | None, wasi_sdk: Path | None) -> tuple[Path, dict]:
    vendor = work / "vendor/lsf"
    pins = (json.loads(read_file(work / "sdk-lock.json"))["toolchain"] if language == "rust"
            else tomllib.loads(read_file(vendor / "tools/toolchain.toml").decode()))
    if language == "rust":
        selected, materials = resolve_tools(pins, work, command.environment)
        command.environment["RUSTC"] = str(selected["rustc"])
        for name in ("cargo", "rustc"):
            if command.run(name + "-version", selected[name], "--version").split()[:2] != [name.encode(), b"1.97.1"]:
                raise ValueError("unreviewed authored Rust compiler:" + name)
        bindgen = Path(shutil.which("wit-bindgen", path=command.environment["PATH"]) or "missing-wit-bindgen").resolve(strict=True)
        if command.run("bindgen-version", bindgen, "--version").strip() != b"wit-bindgen-cli 0.62.0":
            raise ValueError("unreviewed authored Rust binding generator")
        binding_identity = file_identity(bindgen, "wit-bindgen")
        for name in ("bindings", "bindings-check"):
            command.run(name, bindgen, "rust", work / "wit", "--world", WORLD, "--generate-all", "--out-dir", output / name)
        bindings = snapshot(output / "bindings")
        if bindings != snapshot(output / "bindings-check"):
            raise ValueError("authored Rust binding drift")
        command.run("actual-authored-rust", selected["cargo"], "build", "--locked", "--release", "--lib", "--target", "wasm32-unknown-unknown")
        target = Path(command.environment.get("CARGO_TARGET_DIR", work / "target"))
        name = json.loads(read_file(work / "capsule-project.json"))["name"].replace("-", "_")
        component = output / "component.wasm"
        command.run("compose", selected["wasm-tools"], "component", "new", target / ("wasm32-unknown-unknown/release/" + name + ".wasm"), "-o", component)
        for material in materials:
            if file_identity(selected[material["name"]], material["name"]) != material:
                raise ValueError("authored Rust compiler changed during the build")
        if file_identity(bindgen, "wit-bindgen") != binding_identity:
            raise ValueError("authored Rust binding generator changed during the build")
        return component, {"tools": [*materials, binding_identity], "bindings": json.loads(inventory(bindings))}
    if language == "c":
        from tools.c_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", 900, sdk=vendor / "sdk/c-guest", platform=None, config=pins, commands=command)
        component, binding = compiler.compile([work / SOURCES[language]], work / "wit", WORLD, output / "compiled")
        from tools.c_guest.bindings import generate
        _, second = generate(compiler.run, work / "wit", WORLD, output / "bindings-check", platform=None)
        if second != binding:
            raise ValueError("authored C binding drift")
    elif language == "java":
        from tools.java_guest.compiler import Compiler
        if wasi_sdk is None:
            raise ValueError("authored Java requires its pinned --wasi-sdk")
        compiler = Compiler(output / "compiler", wasi_sdk, sdk=vendor / "sdk/java-guest", platform=vendor / "wit/platform", config=pins)
        component, binding = compiler.compile(work / "src", work / "wit", WORLD, output / "compiled")
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
    elif language == "go":
        from tools.go_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", vendor / "sdk/go-guest", command)
        component, binding = compiler.compile(work / "src", work / "wit", WORLD, output / "compiled")
    else:
        if tools is None:
            raise ValueError("authored managed guest requires --tools")
        if language == "typescript":
            from tools.typescript_guest.compiler import Compiler
            compiler = Compiler(tools, command, {name: read_file(vendor / "sdk/typescript-guest/tools" / name) for name in ("package.json", "package-lock.json")})
        elif language == "dotnet":
            from tools.dotnet_guest.compiler import Compiler
            compiler = Compiler(tools, command, vendor)
        else:
            raise ValueError("unknown transaction guest language")
        component, binding = compiler.compile(work, WORLD, output / "compiled")
    compiler.check_unchanged()
    details = {"bindings": binding}
    if hasattr(compiler, "materials"):
        details["tools"] = compiler.materials
    if hasattr(compiler, "records"):
        details["commands"] = compiler.records
    if hasattr(compiler, "before"):
        details["compilerClosureDigest"] = digest(json.dumps(compiler.before, sort_keys=True, separators=(",", ":")).encode())
    return component, details


def compile_guests(language: str, output: Path, *, tools: Path | None = None, wasi_sdk: Path | None = None) -> None:
    output = fresh(output)
    for variant in VARIANTS:
        current = fresh(output / variant)
        report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": language,
            "variant": variant, "evidenceKind": "authored-component-compiler", "status": "running",
            "compiled": False, "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
            "world": WORLD, "hostAbiDigest": json.loads(read_file(ROOT / "wit/host-abi-phase4-v1.json"))["digest"]}
        command = None
        try:
            work = authored_project(language, variant, current / "project")
            captured = snapshot(work)
            source = inventory(captured)
            (current / "source-inputs.json").write_bytes(source)
            report["sourceDigest"] = digest(source)
            owner = {"rust": "tools.rust_capsule_build", "c": "tools.c_capsule_build", "typescript": "tools.typescript_guest.build",
                     "go": "tools.go_capsule_build", "java": "tools.java_capsule_build", "dotnet": "tools.dotnet_guest.build"}[language]
            import importlib
            recipe = (*importlib.import_module(owner).RECIPE, "tools/compile_transaction_guests.py", "tools/transaction_guest_variants.py")
            recipe_inputs = inventory({name: read_file(ROOT / name) for name in recipe})
            (current / "recipe-inputs.json").write_bytes(recipe_inputs)
            report["recipeDigest"] = digest(recipe_inputs)
            archive = current / "source.tar.gz"
            with archive.open("xb") as retained, gzip.GzipFile(fileobj=retained, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as source_archive:
                    for name, raw in captured.items():
                        entry = tarfile.TarInfo(name)
                        entry.size, entry.mode = len(raw), 0o644
                        source_archive.addfile(entry, io.BytesIO(raw))
            report["sourceArchiveDigest"] = digest(read_file(archive, 32 * 1024 * 1024))
            report["companionDigest"] = digest(captured["transaction-binding.json"])
            command = Commands(work, current, build_environment(current), deadline_seconds=900)
            report["sourceRevision"] = command.run("source-revision", "git", "-C", ROOT, "rev-parse", "HEAD").decode().strip()
            report["workingTreeChanged"] = bool(command.run("source-status", "git", "-C", ROOT, "status", "--porcelain", "--untracked-files=normal").strip())
            # CARGO_TARGET_DIR is intentionally owner-local and shared by these
            # two authored guest projects, not the workspace or another session.
            command.environment["CARGO_TARGET_DIR"] = str(output / "rust-target")
            wasm = Path(shutil.which("wasm-tools", path=command.environment["PATH"]) or "missing-wasm-tools").resolve(strict=True)
            if command.run("validator-version", wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
                raise ValueError("unreviewed authored guest validator")
            expected = surface(json.loads(command.run("authored-wit", wasm, "component", "wit", work / "wit", "--json")), WORLD)
            component, details = compile_project(language, work, current, command, tools=tools, wasi_sdk=wasi_sdk)
            command.run("validate-authored-component", wasm, "validate", "--features", "all", component)
            actual = surface(json.loads(command.run("actual-component-wit", wasm, "component", "wit", component, "--json")))
            check_surface(expected, actual, variant)
            if any(read_file(work / name) != raw for name, raw in captured.items()):
                raise ValueError("captured guest source changed during compilation")
            if inventory({name: read_file(ROOT / name) for name in recipe}) != recipe_inputs:
                raise ValueError("authored compiler recipe changed during compilation")
            (current / "component.wit").write_bytes(command.run("retained-component-wit", wasm, "component", "wit", component))
            report.update(status="compiled", compiled=True, componentDigest=digest(read_file(component, 64 * 1024 * 1024)),
                          componentBytes=component.stat().st_size, actualImports=sorted(actual["imports"]), details=details)
        except BaseException as error:
            report.update(status="failed", reason=str(error))
            raise
        finally:
            if command is not None:
                report["commands"] = command.records
            write_json(current / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=LANGUAGES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tools", type=Path)
    parser.add_argument("--wasi-sdk", type=Path)
    arguments = parser.parse_args()
    compile_guests(arguments.language, arguments.output, tools=arguments.tools, wasi_sdk=arguments.wasi_sdk)


if __name__ == "__main__":
    main()
