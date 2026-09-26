"""Observe one actual Go source build; never sign, execute or grant authority."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools.go_guest.compiler import Compiler
from tools.go_capsule_project import validate
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
                                        read_file, read_json, snapshot, write_json)

BUILD_TYPE = "https://latent.dev/build/go-capsule/v1"
RECIPE = ("tools/go_capsule.py", "tools/go_capsule_project.py", "tools/go_capsule_build.py",
          "tools/go_guest/compiler.py", "tools/go_guest/runtime.py", "tools/go_guest/sdk.py", "tools/rust_capsule_project.py",
          "tools/rust_capsule_build.py", "tools/build_observation.py", "tools/build_process.py",
          "tools/build_process_linux.py", "tools/build_process_windows.py", "tools/build_process_signals.py",
          "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
          "examples/echo-contract/deployment.json")


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None, repository: str,
          *, offline_cache: Path | None = None) -> Path:
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
        with tempfile.TemporaryDirectory(prefix="lsf-go-capsule-") as owned:
            temporary = Path(owned)
            work = temporary / "project"
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            commands = Commands(work, output, build_environment(temporary))
            compiler = Compiler(temporary / "compiler", work / "vendor/lsf/sdk/go-guest", commands,
                                offline_cache=offline_cache, source_root=project_path / "src")
            materials = list(compiler.materials.values())
            paths = {"contracts-tool": checked_path(contracts_tool)}
            if packager is not None:
                paths["packager"] = checked_path(packager)
            materials.extend(file_identity(path, name) for name, path in paths.items())
            stage = "compile"
            component_path, generated = compiler.compile(work / "src", work / "wit", project["world"], temporary / "compiled")
            binding_digest = digest(json.dumps(generated, sort_keys=True, separators=(",", ":")).encode())
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
                raise ValueError("project changed during the observed Go build")
            if inventory({path: read_file(ROOT / path) for path in RECIPE}) != recipe_inputs:
                raise ValueError("Go authoring recipe changed during the build")
            compiler.check_unchanged()
            for name, path in paths.items():
                if file_identity(path, name) not in materials:
                    raise ValueError("packaging binary changed during the Go build")
            package_files = {"package-source.json": read_file(output / "package-source.json")}
            for layer in read_json(output / "package-source.json")["layers"]:
                package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
            package_inventory = inventory(package_files)
            (output / "package-inputs.json").write_bytes(package_inventory)
            materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                ("source-snapshot", source_inputs), ("build-recipe", recipe_inputs), ("package-inputs", package_inventory),
                ("toolchain-config", files["vendor/lsf/sdk/go-guest/toolchain.lock.json"]),
                ("dependency-lock", files["vendor/lsf/sdk/go-guest/runtime-deps/dependencies.lock.json"])))
            finished = int(time.time())
            if finished < started or finished - started > 900 or time.monotonic() - start > 900:
                raise ValueError("Go build clock or overall deadline invalid")
            write_json(output / "build-observation.json", {"formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(source_inputs)[7:], "snapshotDigest": digest(source_inputs),
                           "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda row: row["name"]),
                "parameters": {"goPackage": project["name"], "compiler": "componentize-go", "target": "wasm32-wasip1",
                               "runtime": "go-component-async-v1", "locked": True, "ambientWasi": False},
                "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                "dependencyCompleteness": "declared-inputs-incomplete"})
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1, "packageAssembled": packager is not None,
                "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                "componentDigest": digest(component), "sdkBindingDigest": binding_digest,
                "buildSeconds": round(time.monotonic() - start, 6), "commands": commands.records})
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": commands.records if commands else []})
        raise
