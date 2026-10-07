"""Observe actual TypeScript sources, generated bindings and compiler inputs."""
from __future__ import annotations

from tools import guest_compatibility_context_build, guest_runtime_receipts
import json
from pathlib import Path
import tempfile
import time
from tools.build_observation import build_environment, file_identity, public_repository
from tools.build_process import BuildProcessError
from tools import guest_authoring_frontend, guest_compatibility_build, guest_dependency_inputs, guest_resources
from tools.rust_capsule_build import Commands, package_inputs
from tools.rust_capsule_project import (ROOT, checked_path, digest, fresh, inventory,
    read_file, read_json, snapshot, write_json)
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.project import validate
from tools.typescript_guest import runtime_profile as runtime
from tools.application_dependencies import prepare
from tools.typescript_application_dependencies import source_snapshot, bundle_configuration

BUILD_TYPE = "https://latent.dev/build/typescript-capsule/v1"
RECIPE = ("tools/typescript_capsule.py", "tools/typescript_guest/project.py", "tools/typescript_guest/build.py",
    "tools/typescript_guest/compiler.py", "tools/typescript_guest/probe.py", "tools/typescript_guest/bundle.mjs",
    "tools/typescript_guest/componentize.mjs", "tools/typescript_guest/signed64.mjs", "tools/typescript_guest/resources.mjs",
    "tools/rust_capsule_project.py", "tools/rust_capsule_build.py",
    "tools/build_observation.py", "tools/build_process.py", "tools/build_process_linux.py",
    "tools/build_process_windows.py", "tools/build_process_signals.py", "tools/build_snapshot.py", "tools/stage_runtime_wit.py",
    "tools/phase3_resource_identity.py", "tools/phase3_resource_profile.py", "tools/phase2_operator_process.py",
    "examples/echo-contract/capsule.json", "examples/echo-contract/deployment.json", "tools/transaction_guest_project.py",
    "tools/dev_workflow/common.py", "tools/dev_workflow/transaction_binding.py")
RECIPE += ("tools/application_dependencies.py", "tools/application_dependency_store.py", "tools/application_dependency_tools.py",
           "tools/application_dependency_approval.py", "tools/typescript_application_dependencies.py",
           "tools/typescript_dependency_authoring.py", "tools/captured_compiler_isolation.py")
RECIPE += guest_compatibility_build.RECIPE
RECIPE += guest_compatibility_context_build.RECIPE
RECIPE += ('tools/guest_runtime_receipts.py',)
RECIPE += guest_resources.RECIPE
RECIPE += guest_dependency_inputs.RECIPE
RECIPE += guest_authoring_frontend.RECIPE
RECIPE += ('tools/typescript_guest/runtime_profile.py', 'tools/typescript_guest/activation_engine.py',
           'tools/typescript_guest/promise_engine.py', 'tools/typescript_guest/timer_engine.py', 'tools/typescript_guest/abort_engine.py',
           'tools/typescript_guest/event_engine.py',
           'sdk/typescript-guest/activation/runtime-globals.d.ts')
from tools.typescript_guest.activation_engine import NATIVE_SOURCES
RECIPE += tuple('sdk/typescript-guest/activation/'+name for name in NATIVE_SOURCES)
RECIPE += ("tools/typescript_generator_authoring.py",)


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None, repository: str, *, tools: Path,
          runtime_engine: Path | None = None, runtime_engine_receipt: Path | None = None):
    project_path, output, tools = map(checked_path, (project_path, output, tools))
    project_path = guest_dependency_inputs.application_root(project_path, 'typescript')
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("build output must be outside source or beneath its target directory")
    if tools == project_path or tools in project_path.parents or project_path in tools.parents:
        raise ValueError("compiler installation must be separate from captured application sources")
    repository, output = public_repository(repository), fresh(output)
    commands, stage = None, "capture"
    started, start = int(time.time()), time.monotonic()
    try:
        observed = guest_dependency_inputs.capture_source(project_path, 'typescript',
                                                         exclude_when_captured=('node_modules',))
        files = observed.files
        project, lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe_files = {name: read_file(ROOT / name) for name in RECIPE}
        recipe = inventory(recipe_files)
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe)
        with tempfile.TemporaryDirectory(prefix="lsf-typescript-capsule-") as owned:
            temporary, work = Path(owned), Path(owned) / "project"
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            commands = Commands(work, output, build_environment(temporary))
            stage = "application-dependencies"
            closure = prepare(observed.dependency_root, work, output, "typescript")
            application_modules = bundle_configuration(closure) if closure is not None else None
            runtime_profile = runtime.selected_profile(project, closure.lock if closure is not None else None)
            if closure is not None:
                write_json(output / "npm-inputs.json", application_modules)
            write_json(output / "diagnostic-source.json", {"capturedSource": str(work / "src"),
                       "requestedSource": str(project_path / "src")})
            paths = {"contracts-tool": checked_path(contracts_tool)}
            if packager is not None:
                paths["packager"] = checked_path(packager)
            materials = [file_identity(path, name) for name, path in paths.items()]
            # Check the production public-value profile before compiling the
            # embedded engine. Host resource imports remain legal, but public
            # RPC signatures cannot transfer owned/borrowed resource handles.
            stage = "contracts"
            wit_input = temporary / "wit-inputs.json"
            write_json(wit_input, {"world": project["world"], "sources": [
                {"path": name, "content": data.decode()} for name, data in files.items() if name.startswith("wit/") and name.endswith(".wit")]})
            derived = temporary / "derived"
            commands.run("contracts", paths["contracts-tool"], wit_input, derived)
            for name in ("contracts.json", "wit-lock.json", "surface.json"):
                (output / name).write_bytes(read_file(derived / name))
            stage = "compiler-inputs"
            options = {'isolated_workspace': temporary if closure is not None else None}
            if runtime_profile == runtime.ASYNC_PROFILE:
                options.update(isolated_workspace=temporary, runtime_profile=runtime_profile,
                               engine=runtime_engine, engine_receipt=runtime_engine_receipt)
            elif runtime_engine is not None or runtime_engine_receipt is not None:
                raise ValueError('native engine input requires the explicit TypeScript Promise candidate')
            compiler = Compiler(tools, commands, {name: files["vendor/lsf/sdk/typescript-guest/tools/" + name]
                                                 for name in ("package.json", "package-lock.json")}, **options)
            write_json(output / "compiler-inputs.json", compiler.before)
            compiler_paths = {"node": compiler.node, "wasm-tools": compiler.wasm}
            materials.extend(file_identity(path, name) for name, path in compiler_paths.items())
            paths.update(compiler_paths)
            if compiler.isolation is not None:
                write_json(output / "compiler-containment.json", compiler.isolation.receipt)
            stage = "compile"
            component_path, generated = compiler.compile(work, project["world"], temporary / "compiled", application_modules=application_modules)
            package_project = project
            runtime_assets = ()
            runtime_materials = []
            if runtime_profile == runtime.ASYNC_PROFILE:
                for name in ('contracts.json', 'wit-lock.json', 'surface.json'):
                    (output/('original-'+name)).write_bytes(read_file(output/name))
                selected_contracts = temporary/'selected-contracts'
                commands.run('selected-runtime-contracts', paths['contracts-tool'],
                             temporary/'compiled/selected-wit-inputs.json', selected_contracts)
                for name in ('contracts.json', 'wit-lock.json', 'surface.json'):
                    (output/name).write_bytes(read_file(selected_contracts/name))
                if read_json(output/'surface.json')['exports'] != read_json(output/'original-surface.json')['exports']:
                    raise ValueError('selected TypeScript runtime changed public contract exports')
                package_project = dict(project, world=runtime.SELECTED_WORLD)
                (output/'typescript-runtime-selection.json').write_bytes(
                    read_file(temporary/'compiled/typescript-runtime-selection.json', 65536))
                runtime_assets = (('typescript-runtime-selection.json', 'asset',
                                  'application/vnd.latent.typescript.runtime-selection.v1+json'),)
                runtime_materials.extend({'name': name, 'digest': digest(raw), 'size': len(raw)} for name, raw in (
                    ('typescript-native-engine', compiler.engine_before[0]),
                    ('typescript-native-engine-input', compiler.engine_before[1]),
                    ('typescript-runtime-selection', read_file(output/'typescript-runtime-selection.json', 65536))))
            component = read_file(component_path, 64 * 1024 * 1024)
            (output / "component.wasm").write_bytes(component)
            (output / "generated-bindings.js").write_bytes(read_file(temporary / "compiled/generated-bindings.js", 8 * 1024 * 1024))
            write_json(output / "bindings.json", generated)
            if closure is not None:
                (output / "bundle-selected-inputs.json").write_bytes(read_file(temporary / "compiled/application.mjs.inputs.json", 8 * 1024 * 1024))
                (output / "application.mjs.map").write_bytes(read_file(temporary / "compiled/application.mjs.map", 32 * 1024 * 1024))
            # The selected runtime derives an authoritative surface with its
            # activation import. Use those same bytes for compatibility and
            # manifest admission; the original surface remains retained above.
            surface = read_json(output / "surface.json")
            stage = "compatibility"
            recipe = guest_compatibility_build.capture_host_recipe(output, recipe_files, recipe, surface)
            guest_compatibility_build.inspect(commands, compiler.wasm, output, surface,
                host_abi_profile=guest_compatibility_build.declared_host_abi(surface))
            if runtime_assets:
                package_inputs(output, package_project, surface, files, component, additional_assets=runtime_assets)
            else:
                package_inputs(output, project, surface, files, component)
            if packager is not None:
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                commands.run("inspect", paths["packager"], "inspect", output / "package")
            stage = "recheck"
            captured_after = {name: data for name, data in snapshot(work, exclude=("dependencies", "application-vendor")).items()
                              if not name.startswith("generated/") and name != "tsconfig.json"}
            observed.check_unchanged()
            if captured_after != files:
                raise ValueError("captured project changed during compilation")
            if inventory({name: read_file(ROOT / name) for name in recipe_files}) != recipe:
                raise ValueError("authoring recipe changed during compilation")
            compiler.check_unchanged()
            if closure is not None:
                closure.check_unchanged()
            if [file_identity(path, name) for name, path in paths.items()] != materials:
                raise ValueError("compiler or packaging binary changed")
            materials.extend(runtime_materials)
            package_files = {"package-source.json": read_file(output / "package-source.json")}
            for layer in read_json(output / "package-source.json")["layers"]:
                package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
            package_inventory = inventory(package_files)
            (output / "package-inputs.json").write_bytes(package_inventory)
            materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                ("source-snapshot", source_inputs), ("build-recipe", recipe), ("package-inputs", package_inventory),
                ("compiler-inputs", read_file(output / "compiler-inputs.json", 8 * 1024 * 1024)),
                ("dependency-lock", files["vendor/lsf/sdk/typescript-guest/tools/package-lock.json"]),
                ("toolchain-config", files["vendor/lsf/tools/toolchain.toml"])))
            if 'typescript-generated-inputs.json' in files:
                data = files['typescript-generated-inputs.json']
                materials.append({"name": "typescript-generator-inputs",
                                  "digest": digest(data), "size": len(data)})
            if closure is not None:
                for name in ("application-dependencies.json", "npm-inputs.json", "compiler-containment.json", "bundle-selected-inputs.json", "application.mjs.map"):
                    data = read_file(output / name, 32 * 1024 * 1024)
                    materials.append({"name": name.removesuffix(".json"), "digest": digest(data), "size": len(data)})
            materials.append(guest_runtime_receipts.emit(output, 'typescript', runtime_profile, files,
                source_inputs, component, materials, graph=closure.lock if closure is not None else None,
                binding_digest=generated['filesDigest'], configuration={"profile": runtime_profile, "world": project['world'],
                    "target": "wasm32-component", "selection": closure.lock['selection'] if closure is not None else {}}))
            finished = int(time.time())
            if finished < started or finished - started > 900 or time.monotonic() - start > 900:
                raise ValueError("compiler observation deadline or clock invalid")
            write_json(output / "build-observation.json", {"formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(source_inputs)[7:], "snapshotDigest": digest(source_inputs),
                           "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda row: row["name"]),
                "parameters": {"compiler": "componentize-js", "bindings": "jco", "language": "typescript",
                               "target": "wasm32-component", "runtime": "spidermonkey", "ambientWasi": False},
                "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                "dependencyCompleteness": "declared-inputs-incomplete"})
            guest_compatibility_context_build.finish(output, files, source_inputs, component, materials)
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1, "packageAssembled": packager is not None,
                "observationDigest": digest(read_file(output / "build-observation.json")), "sourceDigest": digest(source_inputs),
                "componentDigest": digest(component), "sdkBindingDigest": generated["filesDigest"],
                "buildSeconds": round(time.monotonic() - start, 6), "commands": commands.records})
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": commands.records if commands else []})
        guest_compatibility_build.failure_report(output, "typescript", stage)
        raise
