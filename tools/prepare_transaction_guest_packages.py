#!/usr/bin/env python3
"""Prepare real observed packages for the six-language native transaction gate.

Each variant delegates to its maintained complete build owner. The original
compiler logs, source/recipe/package inventories and BuildObservation remain
unchanged. This tool neither creates signing keys nor asserts node execution.
"""
from __future__ import annotations

import argparse
import gzip
import importlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.compile_transaction_guests import VARIANTS, WORLD, authored_project, check_surface
from tools.java_guest.surface import surface
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import (ROOT, MAX_SOURCE, checked_path, digest, fresh,
                                        inventory, read_file, read_json, snapshot, write_json)
from tools.transaction_guest_variants import LANGUAGES

REPOSITORY = "https://github.com/KirilsTurkins/latent-service-fabric"
OWNERS = {"rust": "tools.rust_capsule_build", "c": "tools.c_capsule_build",
          "typescript": "tools.typescript_guest.build", "go": "tools.go_capsule_build",
          "java": "tools.java_capsule_build", "dotnet": "tools.dotnet_guest.build"}


def verify_observation(project: Path, built: Path, build_type: str,
                       binaries: list[dict]) -> tuple[dict, bytes]:
    """Verify retained original observations, never fill missing builder facts."""
    marker = read_json(built / "BUILD-COMPLETE.json")
    raw = read_file(built / "build-observation.json", 65536)
    observation = read_json(built / "build-observation.json")
    component = read_file(built / "component.wasm", 64 * 1024 * 1024)
    inputs = read_file(built / "source-inputs.json")
    if (marker.get("formatVersion") != 1 or marker.get("packageAssembled") is not True
            or marker.get("observationDigest") != digest(raw)
            or marker.get("sourceDigest") != digest(inputs)
            or marker.get("componentDigest") != digest(component)
            or observation.get("formatVersion") != 1 or observation.get("buildType") != build_type
            or observation.get("componentDigest") != digest(component)
            or observation.get("componentSize") != len(component)
            or inventory(snapshot(project)) != inputs):
        raise ValueError("incomplete or changed observed transaction build")
    source = observation.get("source", {})
    if (source.get("snapshotDigest") != digest(inputs) or source.get("repository") != REPOSITORY
            or source.get("revision") != digest(inputs)[7:]
            or source.get("repositoryTrust") != "operator-asserted"
            or source.get("capture") != "explicit-input-files"):
        raise ValueError("transaction build source identity changed")
    materials = observation.get("materials", [])
    if (not isinstance(materials, list) or len(materials) > 64
            or len({row["name"] for row in materials}) != len(materials)):
        raise ValueError("ambiguous transaction build materials")
    files = {"package-source.json": read_file(built / "package-source.json")}
    package = read_json(built / "package-source.json")
    if not isinstance(package.get("layers"), list) or not 1 <= len(package["layers"]) <= 128:
        raise ValueError("bounded transaction package inputs required")
    total = 0
    for layer in package["layers"]:
        name = layer["source"]
        path = checked_path(built / name)
        if not path.is_relative_to(checked_path(built)) or name in files:
            raise ValueError("escaping or duplicate transaction package input")
        files[name] = read_file(path, 64 * 1024 * 1024)
        total += len(files[name])
        if total > 128 * 1024 * 1024:
            raise ValueError("transaction package input byte limit")
    package_inputs = read_file(built / "package-inputs.json")
    if inventory(files) != package_inputs:
        raise ValueError("transaction package inputs changed after observation")
    retained = (("source-snapshot", inputs), ("build-recipe", read_file(built / "recipe-inputs.json")),
                ("package-inputs", package_inputs))
    expected = [*binaries, *({"name": name, "digest": digest(data), "size": len(data)}
                            for name, data in retained)]
    if any(row not in materials for row in expected):
        raise ValueError("missing original transaction build material")
    return observation, component


def observed_build(language: str, project: Path, output: Path, contracts_tool: Path,
                   packager: Path, *, tools: Path | None, wasi_sdk: Path | None,
                   offline: bool, rust_bin: Path | None, host_linker: Path | None,
                   go_cache: Path | None, gradle_cache: Path | None) -> Path:
    owner = importlib.import_module(OWNERS[language])
    options = {}
    if language in {"typescript", "dotnet"}:
        if tools is None:
            raise ValueError("managed transaction preparation requires --tools")
        options["tools"] = tools
    if language == "rust":
        options.update(offline=offline, rust_bin=rust_bin, host_linker=host_linker)
    elif language == "dotnet":
        options["offline"] = offline
    elif language == "go":
        options["offline_cache"] = go_cache
    elif language == "java":
        if wasi_sdk is None:
            raise ValueError("Java transaction preparation requires --wasi-sdk")
        options.update(wasi_sdk=wasi_sdk, offline_cache=gradle_cache)
    return owner.build(project, output, contracts_tool, packager, REPOSITORY, **options)


def prepare(language: str, output: Path, contracts_tool: Path, packager: Path, *,
            tools: Path | None = None, wasi_sdk: Path | None = None, offline: bool = False,
            rust_bin: Path | None = None, host_linker: Path | None = None,
            go_cache: Path | None = None, gradle_cache: Path | None = None) -> None:
    if language not in LANGUAGES:
        raise ValueError("unknown transaction guest language")
    if language in {"typescript", "dotnet"} and tools is None or language == "java" and wasi_sdk is None:
        raise ValueError("selected transaction compiler requires its explicit tool prefix")
    binaries = [file_identity(checked_path(path), name)
                for name, path in (("contracts-tool", contracts_tool), ("packager", packager))]
    output = fresh(output)
    fresh(output / "native-evidence")
    for variant in VARIANTS:
        current = fresh(output / variant)
        command = None
        report = {"schemaVersion": "latent.transaction-guest.preparation.v1", "language": language,
                  "variant": variant, "evidenceKind": "authored-observed-package", "world": WORLD,
                  "hostAbiDigest": read_json(ROOT / "wit/host-abi-phase4-v1.json")["digest"],
                  "status": "running", "compiled": False, "packageAssembled": False,
                  "signedNodeExecutionQualified": False, "admissionRejectionQualified": False}
        try:
            project = authored_project(language, variant, current / "project")
            captured = snapshot(project)
            source_inputs = inventory(captured)
            with (current / "source.tar.gz").open("xb") as retained:
                with gzip.GzipFile(fileobj=retained, mode="wb", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w") as archive:
                        for name, data in captured.items():
                            entry = tarfile.TarInfo(name)
                            entry.size, entry.mode = len(data), 0o644
                            archive.addfile(entry, io.BytesIO(data))
            report.update(sourceDigest=digest(source_inputs),
                          sourceArchiveDigest=digest(read_file(current / "source.tar.gz", MAX_SOURCE + 1024 * 1024)),
                          companionDigest=digest(captured["transaction-binding.json"]))
            command = Commands(project, current, build_environment(current), deadline_seconds=900)
            report["sourceRevision"] = command.run("source-revision", "git", "-C", ROOT, "rev-parse", "HEAD").decode().strip()
            report["workingTreeChanged"] = bool(command.run("source-status", "git", "-C", ROOT, "status", "--porcelain", "--untracked-files=normal").strip())
            wasm = Path(shutil.which("wasm-tools", path=command.environment["PATH"]) or "missing-wasm-tools").resolve(strict=True)
            wasm_identity = file_identity(wasm, "wasm-tools")
            if command.run("validator-version", wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
                raise ValueError("unreviewed transaction package validator")
            expected = surface(json.loads(command.run("authored-wit", wasm, "component", "wit", project / "wit", "--json")), WORLD)
            built = observed_build(language, project, current / "built", contracts_tool, packager,
                tools=tools, wasi_sdk=wasi_sdk, offline=offline, rust_bin=rust_bin,
                host_linker=host_linker, go_cache=go_cache, gradle_cache=gradle_cache)
            owner = importlib.import_module(OWNERS[language])
            observation, component = verify_observation(project, built, owner.BUILD_TYPE, binaries)
            command.run("validate-observed-component", wasm, "validate", "--features", "all", built / "component.wasm")
            actual = surface(json.loads(command.run("actual-component-wit", wasm, "component", "wit", built / "component.wasm", "--json")))
            check_surface(expected, actual, variant)
            if (snapshot(project) != captured or file_identity(wasm, "wasm-tools") != wasm_identity
                    or any(file_identity(checked_path(path), name) != identity for (name, path), identity in
                           zip((("contracts-tool", contracts_tool), ("packager", packager)), binaries, strict=True))):
                raise ValueError("transaction preparation input changed")
            (current / "component.wit").write_bytes(command.run("retained-component-wit", wasm, "component", "wit", built / "component.wasm"))
            report.update(status="prepared", compiled=True, packageAssembled=True,
                componentDigest=digest(component), componentBytes=len(component), buildType=observation["buildType"],
                buildObservationDigest=digest(read_file(built / "build-observation.json", 65536)),
                packageSourceDigest=digest(read_file(built / "package-source.json")), actualImports=sorted(actual["imports"]))
        except BaseException as error:
            report.update(status="failed", reason=str(error))
            raise
        finally:
            if command is not None:
                report["validationCommands"] = command.records
            write_json(current / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=LANGUAGES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--contracts-tool", required=True, type=Path)
    parser.add_argument("--packager", required=True, type=Path,
                        help="the checked transaction_package executable, not the stateless package tool")
    for name in ("tools", "wasi-sdk", "rust-bin", "host-linker", "go-cache", "gradle-cache"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--offline", action="store_true")
    arguments = parser.parse_args()
    prepare(**vars(arguments))


if __name__ == "__main__":
    main()
