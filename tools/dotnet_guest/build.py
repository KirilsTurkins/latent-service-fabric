"""Observe the actual editable C# project, compiler closure and package inputs."""
from __future__ import annotations

from tools import guest_compatibility_context_build
from tools.transaction_guest_project import packaging_arguments
import json
import math
from pathlib import Path
import tempfile
import time
from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools import guest_compatibility_build, guest_dependency_inputs, guest_resources
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
    "tools/dotnet_guest/compiler.py", "tools/dotnet_guest/runtime.py", "tools/dotnet_guest/composer.py",
    "tools/dotnet_guest/compatibility.py", "tools/dotnet_guest/entropy.py", "tools/dotnet_guest/outputs.py",
    "tools/dotnet_guest/managed_entropy.py", "tools/dotnet_guest/reachability.py",
    "tools/dotnet_guest/http_errors.py", "tools/dotnet_guest/task_wait.py", "tools/dotnet_guest/aggregate_task_wait.py", "tools/dotnet_guest/closed_filesystem.py", "tools/dotnet_guest/resources.py", "tools/dotnet_guest/sdk.py", "tools/dotnet_guest_bindings.py",
    "tools/dotnet_guest/async_exports.py",
    "tools/dotnet_guest/internal_io.py",
    "tools/dotnet_guest/closed_io.py",
    "tools/dotnet_guest/retirement.py",
    "tools/dotnet_guest/managed_work.py",
    "tools/rust_capsule_project.py", "tools/rust_capsule_build.py", "tools/build_observation.py",
    "tools/build_process.py", "tools/build_process_linux.py", "tools/build_process_windows.py",
    "tools/build_process_signals.py", "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
    "examples/echo-contract/deployment.json", "tools/transaction_guest_project.py",
    "tools/dev_workflow/common.py", "tools/dev_workflow/transaction_binding.py")
RECIPE += ('tools/application_dependencies.py', 'tools/application_dependency_store.py', 'tools/application_dependency_tools.py',
           'tools/application_dependency_approval.py', 'tools/captured_compiler_isolation.py', 'tools/dotnet_compiler_isolation.py',
           'tools/dotnet_application_dependencies.py', 'tools/dotnet_dependency_authoring.py', 'tools/dotnet_registry_tls.py')
RECIPE += guest_compatibility_build.RECIPE
RECIPE += guest_compatibility_context_build.RECIPE
RECIPE += guest_resources.RECIPE
RECIPE += guest_dependency_inputs.RECIPE


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None, repository: str,
          *, tools: Path, offline: bool = False, executable_approval: str | None = None,
          compiler_methods: bool = False, _deadline: float | None = None, _root_return_capture: tuple | None = None):
    if _deadline is not None and (type(_deadline) not in (int, float) or not math.isfinite(_deadline)
                                 or _deadline <= time.monotonic() + 5):
        raise ValueError('dotnet-build-original-owner-deadline')
    if _root_return_capture is not None and (type(_root_return_capture) is not tuple
            or len(_root_return_capture) != 2 or not all(callable(item) for item in _root_return_capture)):
        raise ValueError("dotnet-root-return-capture-selection")
    if type(compiler_methods) is not bool:
        raise ValueError('dotnet compiler method observations require an explicit boolean')
    project_path, output, tools = map(checked_path, (project_path, output, tools))
    project_path = guest_dependency_inputs.application_root(project_path, 'dotnet')
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    if tools == project_path or tools in project_path.parents or project_path in tools.parents:
        raise ValueError("compiler installation must be separate from captured application sources")
    repository, output = public_repository(repository), fresh(output)
    commands, stage = None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        observed = guest_dependency_inputs.capture_source(project_path, 'dotnet')
        files = observed.files
        project, lock, pins = validate(files)
        stage = "resource-inputs"
        guest_resources.select(files)
        source_inputs = inventory(files)
        recipe_files = {name: read_file(ROOT / name) for name in RECIPE}
        if _root_return_capture is not None:
            recipe_files["tools/dotnet_root_return.py"] = read_file(ROOT / "tools/dotnet_root_return.py")
        recipe = inventory(recipe_files)
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe)
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-capsule-") as owned:
            temporary, work = Path(owned), Path(owned) / "project"
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            commands = Commands(work, output, build_environment(temporary))
            if _deadline is not None:
                if _deadline <= time.monotonic() + 5:
                    raise ValueError('compiler-setup-consumed-parent-cleanup-reserve')
                commands.deadline = min(commands.deadline, _deadline - 5)
                commands._parent_deadline = _deadline
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
            surface = read_json(derived / "surface.json")
            recipe = guest_compatibility_build.capture_host_recipe(output, recipe_files, recipe, surface)
            stage = "compiler-inputs"
            verified = verify_inputs(observed.dependency_root, 'dotnet')
            compiler = Compiler(tools, commands, work / "vendor/lsf", offline=offline, captured=verified is not None,
                compiler_methods=True)
            write_json(output / "compiler-inputs.json", compiler.before)
            materials.extend(compiler.materials)
            write_json(output / 'compiler-patches-preparation.json', {'formatVersion': 1, 'patches': compiler.compiler_patches})
            patch_identity = read_file(output / 'compiler-patches-preparation.json')
            materials.append({'name': 'compiler-patch-preparation', 'digest': digest(patch_identity), 'size': len(patch_identity)})
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
                closure = prepare(observed.dependency_root, work, output, 'dotnet', execution_approval=approval)
                compiler.application_closure = closure
                compiler.executable_approval = approval
            stage = "compile"
            write_json(output / "diagnostic-source.json", {
                "capturedSource": str(temporary / "compiled/project/src"),
                "requestedSource": str(project_path / "src")})
            try:
                component_path, generated = compiler.compile(work, project["world"], temporary / "compiled")
            except BaseException:
                if _root_return_capture is not None:
                    try:
                        _root_return_capture[1](temporary / "compiled", output)
                    except Exception as capture_error:
                        write_json(output / "probe-inputs-unavailable.json", {"status": "unavailable",
                            "reason": type(capture_error).__name__, "compilerSucceeded": False})
                raise
            if _root_return_capture is not None:
                _root_return_capture[0](temporary / "compiled", output, generated["bindings"], compiler)
            # Native ports are derived inside the owned compiler workspace.
            # Bind the completed derivation and real linker observation rather
            # than the initial composer-only receipt written before approval.
            write_json(output / 'compiler-patches.json', {'formatVersion': 1, 'patches': compiler.compiler_patches})
            patch_identity = read_file(output / 'compiler-patches.json')
            materials.append({'name': 'automatic-compiler-patches', 'digest': digest(patch_identity), 'size': len(patch_identity)})
            materials.extend(compiler.generated_materials)
            component = read_file(component_path, 64 * 1024 * 1024)
            (output / "component.wasm").write_bytes(component)
            write_json(output / "bindings.json", generated)
            stage = "compatibility"
            guest_compatibility_build.inspect(commands, compiler.wasm, output, surface,
                host_abi_profile=guest_compatibility_build.declared_host_abi(surface))
            package_inputs(output, project, surface, files, component)
            if packager is not None:
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package", *packaging_arguments(files))
                commands.run("inspect", paths["packager"], "inspect", output / "package", *packaging_arguments(files))
            stage = "recheck"
            observed.check_unchanged()
            if snapshot(work, exclude=('dependencies', 'application-vendor') if closure else ()) != files:
                raise ValueError("captured C# project changed during compilation")
            if inventory({name: read_file(ROOT / name) for name in recipe_files}) != recipe:
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
                    from tools.dotnet_guest.outputs import verify as verify_generated
                    verify_generated(output, approval, source=temporary / 'compiled/generator-outputs')
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
                ("runtime-profile", read_file(output / "runtime-profile.json", 4 * 1024 * 1024)),
                ("closed-runtime-coverage", read_file(output / "closed-runtime-coverage.json", 4 * 1024 * 1024)),
                ("dependency-lock", files["vendor/lsf/sdk/dotnet-guest/probes/smoke/packages.lock.json"]),
                ("toolchain-config", files["global.json"])))
            if compiler.compiler_methods:
                from tools.dotnet_guest import reachability
                from tools import guest_runtime_receipts
                observed_methods = getattr(compiler, 'reachability_observation', None)
                methods_material = None
                try:
                    if observed_methods is None or observed_methods.get('schemaVersion') != 'lsf.dotnet.compiler-methods.v1':
                        raise ValueError('compiler-method-observation-unavailable')
                    graph = guest_runtime_receipts.captured_graph(files)
                    observed_methods = reachability.bind(observed_methods, source=digest(source_inputs),
                        component=digest(component), compiler=digest(read_file(output / 'compiler-inputs.json', 32 * 1024 * 1024)),
                        recipe=digest(recipe), graph=digest(canonical(graph)) if graph is not None else None)
                    write_json(output / 'compatibility-compiler-methods.json', observed_methods)
                    data = read_file(output / 'compatibility-compiler-methods.json', reachability.MAX_PUBLIC_BYTES)
                    methods_material = {'name': 'compiler-method-reachability', 'digest': digest(data), 'size': len(data)}
                    materials.append(methods_material)
                except Exception:
                    # A missing/overbound observation remains unknown. It
                    # cannot replace the original successful compiler result.
                    write_json(output / 'compatibility-compiler-methods-unavailable.json',
                        reachability.unavailable(getattr(compiler, 'reachability_observation', None)))
                selected = canonical({'schemaVersion': 'lsf.guest.compiler-method-selection.v1',
                    'language': 'dotnet', 'selected': True,
                    'status': 'observed' if methods_material is not None else 'unavailable',
                    'observation': methods_material}) + b'\n'
                with (output / 'compiler-method-observation-selection.json').open('xb') as stream:
                    stream.write(selected)
                materials.append({'name': 'compiler-method-observation-selection',
                    'digest': digest(selected), 'size': len(selected)})
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
            guest_compatibility_context_build.finish(output, files, source_inputs, component, materials)
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1,
                "packageAssembled": packager is not None,
                "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                "componentDigest": digest(component), "sdkBindingDigest": generated["filesDigest"],
                "buildSeconds": round(time.monotonic() - start, 6), "commands": commands.records})
        return output
    except BaseException as error:
        if stage == "capture" and isinstance(error, guest_resources.ResourceError):
            stage = "resource-inputs"
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
