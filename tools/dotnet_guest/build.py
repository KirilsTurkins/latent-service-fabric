"""Observe the actual editable C# project, compiler closure and package inputs."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import time
from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools import guest_compatibility_build
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
    read_file, read_json, snapshot, write_json)
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import validate
from tools.application_dependencies import prepare, verify_inputs
from tools.application_dependency_approval import request as execution_request, approve as approve_execution
from tools.build_snapshot import canonical

BUILD_TYPE = "https://latent.dev/build/dotnet-capsule/v1"
RECIPE = ("tools/dotnet_capsule.py", "tools/dotnet_guest/project.py", "tools/dotnet_guest/build.py",
    "tools/dotnet_guest/compiler.py", "tools/dotnet_guest/composer.py", "tools/dotnet_guest/compatibility.py", "tools/dotnet_guest/sdk.py", "tools/dotnet_guest_bindings.py",
    "tools/rust_capsule_project.py", "tools/rust_capsule_build.py", "tools/build_observation.py",
    "tools/build_process.py", "tools/build_process_linux.py", "tools/build_process_windows.py",
    "tools/build_process_signals.py", "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
    "examples/echo-contract/deployment.json")
RECIPE += ('tools/application_dependencies.py', 'tools/application_dependency_store.py', 'tools/application_dependency_tools.py',
           'tools/application_dependency_approval.py', 'tools/captured_compiler_isolation.py', 'tools/dotnet_compiler_isolation.py',
           'tools/dotnet_application_dependencies.py')
RECIPE += guest_compatibility_build.RECIPE


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None, repository: str,
          *, tools: Path, offline: bool = False, executable_approval: str | None = None):
    project_path, output, tools = map(checked_path, (project_path, output, tools))
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    if tools == project_path or tools in project_path.parents or project_path in tools.parents:
        raise ValueError("compiler installation must be separate from captured application sources")
    repository, output = public_repository(repository), fresh(output)
    commands, stage = None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        files = snapshot(project_path)
        project, lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe = inventory({name: read_file(ROOT / name) for name in RECIPE})
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe)
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-capsule-") as owned:
            temporary, work = Path(owned), Path(owned) / "project"
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            commands = Commands(work, output, build_environment(temporary))
            paths = {"contracts-tool": checked_path(contracts_tool)}
            if packager is not None:
                paths["packager"] = checked_path(packager)
            materials = [file_identity(path, name) for name, path in paths.items()]
            stage = "contracts"
            # Public RPC resources and other unsupported contracts fail before
            # compiler work. Imported capability resources remain authoritative.
            wit_input = temporary / "wit-inputs.json"
            write_json(wit_input, {"world": project["world"], "sources": [
                {"path": name, "content": data.decode()} for name, data in files.items() if name.startswith("wit/") and name.endswith(".wit")]})
            derived = temporary / "derived"
            commands.run("contracts", paths["contracts-tool"], wit_input, derived)
            for name in ("contracts.json", "wit-lock.json", "surface.json"):
                (output / name).write_bytes(read_file(derived / name))
            stage = "compiler-inputs"
            verified = verify_inputs(project_path, 'dotnet')
            compiler = Compiler(tools, commands, work / "vendor/lsf", offline=offline, captured=verified is not None)
            write_json(output / "compiler-inputs.json", compiler.before)
            materials.extend(compiler.materials)
            write_json(output / 'compiler-patches.json', {'formatVersion': 1, 'patches': compiler.compiler_patches})
            patch_identity = read_file(output / 'compiler-patches.json')
            materials.append({'name': 'automatic-compiler-patches', 'digest': digest(patch_identity), 'size': len(patch_identity)})
            closure, approval = None, None
            if verified is not None:
                write_json(output / 'compiler-containment.json', compiler.isolation.receipt)
                if verified.lock['executableInputs']:
                    stage = 'executable-input-approval'
                    executable_recipe = digest(canonical({'recipe': digest(recipe), 'sourceSnapshot': digest(source_inputs)}))
                    requested = execution_request(verified, compiler.isolation, executable_recipe)
                    write_json(output / 'executable-input-approval-request.json', {
                        'formatVersion': 1, 'identity': digest(canonical(requested)), 'specification': requested})
                    if executable_approval is None:
                        raise ValueError('captured NuGet targets/analyzers require the exact retained executable-input approval identity')
                    approval = approve_execution(verified, compiler.isolation, executable_recipe, executable_approval)
                closure = prepare(project_path, work, output, 'dotnet', execution_approval=approval)
                compiler.application_closure = closure
            stage = "compile"
            write_json(output / "diagnostic-source.json", {
                "capturedSource": str(temporary / "compiled/project/src"),
                "requestedSource": str(project_path / "src")})
            component_path, generated = compiler.compile(work, project["world"], temporary / "compiled")
            component = read_file(component_path, 64 * 1024 * 1024)
            (output / "component.wasm").write_bytes(component)
            write_json(output / "bindings.json", generated)
            surface = read_json(derived / "surface.json")
            stage = "compatibility"
            guest_compatibility_build.inspect(commands, compiler.wasm, output, surface)
            package_inputs(output, project, surface, files, component)
            if packager is not None:
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                commands.run("inspect", paths["packager"], "inspect", output / "package")
            stage = "recheck"
            if snapshot(project_path) != files or snapshot(work, exclude=('dependencies', 'application-vendor') if closure else ()) != files:
                raise ValueError("captured C# project changed during compilation")
            if inventory({name: read_file(ROOT / name) for name in RECIPE}) != recipe:
                raise ValueError("C# authoring recipe changed during compilation")
            compiler.check_unchanged()
            if closure:
                closure.check_unchanged()
                write_json(output / 'compiler-namespace-arguments.json', {'formatVersion': 1,
                    'commands': compiler.isolation.executed_arguments(), 'format': 'nul-separated-bubblewrap-options-v1'})
                for name in ('application-dependencies.json', 'compiler-containment.json', 'nuget-build-inputs.json', 'compiler-namespace-arguments.json'):
                    data = read_file(output / name, 32 * 1024 * 1024)
                    materials.append({'name': name.removesuffix('.json'), 'digest': digest(data), 'size': len(data)})
                if approval:
                    from tools.application_dependency_store import directory_files
                    generated_outputs = directory_files(temporary / 'compiled/generator-outputs') if (temporary / 'compiled/generator-outputs').exists() else {}
                    if len(generated_outputs) > 8192 or sum(len(data) for data in generated_outputs.values()) > 64 * 1024 * 1024:
                        raise ValueError('NuGet-executable-generated-output-limit')
                    write_json(output / 'executable-input-outputs.json', {'formatVersion': 1, 'approvalIdentity': approval.identity,
                        'outputs': {name: {'digest': digest(data), 'size': len(data)} for name, data in generated_outputs.items()},
                        'cleanup': 'namespace-and-owned-process-reaped', 'hermetic': False})
                    data = read_file(output / 'executable-input-outputs.json', 32 * 1024 * 1024)
                    materials.append({'name': 'executable-input-outputs', 'digest': digest(data), 'size': len(data)})
            if any(file_identity(path, name) not in materials for name, path in paths.items()):
                raise ValueError("packaging binary changed during compilation")
            package_files = {"package-source.json": read_file(output / "package-source.json")}
            for layer in read_json(output / "package-source.json")["layers"]:
                package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
            package_inventory = inventory(package_files)
            (output / "package-inputs.json").write_bytes(package_inventory)
            materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                ("source-snapshot", source_inputs), ("build-recipe", recipe), ("package-inputs", package_inventory),
                ("compiler-inputs", read_file(output / "compiler-inputs.json", 32 * 1024 * 1024)),
                ("closed-runtime-coverage", read_file(output / "closed-runtime-coverage.json", 4 * 1024 * 1024)),
                ("dependency-lock", files["vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json"]),
                ("toolchain-config", files["global.json"])))
            finished = int(time.time())
            if finished < started or finished - started > 900 or time.monotonic() - start > 900:
                raise ValueError("compiler observation deadline or clock invalid")
            write_json(output / "build-observation.json", {"formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(source_inputs)[7:], "snapshotDigest": digest(source_inputs),
                           "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda row: row["name"]),
                "parameters": {"compiler": "native-aot-llvm", "bindings": "wit-bindgen-csharp", "language": "csharp",
                               "target": "wasi-wasm", "runtime": "native-aot", "locked": True, "ambientWasi": False},
                "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                "dependencyCompleteness": "declared-inputs-incomplete"})
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1,
                "packageAssembled": packager is not None,
                "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                "componentDigest": digest(component), "sdkBindingDigest": generated["filesDigest"],
                "buildSeconds": round(time.monotonic() - start, 6), "commands": commands.records})
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": commands.records if commands else []})
        guest_compatibility_build.failure_report(output, "dotnet", stage)
        try:
            from tools.dotnet_guest.compatibility import retain_failure
            retain_failure(output)
        except Exception:
            pass  # A failed diagnostic must preserve the original compiler error.
        raise
