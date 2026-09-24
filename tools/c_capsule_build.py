"""Observe one actual C source build; never sign, execute or grant authority."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools.c_guest.compiler import Compiler
from tools.c_capsule_project import validate
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
                                        read_file, read_json, snapshot, write_json)
from tools.stage_runtime_wit import copy_wit_tree, dependencies

BUILD_TYPE = "https://latent.dev/build/c-guest/v1"
RECIPE = ("tools/c_capsule.py", "tools/c_capsule_project.py", "tools/c_capsule_build.py",
          "tools/c_guest/compiler.py", "tools/c_guest/bindings.py", "tools/rust_capsule_project.py",
          "tools/rust_capsule_build.py", "tools/build_observation.py", "tools/build_process.py",
          "tools/build_process_linux.py", "tools/build_process_windows.py", "tools/build_process_signals.py",
          "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
          "examples/echo-contract/deployment.json")


def binding_check(work: Path, lock: dict, commands: Commands, generator: Path) -> str:
    platform = work / "vendor/lsf/wit/platform"
    source, staged = platform / "runtime-phase3-blobs", work.parent / "binding-wit"
    copy_wit_tree(source, staged)
    for package in dependencies(source, platform):
        copy_wit_tree(package, staged / "deps" / package.name)
    output = work.parent / "sdk-bindings"
    commands.run("sdk-bindings", generator, "c", staged, "--out-dir", output)
    actual = {"c/" + path.name: digest(read_file(path)) for path in sorted(output.iterdir())}
    expected = {name: value for name, value in lock["bindings"]["outputs"].items() if name.startswith("c/")}
    if actual != expected or len(actual) != 3:
        raise ValueError("generated C SDK binding drift; review WIT and generator pins")
    return digest(inventory({path.name: read_file(path) for path in output.iterdir()}))


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None, repository: str,
          *, installed: dict[str, Path] | None = None) -> Path:
    project_path, output = checked_path(project_path), checked_path(output)
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    repository = public_repository(repository)
    output = fresh(output)
    commands, stage = None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        files = snapshot(project_path)
        project, lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe_inputs = inventory({path: read_file(ROOT / path) for path in RECIPE})
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe_inputs)
        with tempfile.TemporaryDirectory(prefix="lsf-c-capsule-") as owned:
            temporary = Path(owned)
            work = temporary / "project"
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            commands = Commands(work, output, build_environment(temporary))
            if packager is None:
                write_json(output / "diagnostic-source.json", {"capturedSource": str(work), "requestedSource": str(project_path)})
            compiler = Compiler(temporary / "compiler", 900, sdk=work / "vendor/lsf/sdk/c-guest",
                                platform=None, config=pins, commands=commands, installed=installed)
            materials = list(compiler.materials.values())
            paths = {"contracts-tool": checked_path(contracts_tool)}
            if packager is not None:
                paths["packager"] = checked_path(packager)
            materials.extend(file_identity(path, name) for name, path in paths.items())
            stage = "binding-drift"
            binding_digest = binding_check(work, lock, commands, compiler.paths["wit-bindgen"])
            stage = "compile"
            sources = [work / name for name in files if name.startswith("src/") and name.endswith(".c")]
            component_path, generated = compiler.compile(sources, work / "wit", project["world"], temporary / "compiled",
                                                          memory_bytes=64 * 1024 * 1024)
            component = read_file(component_path, 64 * 1024 * 1024)
            (output / "component.wasm").write_bytes(component)
            write_json(output / "bindings.json", generated)
            stage = "contracts"
            wit_input = temporary / "wit-inputs.json"
            write_json(wit_input, {"world": project["world"], "sources": [
                {"path": path, "content": data.decode()} for path, data in files.items() if path.startswith("wit/") and path.endswith(".wit")]})
            derived = temporary / "derived"
            commands.run("contracts", paths["contracts-tool"], wit_input, derived)
            for name in ("contracts.json", "wit-lock.json", "surface.json"):
                (output / name).write_bytes(read_file(derived / name))
            package_inputs(output, project, read_json(derived / "surface.json"), files, component)
            if packager is not None:
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                commands.run("inspect", paths["packager"], "inspect", output / "package")
            stage = "recheck"
            if snapshot(project_path) != files or snapshot(work) != files:
                raise ValueError("project changed during the observed C build")
            if inventory({path: read_file(ROOT / path) for path in RECIPE}) != recipe_inputs:
                raise ValueError("C authoring recipe changed during the build")
            compiler.check_unchanged()
            for name, path in paths.items():
                if file_identity(path, name) not in materials:
                    raise ValueError("packaging binary changed during the C build")
            package_files = {"package-source.json": read_file(output / "package-source.json")}
            for layer in read_json(output / "package-source.json")["layers"]:
                package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
            package_inventory = inventory(package_files)
            (output / "package-inputs.json").write_bytes(package_inventory)
            materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                ("source-snapshot", source_inputs), ("build-recipe", recipe_inputs), ("package-inputs", package_inventory),
                ("toolchain-config", files["vendor/lsf/tools/toolchain.toml"])))
            finished = int(time.time())
            if finished < started or finished - started > 900 or time.monotonic() - start > 900:
                raise ValueError("C build clock or overall deadline invalid")
            write_json(output / "build-observation.json", {"formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(source_inputs)[7:], "snapshotDigest": digest(source_inputs),
                           "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda row: row["name"]),
                "parameters": {"compiler": "zig-cc", "fixture": "application", "target": "wasm32-wasi", "optimization": "O2"},
                "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                "dependencyCompleteness": "declared-inputs-incomplete"})
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1,
                "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                "componentDigest": digest(component), "sdkBindingDigest": binding_digest,
                "buildSeconds": round(time.monotonic() - start, 6), "packageAssembled": packager is not None, "commands": commands.records})
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": commands.records if commands else []})
        raise
