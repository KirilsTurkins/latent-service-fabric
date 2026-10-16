#!/usr/bin/env python3
"""Capture C library inputs, then qualify source/archive components offline."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, c_capsule_project, c_dependency_controls, c_dependency_fixture
from tools import c_static_archive_build
from tools.build_observation import build_environment
from tools.c_dependency_authoring import build_inputs
from tools.dev_workflow.common import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_json, write_json

REPOSITORY = "https://github.com/KirilsTurkins/latent-service-fabric"
PRODUCTS = ("latent", "latentd", "package", "capsule_contracts", "capsule_authoring")


def project_identities(root: Path) -> dict:
    return {name: digest(inventory(build_inputs(root / "projects" / name)[0])) for name in TEMPLATES}


def capture(output: Path) -> dict:
    output = fresh(output)
    (output / "projects").mkdir(mode=0o700)
    result = {"schemaVersion": "latent.c-library-capture.v1", "status": "in-progress"}
    try:
        for name in TEMPLATES:
            c_capsule_project.create(output / "projects" / name, name)
        result["library"] = c_dependency_fixture.install(output / "projects/greeting", output / "originals")
        result.update(status="passed", projects=project_identities(output))
        write_json(output / "capture.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", reason=type(error).__name__)
        write_json(output / "CAPTURE-FAILED.json", result)
        raise


def captured(root: Path) -> dict:
    record = read_json(root / "capture.json")
    require(record.get("schemaVersion") == "latent.c-library-capture.v1" and record.get("status") == "passed"
            and set(record.get("projects", {})) == set(TEMPLATES), "c-library-complete-capture-required")
    require(record["projects"] == project_identities(root), "c-library-captured-project-changed")
    return record


def execute(inputs: Path, output: Path, native: Path, receipt: Path, installed: dict) -> dict:
    require(inputs != output and inputs not in output.parents and output not in inputs.parents,
            "c-library-distinct-capture-and-execution-owners")
    original = captured(inputs)
    binaries = {name: native / name for name in PRODUCTS}
    observed = ordinary_tuple(receipt, binaries)
    output = fresh(output)
    selected = output / "selected-native"
    selected.mkdir(mode=0o700)
    for name, path in binaries.items():
        shutil.copyfile(path, selected / name)
        (selected / name).chmod(0o700)
    binaries = {name: selected / name for name in PRODUCTS}
    require(ordinary_tuple(receipt, binaries) == observed, "c-library-native-capture-changed")
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=900, command_seconds=300)
    result = {"schemaVersion": "latent.c-library-ingestion.v1", "status": "in-progress",
        "scope": "actual-source-and-static-library-components-on-ordinary-signed-node",
        "nativeTuple": observed, "capture": file_identity(inputs / "capture.json"),
        "library": original["library"], "builds": {}, "releasePublication": False}
    recipe = {name: file_identity(ROOT / name) for name in c_capsule_build.RECIPE}
    stage = "source-components"
    try:
        artifacts = []
        for name in TEMPLATES:
            artifact = c_capsule_build.build(inputs / "projects" / name, output / ("build-" + name),
                binaries["capsule_contracts"], binaries["package"], REPOSITORY, installed=installed)
            artifacts.append(artifact)
            result["builds"][name] = read_json(artifact / "BUILD-COMPLETE.json")
            require(time.monotonic() < commands.deadline, "c-library-original-overall-deadline")
        stage = "offline-rebuild"
        rebuilt = c_capsule_build.build(inputs / "projects/greeting", output / "build-greeting-offline",
            binaries["capsule_contracts"], binaries["package"], REPOSITORY, installed=installed)
        first, second = (read_json(path / "BUILD-COMPLETE.json") for path in (artifacts[0], rebuilt))
        require(all(first[key] == second[key] for key in ("sourceDigest", "sdkBindingDigest")),
                "c-library-offline-source-or-sdk-drift")
        result["offlineRebuild"] = {"receipt": file_identity(rebuilt / "BUILD-COMPLETE.json"),
            "sameComponentBytes": file_identity(artifacts[0] / "component.wasm") == file_identity(rebuilt / "component.wasm")}
        stage = "source-node"
        commands.run("sign-source", binaries["capsule_authoring"], "demo-sign", output / "signed-source", *artifacts)
        source = node_workflow(binaries["latent"], binaries["latentd"], output / "signed-source", output / "node-source", language="c")
        result["sourceExecution"] = {"status": source["status"], "invocations": len(source["invocations"]),
            "receipt": file_identity(output / "node-source/workflow.json")}
        stage = "source-static-archive"
        archive = c_static_archive_build.build(inputs / "projects/greeting", output / "static-library", REPOSITORY, installed=installed)
        static_project = output / "static-project"
        shutil.copytree(inputs / "projects/greeting", static_project)
        result["staticLibrary"] = c_dependency_fixture.use_static_archive(static_project, archive / "library.a",
            read_json(archive / "archive-profile.json"), output / "original-static-inputs",
            library_identity="outside-independent-c-library/2026.10")
        static = c_capsule_build.build(static_project, output / "build-greeting-static", binaries["capsule_contracts"],
            binaries["package"], REPOSITORY, installed=installed)
        result["builds"]["greeting-static"] = read_json(static / "BUILD-COMPLETE.json")
        stage = "static-node"
        commands.run("sign-static", binaries["capsule_authoring"], "demo-sign", output / "signed-static", static, *artifacts[1:])
        static_result = node_workflow(binaries["latent"], binaries["latentd"], output / "signed-static", output / "node-static", language="c")
        result["staticExecution"] = {"status": static_result["status"], "invocations": len(static_result["invocations"]),
            "receipt": file_identity(output / "node-static/workflow.json")}
        stage = "adversarial-object-and-generator-controls"
        negatives = c_dependency_controls.qualify(static_project, output / "negative-controls",
            binaries["capsule_contracts"], binaries["package"], installed=installed)
        result["controls"] = {"status": negatives["status"], "count": len(negatives["controls"]),
            "receipt": file_identity(output / "negative-controls/CONTROLS-COMPLETE.json")}
        stage = "final-integrity"
        require(captured(inputs) == original, "c-library-inputs-changed-during-qualification")
        require(recipe == {name: file_identity(ROOT / name) for name in c_capsule_build.RECIPE}, "c-library-recipe-changed")
        require(ordinary_tuple(receipt, binaries) == observed, "c-library-native-products-changed")
        require(time.monotonic() < commands.deadline, "c-library-original-overall-deadline")
        result.update(status="passed", recipe=recipe, commands=commands.records)
        write_json(output / "qualification.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", stage=stage, reason=type(error).__name__, commands=commands.records)
        write_json(output / "FAILED.json", result)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("capture", help="Explicitly acquire and close source/library inputs")
    prepare.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("execute", help="Build/sign/execute captured inputs without resolving dependencies")
    for name in ("inputs", "output", "native-directory", "native-tuple", "zig", "wit-bindgen", "wasm-tools"):
        run.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    require(args.output.is_absolute() and args.output != ROOT and ROOT not in args.output.parents,
            "c-library-outside-checkout-output-required")
    if args.command == "capture":
        capture(args.output)
    else:
        execute(args.inputs.resolve(strict=True), args.output,
            args.native_directory.resolve(strict=True), args.native_tuple.resolve(strict=True),
            {name: getattr(args, name.replace("-", "_")).resolve(strict=True) for name in ("zig", "wit-bindgen", "wasm-tools")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
