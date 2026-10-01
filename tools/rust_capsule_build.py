"""Bounded actual-source compiler recipe for standalone Rust capsules."""
from __future__ import annotations

import json
import re
from pathlib import Path
import shutil
import tempfile
import time
import tomllib

from tools.build_observation import build_environment, file_identity, public_repository, resolve_tools
from tools.build_process import BuildProcessError, run_bounded_result
from tools.rust_capsule_project import (ROOT, canonical, checked_path, digest, fresh,
                                        inventory, decode_json, read_file, read_json, snapshot, write_json)
from tools.stage_runtime_wit import copy_wit_tree, dependencies
from tools import guest_compatibility_build

BUILD_TYPE = "https://latent.dev/build/rust-capsule/v1"
RECIPE = ("tools/rust_capsule.py", "tools/rust_capsule_project.py", "tools/rust_capsule_build.py",
          "tools/build_observation.py", "tools/build_process.py", "tools/build_process_linux.py",
          "tools/build_process_windows.py", "tools/build_process_signals.py", "tools/build_snapshot.py",
          "tools/stage_runtime_wit.py")
RECIPE += ("tools/application_dependencies.py", "tools/application_dependency_store.py", "tools/application_dependency_tools.py",
           "tools/application_dependency_approval.py", "tools/rust_application_dependencies.py", "tools/captured_compiler_isolation.py")
RECIPE += guest_compatibility_build.RECIPE


class Commands:
    def __init__(self, root: Path, output: Path, environment: dict[str, str], *,
                 deadline_seconds=900, command_seconds=600):
        if (type(deadline_seconds) is not int or type(command_seconds) is not int
                or not 1 <= command_seconds <= min(deadline_seconds, 1800)
                or not 1 <= deadline_seconds <= 7200):
            raise ValueError("finite build command and overall deadlines required")
        self.root, self.output, self.environment = root, output, environment
        self.deadline = time.monotonic() + deadline_seconds
        self.command_seconds = command_seconds
        self.records = []
        self.retained = 0
        (output / "logs").mkdir()

    def run(self, stage: str, *command: str) -> bytes:
        timeout = min(self.command_seconds, self.deadline - time.monotonic())
        if timeout <= 0:
            raise ValueError("standalone build deadline exceeded")
        start = time.monotonic()
        result = run_bounded_result([str(part) for part in command], cwd=self.root, env=self.environment,
                                    timeout_seconds=timeout, max_output_bytes=4 * 1024 * 1024)
        self.retained += len(result.stdout) + len(result.stderr)
        if self.retained > 16 * 1024 * 1024:
            raise ValueError("standalone diagnostic retention limit exceeded")
        ordinal = len(self.records)
        for stream in ("stdout", "stderr"):
            path = self.output / "logs" / f"{ordinal:02d}-{stage}.{stream}.txt"
            with path.open("xb") as file:
                file.write(getattr(result, stream))
        self.records.append({"stage": stage, "exitCode": result.returncode,
                             "seconds": round(time.monotonic() - start, 6)})
        if result.returncode:
            raise ValueError(f"{stage} failed; inspect the retained bounded compiler diagnostics")
        return result.stdout


def validate_project(files: dict[str, bytes]) -> tuple[dict, dict]:
    required = {"Cargo.toml", "Cargo.lock", "capsule-project.json", "sdk-lock.json", "src/lib.rs", "rust-toolchain.toml"}
    if not required <= files.keys():
        raise ValueError("incomplete standalone capsule project")
    project = decode_json(files["capsule-project.json"])
    if (not isinstance(project, dict) or set(project) != {"formatVersion", "name", "version", "tenant", "service", "world", "limits"}
            or type(project["formatVersion"]) is not int or project["formatVersion"] != 1):
        raise ValueError("unsupported capsule project format")
    if not isinstance(project["name"], str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", project["name"]) or len(project["name"]) > 64:
        raise ValueError("invalid Cargo capsule name")
    if not all(isinstance(project[key], str) and 0 < len(project[key]) <= 512 for key in ("version", "tenant", "service", "world")):
        raise ValueError("invalid capsule identity")
    pins = decode_json(files["sdk-lock.json"])
    if (not isinstance(pins, dict) or set(pins) != {"formatVersion", "toolchain", "sdk", "bindings", "template"}
            or type(pins["formatVersion"]) is not int or pins["formatVersion"] != 1):
        raise ValueError("unsupported SDK lock format")
    actual = {path.removeprefix("vendor/lsf/"): data for path, data in files.items() if path.startswith("vendor/lsf/")}
    if json.loads(inventory(actual)) != pins["sdk"]:
        raise ValueError("vendored SDK changed; review and regenerate the SDK source lock")
    if files["rust-toolchain.toml"] != actual.get("rust-toolchain.toml"):
        raise ValueError("Rust toolchain configuration differs from the vendored SDK")
    if any(Path(path).name in {"config", "config.toml"} and ".cargo" in Path(path).parts for path in files):
        raise ValueError("project Cargo configuration overrides are not supported")
    cargo = tomllib.loads(files["Cargo.toml"].decode())
    vendor_cargo = tomllib.loads(actual["Cargo.toml"].decode())
    expected_workspace = {key: value for key, value in vendor_cargo["workspace"].items()
                          if key not in {"members", "resolver"}}
    if cargo.get("workspace") != expected_workspace:
        raise ValueError("SDK workspace inheritance must remain exactly pinned")
    if cargo.get("package", {}).get("name") != project["name"] or cargo.get("package", {}).get("version") != project["version"]:
        raise ValueError("Cargo and capsule project identities disagree")
    if cargo.get("lib") != {"crate-type": ["cdylib"]}:
        raise ValueError("the standalone recipe requires the default cdylib library target")
    captured = "latent.dependencies.json" in files
    if captured:
        from tools.application_dependencies import validate_manifest
        validate_manifest(decode_json(files["latent.dependencies.json"]), "rust")
    if (cargo.get("patch") or cargo.get("replace")) and not captured:
        raise ValueError("dependency patches and replacements cannot override the pinned SDK")
    expected = {"wit-bindgen": "=" + pins["toolchain"]["rust"]["dependencies"]["wit-bindgen"],
                "latent-guest": {"path": "vendor/lsf/sdk/rust-guest"}}
    maintained = cargo.get("target", {}).get('cfg(target_arch = "wasm32")', {}).get("dependencies", {})
    if (not isinstance(maintained, dict) or any(maintained.get(name) != value for name, value in expected.items())
            or not captured and maintained != expected):
        raise ValueError("guest SDK and binding generator dependencies must match the pinned authoring recipe")
    # Other registry dependencies are allowed with exact direct versions and a
    # committed transitive Cargo.lock. Git/path overrides would escape the
    # captured closure and cannot replace the maintained SDK here.
    groups = [cargo.get(group, {}) for group in ("dependencies", "build-dependencies", "dev-dependencies")]
    if captured:
        groups.extend(value.get(group, {}) for value in cargo.get("target", {}).values()
                      for group in ("dependencies", "build-dependencies", "dev-dependencies"))
    for group in groups:
        for name, specification in group.items():
            if name in {"latent-guest", "latent-component-bindings", "wit-bindgen"}:
                if captured and maintained.get(name) == specification and name in expected:
                    continue
                raise ValueError("SDK dependency overrides are not supported")
            version = specification if isinstance(specification, str) else specification.get("version") if isinstance(specification, dict) else None
            if not captured and (not isinstance(version, str) or not re.fullmatch(r"=[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version)):
                raise ValueError("additional dependencies require exact versions and a committed Cargo.lock")
            if isinstance(specification, dict) and not captured and not set(specification) <= {"version", "features", "default-features", "optional", "package"}:
                raise ValueError("uncaptured dependency source override")
    if not captured and set(cargo.get("target", {})) != {'cfg(target_arch = "wasm32")'}:
        raise ValueError("additional target dependency tables require an explicit source-capture extension")
    if not captured and set(cargo.get("target", {})['cfg(target_arch = "wasm32")']) != {"dependencies"}:
        raise ValueError("unsupported target dependency classes")
    script = cargo["package"].get("build", "build.rs" if "build.rs" in files else False)
    if script is not False and (not isinstance(script, str) or script not in files):
        raise ValueError("application build script must be inside the captured project")
    limits = project["limits"]
    expected_limits = set(read_json(ROOT / "examples/echo-contract/capsule.json")["execution"]["limits"])
    if not isinstance(limits, dict) or set(limits) != expected_limits:
        raise ValueError("explicit closed invocation budget required")
    for name, value in limits.items():
        if name == "wallTimeLimitMillis" and value is None:
            continue
        if type(value) is not int or not 0 <= value < 2**64:
            raise ValueError("invocation budgets require unsigned full-width integers")
    if limits["cpuFuel"] == 0 or limits["memoryBytes"] == 0:
        raise ValueError("positive fuel and memory budgets required")
    return project, pins


def binding_check(work: Path, pins: dict, command: Commands, bindgen: Path) -> str:
    platform = work / "vendor/lsf/wit/platform"
    source = platform / "runtime-phase3-blobs"
    staged = work.parent / "binding-wit"
    copy_wit_tree(source, staged)
    for package in dependencies(source, platform):
        copy_wit_tree(package, staged / "deps" / package.name)
    output = work.parent / "bindings"
    command.run("sdk-bindings", bindgen, "rust", staged, "--generate-all", "--out-dir", output)
    actual = digest(read_file(output / "capsule.rs"))
    if actual != pins["bindings"]["outputs"]["rust/capsule.rs"]:
        raise ValueError("generated SDK binding drift; review the WIT and generator pins")
    return actual


def package_inputs(output: Path, project: dict, surface: dict, files: dict[str, bytes], component: bytes) -> None:
    manifest = read_json(ROOT / "examples/echo-contract/capsule.json")
    manifest["metadata"] = {"name": project["service"], "tenant": project["tenant"]}
    if project["tenant"] is None:
        # The public manifest's optional field is absent, never JSON null.
        # This reusable capsule acquires an explicit tenant at admission.
        del manifest["metadata"]["tenant"]
    manifest["component"] = {"digest": digest(component), "version": project["version"], "world": project["world"]}
    manifest["exports"] = surface["exports"]
    manifest["imports"] = [{"contract": name, "optional": False} for name in surface["imports"]]
    manifest["execution"].update(limits=project["limits"], threading="single-threaded", snapshotEligible=False, fusionEligible=False)
    manifest["compatibility"]["minimumFabricVersion"] = tomllib.loads(files["vendor/lsf/Cargo.toml"].decode())["workspace"]["package"]["version"]
    write_json(output / "capsule.json", manifest)
    layers = [("component.wasm", "component", "application/wasm"),
              ("capsule.json", "capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json"),
              ("contracts.json", "contracts", "application/vnd.latent.contracts.v1+json"),
              ("wit-lock.json", "wit-lock", "application/vnd.latent.wit-lock.v1+json")]
    guest_compatibility_build.package_report(output, files, component)
    layers.append(("compatibility-report.json", "asset", "application/vnd.latent.guest.compatibility.v1+json"))
    for name, data in files.items():
        if name.startswith("wit/") and name.endswith(".wit"):
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            layers.append((name, "asset", "text/plain"))
    write_json(output / "package-source.json", {
        "formatVersion": 1, "kind": "capsule", "name": project["name"], "version": project["version"],
        "entrypoint": "component.wasm", "annotations": {},
        "layers": [{"path": path, "source": path, "role": role, "mediaType": media} for path, role, media in layers],
    })
    deployment = read_json(ROOT / "examples/echo-contract/deployment.json")
    deployment["metadata"] = {"name": project["name"], "tenant": project["tenant"]}
    if project["tenant"] is None:
        del deployment["metadata"]["tenant"]
    deployment["spec"].update(service=project["service"], release=digest(component), grants=[], resources=project["limits"])
    write_json(output / "deployment.json", deployment)


def build(project_path: Path, output: Path, contracts_tool: Path, packager: Path | None,
          repository: str, *, offline: bool = False, host_linker: Path | None = None,
          rust_bin: Path | None = None, executable_approval: str | None = None) -> Path:
    # Commands/package_inputs are shared by every language. Only this recipe
    # loads the Rust application graph and executable-input approval consumer.
    from tools.application_dependencies import prepare, verify_inputs
    from tools.application_dependency_approval import approve as approve_execution, request as execution_request
    from tools.rust_application_dependencies import configure as configure_application
    from tools.captured_compiler_isolation import Isolation

    project_path, output = checked_path(project_path), checked_path(output)
    if output == project_path or output in project_path.parents:
        raise ValueError("build output overlaps source")
    if project_path in output.parents and project_path / "target" not in output.parents:
        raise ValueError("in-project build outputs must be inside target/")
    public_repository(repository)
    files = snapshot(project_path)
    project, pins = validate_project(files)
    source_inputs = inventory(files)
    recipe_files = {name: read_file(ROOT / name) for name in RECIPE}
    # The manifest/deployment seed is also an actual recipe input, not an
    # implicit dependency hidden outside the observation.
    for name in ("examples/echo-contract/capsule.json", "examples/echo-contract/deployment.json"):
        recipe_files[name] = read_file(ROOT / name)
    recipe_inputs = inventory(recipe_files)
    output = fresh(output)
    commands = None
    stage = "prepare"
    started, start = int(time.time()), time.monotonic()
    try:
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe_inputs)
        with tempfile.TemporaryDirectory(prefix="lsf-rust-capsule-") as temporary:
            temporary = Path(temporary)
            work = temporary / "source"
            work.mkdir()
            for name, data in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            environment = build_environment(temporary)
            if offline:
                environment.update(CARGO_NET_OFFLINE="true", RUSTUP_AUTO_INSTALL="0")
            paths, materials = resolve_tools(pins["toolchain"], work, environment, installed=rust_bin)
            bindgen_path = shutil.which("wit-bindgen", path=environment.get("PATH"))
            if bindgen_path is None:
                raise ValueError("install the pinned wit-bindgen CLI")
            paths.update({"wit-bindgen": Path(bindgen_path).resolve(strict=True),
                          "contracts-tool": contracts_tool.resolve(strict=True)})
            if packager is not None:
                paths["packager"] = packager.resolve(strict=True)
            if host_linker is not None:
                paths["host-linker"] = host_linker.resolve(strict=True)
                environment["CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"] = str(paths["host-linker"])
            materials.extend(file_identity(paths[name], name)
                             for name in ("wit-bindgen", "contracts-tool", "packager", "host-linker") if name in paths)
            environment.update(RUSTC=str(paths["rustc"]), RUSTUP_TOOLCHAIN=pins["toolchain"]["rust"]["toolchain"],
                               CARGO_INCREMENTAL="0", CARGO_TARGET_DIR=str(temporary / "target"))
            commands = Commands(work, output, environment)
            stage = "application-dependencies"
            verified = verify_inputs(project_path, "rust")
            closure, approval = None, None
            isolation, adapted_manifest = None, None
            if verified is not None:
                environment.update(CARGO_HOME=str(temporary / "cargo-home"), CARGO_NET_OFFLINE="true", RUSTUP_AUTO_INSTALL="0")
                sysroot = Path(commands.run("rust-sysroot", paths["rustc"], "--print", "sysroot").decode().strip()).resolve(strict=True)
                zig = shutil.which("zig", path=environment.get("PATH"))
                shell = shutil.which("sh", path=environment.get("PATH"))
                if not zig or not shell:
                    raise ValueError("captured Rust compilation requires pinned Zig and Linux shell host linker tools")
                zig, shell = Path(zig).resolve(strict=True), Path(shell).resolve(strict=True)
                reported = commands.run("zig-version", zig, "version").decode().strip()
                if reported != pins["toolchain"]["sdk"]["zig"]:
                    raise ValueError("Rust host linker Zig version differs from the pinned compiler profile")
                linker = temporary / "captured-host-linker"
                linker.write_text("#!" + str(shell) + '\nexec "$LSF_CAPTURED_ZIG" cc -target x86_64-linux-gnu.2.39 "$@"\n')
                linker.chmod(0o700)
                environment["CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"] = str(linker)
                environment.update(ZIG_GLOBAL_CACHE_DIR=str(temporary / "zig-global"), ZIG_LOCAL_CACHE_DIR=str(temporary / "zig-local"),
                                   LSF_CAPTURED_ZIG=str(zig))
                selected_tools = {name: paths[name] for name in ("cargo", "rustc", "wasm-tools", "wit-bindgen")}
                selected_tools.update(zig=zig, shell=shell, linker=linker)
                isolation = Isolation(temporary, selected_tools, {"rust-compiler-and-sysroot": sysroot,
                                      "zig-host-linker-and-sysroot": zig.parent})
                write_json(output / "rust-compiler-inputs.json", isolation.receipt)
                if verified.lock["executableInputs"]:
                    stage = "executable-input-approval"
                    executable_recipe = digest(canonical({"recipe": digest(recipe_inputs), "sourceSnapshot": digest(source_inputs)}))
                    requested = execution_request(verified, isolation, executable_recipe)
                    write_json(output / "executable-input-approval-request.json", {
                        "formatVersion": 1, "identity": digest(canonical(requested)), "specification": requested})
                    if executable_approval is None:
                        raise ValueError("captured Cargo build scripts/macros require the exact retained executable-input approval identity")
                    approval = approve_execution(verified, isolation, executable_recipe, executable_approval)
                closure = prepare(project_path, work, output, "rust", execution_approval=approval)
                adapted_manifest, cargo_inputs = configure_application(closure, work, Path(environment["CARGO_HOME"]))
                isolation.protect_inputs(work)
                write_json(output / "cargo-inputs.json", cargo_inputs)
            stage = "bindings"
            version = commands.run("bindgen-version", paths["wit-bindgen"], "--version").decode().strip().split()
            if version != ["wit-bindgen-cli", pins["toolchain"]["rust"]["dependencies"]["wit-bindgen"]]:
                raise ValueError("wit-bindgen CLI does not match the project pin")
            binding_digest = binding_check(work, pins, commands, paths["wit-bindgen"])
            stage = "compile"
            diagnostics = ["--message-format=json"] if packager is None else []
            compile_arguments = ["build", "--locked", "--release", "--lib", "--target", "wasm32-unknown-unknown", *diagnostics]
            if closure is not None:
                selection = closure.lock["selection"]
                if selection.get("features"):
                    compile_arguments.extend(["--features", ",".join(selection["features"])])
                if selection.get("allFeatures"):
                    compile_arguments.append("--all-features")
                if selection.get("noDefaultFeatures"):
                    compile_arguments.append("--no-default-features")
                commands.run("compile", *isolation.wrap(paths["cargo"], compile_arguments, work, environment))
                if approval is not None:
                    from tools.application_dependency_store import directory_files
                    generated_outputs = {}
                    targets = [temporary / "target/release", temporary / "target/wasm32-unknown-unknown/release"]
                    total = 0
                    for target in targets:
                        for directory in sorted((target / "build").glob("*/out")):
                            for name, data in directory_files(directory).items():
                                total += len(data)
                                if len(generated_outputs) >= 8192 or total > 64 * 1024 * 1024:
                                    raise ValueError("captured build-tool generated output limit exceeded")
                                generated_outputs[directory.relative_to(temporary / "target").as_posix() + "/" + name] = {
                                    "digest": digest(data), "size": len(data)}
                    for path in sorted((targets[0] / "deps").glob("*.so")):
                        generated_outputs[path.relative_to(temporary / "target").as_posix()] = {
                            "digest": file_identity(path, "compiled-proc-macro")["digest"], "size": path.stat().st_size}
                    write_json(output / "executable-input-outputs.json", {"formatVersion": 1, "approvalIdentity": approval.identity,
                        "outputs": generated_outputs, "cleanup": "namespace-and-owned-process-reaped", "hermetic": False})
            else:
                commands.run("compile", paths["cargo"], *compile_arguments)
            module = temporary / "target/wasm32-unknown-unknown/release" / (project["name"].replace("-", "_") + ".wasm")
            stage = "component"
            commands.run("component", paths["wasm-tools"], "component", "new", module, "-o", output / "component.wasm")
            commands.run("validate", paths["wasm-tools"], "validate", output / "component.wasm", "--features", "cm-async,cm-async-stackful,cm-more-async-builtins")
            component = read_file(output / "component.wasm", 64 * 1024 * 1024)
            stage = "contracts"
            wit_input = temporary / "wit-inputs.json"
            write_json(wit_input, {"world": project["world"], "sources": [
                {"path": path, "content": data.decode()} for path, data in files.items() if path.startswith("wit/") and path.endswith(".wit")]})
            derived = temporary / "derived"
            commands.run("contracts", paths["contracts-tool"], wit_input, derived)
            for name in ("contracts.json", "wit-lock.json", "surface.json"):
                (output / name).write_bytes(read_file(derived / name))
            surface = read_json(derived / "surface.json")
            stage = "compatibility"
            guest_compatibility_build.inspect(commands, paths["wasm-tools"], output, surface)
            package_inputs(output, project, surface, files, component)
            if packager is not None:
                stage = "package"
                commands.run("package", paths["packager"], "build", output / "package-source.json", output, output / "package")
                commands.run("inspect", paths["packager"], "inspect", output / "package")
            stage = "recheck"
            captured_files = snapshot(work, exclude=("dependencies", "application-vendor"))
            if adapted_manifest is not None:
                if captured_files.get("Cargo.toml") != adapted_manifest:
                    raise ValueError("selected Cargo manifest changed during compilation")
                captured_files["Cargo.toml"] = files["Cargo.toml"]
                closure.check_unchanged()
                isolation.check_unchanged()
            if snapshot(project_path) != files or captured_files != files:
                raise ValueError("project changed during the observed build")
            if inventory({name: read_file(ROOT / name) for name in recipe_files}) != recipe_inputs:
                raise ValueError("authoring recipe changed during the build")
            for material in materials:
                if file_identity(paths[material["name"]], material["name"]) != material:
                    raise ValueError("tool binary changed during the build")
            package_files = {"package-source.json": read_file(output / "package-source.json")}
            for layer in read_json(output / "package-source.json")["layers"]:
                package_files[layer["source"]] = read_file(output / layer["source"], 64 * 1024 * 1024)
            package_inventory = inventory(package_files)
            (output / "package-inputs.json").write_bytes(package_inventory)
            materials.extend({"name": name, "digest": digest(data), "size": len(data)} for name, data in (
                ("source-snapshot", source_inputs), ("build-recipe", recipe_inputs), ("package-inputs", package_inventory),
                ("toolchain-config", files["rust-toolchain.toml"]), ("dependency-lock", files["Cargo.lock"])))
            if closure is not None:
                for name in ("application-dependencies.json", "cargo-inputs.json", "rust-compiler-inputs.json"):
                    data = read_file(output / name, 8 * 1024 * 1024)
                    materials.append({"name": name.removesuffix(".json"), "digest": digest(data), "size": len(data)})
                if approval is not None:
                    for name in ("executable-input-approval-request.json", "executable-input-outputs.json"):
                        data = read_file(output / name, 8 * 1024 * 1024)
                        materials.append({"name": name.removesuffix(".json"), "digest": digest(data), "size": len(data)})
            finished = int(time.time())
            if finished < started or time.monotonic() - start > 900 or finished - started > 900:
                raise ValueError("build clock or overall deadline invalid")
            observation = {"formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(source_inputs)[7:],
                           "snapshotDigest": digest(source_inputs), "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
                "componentDigest": digest(component), "componentSize": len(component), "materials": sorted(materials, key=lambda item: item["name"]),
                "parameters": {"cargoPackage": project["name"], "manifestPath": "Cargo.toml", "crateType": "cdylib", "target": "wasm32-unknown-unknown",
                               "profile": "release", "locked": True, "incremental": False},
                "startedAt": started, "finishedAt": finished, "reproducibility": "not-checked", "hermetic": False,
                "dependencyCompleteness": "declared-inputs-incomplete"}
            write_json(output / "build-observation.json", observation)
            write_json(output / "BUILD-COMPLETE.json", {"formatVersion": 1, "observationDigest": digest(read_file(output / "build-observation.json")),
                "packageAssembled": packager is not None,
                "sourceDigest": digest(source_inputs), "componentDigest": digest(component), "sdkBindingDigest": binding_digest,
                "buildSeconds": round(time.monotonic() - start, 6), "commands": commands.records})
        return output
    except BaseException as error:
        write_json(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
                   "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
                   "commands": commands.records if commands else []})
        guest_compatibility_build.failure_report(output, "rust", stage)
        raise
