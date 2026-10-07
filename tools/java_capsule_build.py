"""Capture, compile and package actual Java source; never sign or grant authority."""
from __future__ import annotations

from tools import guest_compatibility_context_build
import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools import (guest_compatibility_build, guest_resources, guest_dependency_inputs,
                   guest_authoring_frontend, java_http_client, java_server_source, server_source)
from tools.java_capsule_project import validate
from tools.java_guest.compiler import Compiler
from tools.java_guest import resources as java_resources
from tools.application_dependencies import prepare
from tools.java_application_dependencies import classpath
from tools.java_resource_artifacts import packaged_resources
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
                                        read_file, read_json, snapshot, write_json)

BUILD_TYPE = "https://latent.dev/build/java-capsule/v1"
RECIPE = ("tools/java_capsule.py", "tools/java_capsule_project.py", "tools/java_capsule_build.py",
          "tools/application_dependencies.py", "tools/application_dependency_store.py",
          "tools/application_dependency_tools.py", "tools/java_application_dependencies.py", "tools/java_dependency_resolution.py",
          "tools/java_registry_tls.py",
          "tools/java_resource_artifacts.py", "tools/java_dependency_authoring.py", "tools/toolchain.toml",
          "tools/java_guest/compiler.py", "tools/java_guest/resources.py", "tools/java_guest/bindings.py", "tools/java_guest/model.py",
          "tools/java_guest/java.py", "tools/java_guest/c.py", "tools/java_guest/lock.py", "tools/java_guest/surface.py", "tools/rust_capsule_project.py",
          "tools/rust_capsule_build.py", "tools/build_observation.py", "tools/build_process.py",
          "tools/build_process_linux.py", "tools/build_process_windows.py", "tools/build_process_signals.py",
          "tools/build_snapshot.py", "tools/stage_runtime_wit.py", "examples/echo-contract/capsule.json",
          "examples/echo-contract/deployment.json", "tools/transaction_guest_project.py", "tools/java_guest/sdk.py",
          "tools/dev_workflow/common.py", "tools/dev_workflow/transaction_binding.py")
RECIPE += guest_compatibility_build.RECIPE
RECIPE += guest_compatibility_context_build.RECIPE
RECIPE += guest_resources.RECIPE
RECIPE += guest_dependency_inputs.RECIPE
RECIPE += guest_authoring_frontend.RECIPE
RECIPE += java_server_source.RECIPE
RECIPE += ("tools/java_generator_authoring.py",)
RECIPE += java_http_client.RECIPE


def retain_logs(source: Path, output: Path) -> None:
    target = output / "compiler-logs"
    target.mkdir(exist_ok=True)
    total = 0
    for path in sorted((*source.glob("*.log"), *source.glob("*.command.json"))):
        data = read_file(path)
        total += len(data)
        if total > 16 * 1024 * 1024: raise ValueError("Java compiler log retention exceeded")
        with (target / path.name).open("xb") as retained: retained.write(data)


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None,
          repository: str, wasi_sdk: Path, *, gradle="gradle", timeout=900,
          offline_cache: Path | None = None) -> Path:
    if type(timeout) not in {int, float} or not 0 < timeout <= 900:
        raise ValueError("Java build deadline must be positive and at most 900 seconds")
    project_path = guest_dependency_inputs.application_root(checked_path(project_path), 'java')
    output = checked_path(output)
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    repository = public_repository(repository)
    output = fresh(output)
    commands, compiler, stage = None, None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        observed = guest_dependency_inputs.capture_source(project_path, 'java')
        files = observed.files
        project, _lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe_files = {name: read_file(ROOT / name) for name in RECIPE}
        recipe_inputs = inventory(recipe_files)
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
                stage = "application-dependencies"
                closure = prepare(observed.dependency_root, work, output, "java")
                if closure is not None and offline_cache is None:
                    raise ValueError("captured Java builds require the verified offline compiler cache")
                application_jars, application_inventory = classpath(closure, temporary / "selected-application-jars")
                write_json(output / "java-classpath.json", application_inventory)
                additional_resources, resource_sources = packaged_resources(closure, application_inventory, files)
                application_resources = java_resources.materialize({**files, **resource_sources}, source_inputs,
                    additional_resources, temporary / "selected-application-resources")
                stage = "compiler-inputs"
                compiler = Compiler(compiler_dir, checked_path(wasi_sdk), gradle=gradle,
                    sdk=work / "vendor/lsf/sdk/java-guest", platform=work / "vendor/lsf/wit/platform",
                    config=pins, timeout=timeout - (time.monotonic() - start), offline_cache=offline_cache)
                (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
                server_plan, automatic_bridge = None, None
                if "server" in project:
                    stage = "server-source-analysis"
                    server_plan = java_server_source.analyze(compiler, work / "src", project["server"], application_jars, output)
                    automatic_bridge = java_server_source.bridge(compiler.sdk, project["server"], server_plan)
                    (output / "server-profile.json").write_bytes(java_server_source.profile(compiler, recipe_inputs))
                materials = list(compiler.materials)
                paths = {"contracts-tool": checked_path(contracts_tool)}
                if packager is not None:
                    paths["packager"] = checked_path(packager)
                materials.extend(file_identity(path, name) for name, path in paths.items())
                stage = "compile"
                write_json(output / "diagnostic-source.json", {
                    "capturedSource": str(temporary / "compiled/project/src/main/java"),
                    "requestedSource": str(project_path / "src")})
                profile_selection = {}
                if server_plan is not None:
                    profile_selection.update(server_profile=True, server_bridge=automatic_bridge)
                if application_resources is not None:
                    profile_selection["application_resources"] = application_resources
                if "httpClient" in project:
                    profile_selection["http_client_profile"] = True
                component_path, generated = compiler.compile(work / "src", work / "wit", project["world"], temporary / "compiled",
                    application_classpath=application_jars, **profile_selection)
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
                package_files.update(resource_sources)
                package_files.update({"wit/" + path: data for path, data in wit_files.items()})
                surface = read_json(derived / "surface.json")
                stage = "compatibility"
                recipe_inputs = guest_compatibility_build.capture_host_recipe(output, recipe_files, recipe_inputs, surface)
                guest_compatibility_build.inspect(commands, compiler.paths["wasm-tools"], output, surface,
                    host_abi_profile=guest_compatibility_build.declared_host_abi(surface))
                additional_assets = []
                if "httpClient" in project:
                    (output / "http-client-profile.json").write_bytes(java_http_client.profile(
                        compiler.sdk, recipe_inputs, source_inputs, component))
                    additional_assets.append(("http-client-profile.json", "asset", "application/vnd.latent.java.http.profile.v1+json"))
                if server_plan is not None:
                    actual_web = server_source.inspect(commands, compiler.paths["wasm-tools"], component_path,
                                                       temporary / "compiled/wit", world=project["world"])
                    declaration = server_source.emit(files, component, read_file(output / "server-profile.json"), server_plan,
                                                     actual_web, source_inputs=source_inputs)
                    additional_assets.extend([server_source.package(output, declaration),
                        ("server-profile.json", "asset", "application/vnd.latent.server.source.profile.v1+json")])
                package_inputs(output, project, surface, package_files, component,
                               additional_resources=additional_resources, additional_assets=additional_assets)
                if packager is not None:
                    stage = "package"
                    commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                    commands.run("inspect", paths["packager"], "inspect", output / "package")
                stage = "recheck"
                observed.check_unchanged()
                if snapshot(work, exclude=("dependencies", "application-vendor")) != files:
                    raise ValueError("project changed during the observed Java build")
                if closure is not None:
                    closure.check_unchanged()
                    for path, item in zip(application_jars, application_inventory["artifacts"]):
                        if digest(read_file(path, 64 * 1024 * 1024)) != item["selectedDigest"]:
                            raise ValueError("selected Java classpath changed during compilation")
                if inventory({path: read_file(ROOT / path) for path in recipe_files}) != recipe_inputs:
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
                if 'java-generated-inputs.json' in files:
                    data = files['java-generated-inputs.json']
                    materials.append({"name": "java-generator-inputs",
                                      "digest": digest(data), "size": len(data)})
                if (output / 'runtime-profile.json').exists():
                    runtime_receipt = read_file(output / 'runtime-profile.json', 4 * 1024 * 1024)
                    materials.append({'name': 'runtime-profile', 'digest': digest(runtime_receipt), 'size': len(runtime_receipt)})
                if closure is not None:
                    data = read_file(output / "application-dependencies.json", 8 * 1024 * 1024)
                    materials.extend([{"name": "application-dependency-closure", "digest": digest(data), "size": len(data)},
                                      {"name": "java-classpath-selection", "digest": digest(read_file(output / "java-classpath.json", 8 * 1024 * 1024)),
                                       "size": (output / "java-classpath.json").stat().st_size}])
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
                guest_compatibility_context_build.finish(output, files, source_inputs, component, materials)
                write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1,
                    "packageAssembled": packager is not None,
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
        guest_compatibility_build.failure_report(output, "java", stage)
        raise
