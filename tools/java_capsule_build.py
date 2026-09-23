"""Capture, compile and package actual Java source; never sign or grant authority."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools.java_capsule_project import validate
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
                                        read_file, read_json, snapshot, write_json)

BUILD_TYPE = "https://latent.dev/build/java-capsule/v1"
RECIPE = ("tools/java_capsule.py", "tools/java_capsule_project.py", "tools/java_capsule_build.py",
          "tools/java_guest/compiler.py", "tools/java_guest/bindings.py", "tools/java_guest/model.py",
          "tools/java_guest/java.py", "tools/java_guest/c.py", "tools/java_guest/lock.py", "tools/java_guest/surface.py", "tools/rust_capsule_project.py",
          "tools/rust_capsule_build.py", "tools/build_observation.py", "tools/build_process.py",
          "tools/build_process_linux.py", "tools/build_process_windows.py", "tools/build_process_signals.py",
          "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
          "examples/echo-contract/deployment.json")


def retain_logs(source: Path, output: Path) -> None:
    target = output / "compiler-logs"
    target.mkdir(exist_ok=True)
    total = 0
    for path in sorted(source.glob("*.log")):
        data = read_file(path)
        total += len(data)
        if total > 16 * 1024 * 1024: raise ValueError("Java compiler log retention exceeded")
        with (target / path.name).open("xb") as retained: retained.write(data)


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path,
          repository: str, wasi_sdk: Path, *, gradle="gradle", timeout=900) -> Path:
    if type(timeout) not in {int, float} or not 0 < timeout <= 900:
        raise ValueError("Java build deadline must be positive and at most 900 seconds")
    project_path, output = checked_path(project_path), checked_path(output)
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    repository = public_repository(repository)
    output = fresh(output)
    commands, compiler, stage = None, None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        files = snapshot(project_path)
        project, _lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe_inputs = inventory({path: read_file(ROOT / path) for path in RECIPE})
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe_inputs)
        with tempfile.TemporaryDirectory(prefix="lsf-java-capsule-") as owned:
            temporary, compiler_dir = Path(owned), Path(owned) / "compiler"
            try:
                work = temporary / "project"
                for name, data in files.items():
                    path = work / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                commands = Commands(work, output, build_environment(temporary))
                commands.deadline = start + timeout
                stage = "compiler-inputs"
                compiler = Compiler(compiler_dir, checked_path(wasi_sdk), gradle=gradle,
                    sdk=work / "vendor/lsf/sdk/java-guest", platform=work / "vendor/lsf/wit/platform",
                    config=pins, timeout=timeout - (time.monotonic() - start))
                (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
                materials = list(compiler.materials)
                paths = {"contracts-tool": checked_path(contracts_tool), "packager": checked_path(packager)}
                materials.extend(file_identity(path, name) for name, path in paths.items())
                stage = "compile"
                component_path, generated = compiler.compile(work / "src", work / "wit", project["world"], temporary / "compiled")
                component = read_file(component_path, 64 * 1024 * 1024)
                (output / "component.wasm").write_bytes(component)
                write_json(output / "bindings.json", generated)
                bindings_dir = output / "generated-bindings"
                bindings_dir.mkdir()
                for path in sorted((temporary / "compiled/bindings").iterdir()):
                    (bindings_dir / path.name).write_bytes(read_file(path))
                stage = "contracts"
                # Include the selected world, closed adapter world and the exact
                # staged dependency sources used by the compiler/ABI generator.
                wit_files = snapshot(temporary / "compiled/wit")
                wit_input = temporary / "wit-inputs.json"
                write_json(wit_input, {"world": project["world"], "sources": [
                    {"path": "wit/" + path, "content": data.decode()} for path, data in wit_files.items() if path.endswith(".wit")]})
                derived = temporary / "derived"
                commands.run("contracts", paths["contracts-tool"], wit_input, derived)
                for name in ("contracts.json", "wit-lock.json", "surface.json"):
                    (output / name).write_bytes(read_file(derived / name))
                package_files = dict(files)
                package_files.update({"wit/" + path: data for path, data in wit_files.items()})
                package_inputs(output, project, read_json(derived / "surface.json"), package_files, component)
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                commands.run("inspect", paths["packager"], "inspect", output / "package")
                stage = "recheck"
                if snapshot(project_path) != files or snapshot(work) != files:
                    raise ValueError("project changed during the observed Java build")
                if inventory({path: read_file(ROOT / path) for path in RECIPE}) != recipe_inputs:
                    raise ValueError("Java authoring recipe changed during the build")
                compiler.check_unchanged()
                for name, path in paths.items():
                    if file_identity(path, name) not in materials:
                        raise ValueError("packaging binary changed during the Java build")
                package_files = {"package-source.json": read_file(output / "package-source.json")}
                for layer in read_json(output / "package-source.json")["layers"]:
                    package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
                package_inventory = inventory(package_files)
                (output / "package-inputs.json").write_bytes(package_inventory)
                materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                    ("source-snapshot", source_inputs), ("build-recipe", recipe_inputs), ("package-inputs", package_inventory),
                    ("toolchain-config", files["vendor/lsf/tools/toolchain.toml"]), ("compiler-closure", compiler.compiler_inputs),
                    ("dependency-lock", files["vendor/lsf/sdk/java-guest/feasibility/dependencies.lock.json"]),
                    ("generated-bindings", read_file(output / "bindings.json"))))
                finished = int(time.time())
                if finished < started or finished - started > 900 or time.monotonic() - start > timeout:
                    raise ValueError("Java build clock or overall deadline invalid")
                write_json(output / "build-observation.json", {"formatVersion": 1, "buildType": BUILD_TYPE,
                    "source": {"repository": repository, "revision": digest(source_inputs)[7:], "snapshotDigest": digest(source_inputs),
                               "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                    "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda row: row["name"]),
                    "parameters": {"compiler": "teavm-c", "entryPoint": "dev.latent.app.Capsule", "target": "wasm32-wasip1",
                                   "bindings": "lsf-java-wit-v1", "optimization": "O2", "javaHeapBytes": 4_194_304},
                    "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                    "dependencyCompleteness": "declared-inputs-incomplete"})
                write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1,
                    "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                    "componentDigest": digest(component), "sdkBindingDigest": generated["bindings"]["digest"],
                    "buildSeconds": round(time.monotonic() - start, 6), "commands": compiler.records + commands.records})
            finally:
                if compiler_dir.is_dir(): retain_logs(compiler_dir, output)
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": (compiler.records if compiler else []) + (commands.records if commands else [])})
        raise
