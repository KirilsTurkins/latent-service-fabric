#!/usr/bin/env python3
"""Build the maintained guests and exact Phase 2 package inputs; execute no guest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tomllib

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.stage_runtime_wit import stage
from tools.c_guest.compiler import Compiler, CAPABILITIES
from tools.build_process import run_bounded
from tools.build_observation import file_identity, build_environment, resolve_tools

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "tools/toolchain-smoke/examples"
LOCK = ROOT / "tools/guest_bindings.lock.json"
BUILD_DEADLINE: float | None = None
BUILD_ENVIRONMENT: dict[str, str] = {}
TOOL_PATHS: dict[str, Path] = {}
TOOL_MATERIALS: dict[str, dict] = {}


def run(*command: str, capture: bool = False) -> str:
    timeout = 600 if BUILD_DEADLINE is None else min(600, BUILD_DEADLINE - time.monotonic())
    if timeout <= 0:
        raise ValueError("guest build deadline exceeded")
    environment = BUILD_ENVIRONMENT
    command = (str(TOOL_PATHS.get(command[0], command[0])), *command[1:])
    result = run_bounded(command, ROOT, environment, timeout_seconds=timeout, max_output_bytes=4 * 1024 * 1024)
    if not capture:
        print(result.stdout.decode("utf-8", errors="replace"), end="")
        print(result.stderr.decode("utf-8", errors="replace"), end="")
    return result.stdout.decode("utf-8") if capture else ""


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def wit_bindgen_version() -> str:
    config = tomllib.loads((ROOT / "tools/toolchain.toml").read_text(encoding="utf-8"))
    return config["rust"]["dependencies"]["wit-bindgen"]


def check_tools(*, include_c: bool = True) -> None:
    config = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
    paths, materials = resolve_tools(config, ROOT, BUILD_ENVIRONMENT)
    TOOL_PATHS.update(paths)
    TOOL_MATERIALS.update({item["name"]: item for item in materials})
    BUILD_ENVIRONMENT["RUSTC"] = str(paths["rustc"])
    for tool in (("wit-bindgen", "zig") if include_c else ("wit-bindgen",)):
        located = shutil.which(tool, path=BUILD_ENVIRONMENT.get("PATH"))
        if located is None:
            raise ValueError(f"missing guest tool: {tool}")
        TOOL_PATHS[tool] = Path(located).resolve(strict=True)
        TOOL_MATERIALS[tool] = file_identity(TOOL_PATHS[tool], tool)
    for tool, version in (("wasm-tools", config["contracts"]["wasm-tools"]),
                          ("wit-bindgen", config["rust"]["dependencies"]["wit-bindgen"]),
                          ("zig", config["sdk"]["zig"])):
        if tool == "zig" and not include_c:
            continue
        actual = run(tool, "version" if tool == "zig" else "--version", capture=True).strip()
        if version not in actual.split():
            raise ValueError(f"{tool}: expected {version}, found {actual}")
    if run("rustc", "--version", capture=True).split()[1] != config["rust"]["toolchain"]:
        raise ValueError("guest examples require the pinned Rust toolchain")


def source_inputs() -> bytes:
    files = [ROOT / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml", "tools/toolchain.toml",
                                     "tools/build_guest_capsules.py", "tools/stage_runtime_wit.py",
                                     "tools/build_process.py", "tools/build_process_linux.py",
                                     "tools/build_process_windows.py", "tools/build_process_signals.py",
                                     "tools/build_observation.py", "tools/build_snapshot.py", "tools/guest_bindings.lock.json")]
    for directory in ("sdk/rust-guest", "sdk/c-guest", "tools/c_guest", "crates/latent-component-bindings",
                      "tools/toolchain-smoke", "tools/optimization-workloads", "wit/platform"):
        files.extend(path for path in (ROOT / directory).rglob("*") if path.is_file()
                     and not {"target", "__pycache__"}.intersection(path.relative_to(ROOT / directory).parts)
                     and path.suffix != ".pyc")
    if len(files) > 4096:
        raise ValueError("guest source file count exceeded")
    records, size = {}, 0
    for path in sorted(files):
        record = file_identity(path, str(path.relative_to(ROOT)).replace(os.sep, "/"), 4 * 1024 * 1024)
        size += record["size"]
        if size > 32 * 1024 * 1024:
            raise ValueError("guest source byte bound exceeded")
        name = record.pop("name")
        records[name] = record
    return canonical(records)


def observation(output: Path, directory: Path, profile: dict, component: Path,
                started: int, sources: bytes, language: str) -> None:
    if sources != source_inputs():
        raise ValueError("source inputs changed during guest compilation")
    materials = [("source-snapshot", sources), ("build-recipe", Path(__file__).read_bytes()),
                 ("toolchain-config", (ROOT / "tools/toolchain.toml").read_bytes())]
    commands = ["wasm-tools", "wit-bindgen", "zig"] if language == "c" else ["wasm-tools", "wit-bindgen", "cargo", "rustc"]
    if language == "rust":
        materials.append(("dependency-lock", (ROOT / "Cargo.lock").read_bytes()))
    (output / "source-inputs.json").write_bytes(sources)
    write_json(directory / "build-observation.json", {
        "formatVersion": 1, "buildType": f"https://latent.dev/build/{language}-guest/v1",
        "source": {"repository": "https://github.com/KirilsTurkins/latent-service-fabric",
                   "revision": digest(sources).split(":")[1], "snapshotDigest": digest(sources),
                   "repositoryTrust": "operator-asserted", "capture": "explicit-input-files"},
        "componentDigest": digest(component.read_bytes()), "componentSize": component.stat().st_size,
        "materials": [{"name": name, "digest": digest(data), "size": len(data)} for name, data in materials]
                     + [TOOL_MATERIALS[name] for name in commands],
        "parameters": {"cargoPackage": "latent-toolchain-smoke", "cargoExample": "guest-" + profile["name"],
                       "target": "wasm32-unknown-unknown", "profile": "release", "locked": True, "incremental": False}
                      if language == "rust" else {"compiler": "zig-cc", "fixture": profile["name"], "target": "wasm32-wasi", "optimization": "O2"},
        "startedAt": started, "finishedAt": int(time.time()), "reproducibility": "not-checked",
        "hermetic": False, "dependencyCompleteness": "declared-inputs-incomplete",
    })


def bindings(output: Path, update: bool) -> None:
    wit = output / "binding-wit"
    stage(wit, ROOT / "wit/platform/runtime-phase3-blobs")
    hashes = {}
    for language in ("rust", "c"):
        destination = output / "bindings" / language
        destination.mkdir(parents=True, exist_ok=True)
        command = ["wit-bindgen", language, str(wit), "--out-dir", str(destination)]
        if language == "rust":
            command.append("--generate-all")
        run(*command)
        for path in sorted(destination.iterdir()):
            if path.is_file():
                hashes[f"{language}/{path.name}"] = digest(path.read_bytes())
    value = {"formatVersion": 1, "generator": f"wit-bindgen {wit_bindgen_version()}",
             "world": "latent:platform/capsule@0.4.0", "outputs": hashes}
    if update:
        write_json(LOCK, value)
    elif json.loads(LOCK.read_text()) != value:
        raise ValueError("guest binding drift: review WIT/generator changes and use --update-bindings\n" + json.dumps(value, indent=2))


def package_inputs(directory: Path, profile: dict, source: Path, component: Path, *, maximum_fuel: int | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(component, directory / "component.wasm")
    # Uniform public probe types are intentionally small. The Phase 2 builder
    # checks this metadata against the actual component and locked WIT sources.
    interface = {"id": profile["contract"], "documentation": None, "functions": [{
        "id": "run", "name": "run", "asynchronous": profile["asynchronous"], "documentation": None,
        "attributes": {}, "parameters": [
            {"name": name, "value_type": kind, "documentation": None}
            for name, kind in (("which", "U32"), ("text", "String"), ("handle", "U64"))],
        "results": [{"name": "result", "value_type": "U64", "documentation": None}],
    }]}
    if "functions" in profile:
        interface["functions"] = profile["functions"]
    interface["digest"] = digest(canonical(interface))
    descriptor = {"id": profile["contract"], "package_name": profile["package"].split("@")[0],
                  "semantic_version": "1.0.0", "interfaces": [interface], "dependencies": []}
    descriptor["digest"] = digest(canonical(descriptor))
    contracts = canonical({"format_version": 1, "contracts": [descriptor]})
    (directory / "contracts.json").write_bytes(contracts)
    manifest = json.loads((ROOT / "examples/echo-contract/capsule.json").read_text())
    service_name = {"service": "caller", "callee": "callee"}.get(profile["name"], "generic")
    manifest["metadata"] = {"name": service_name, "annotations": {"latent.dev/purpose": "guest-sdk-example"}}
    manifest["component"] = {"digest": digest(component.read_bytes()), "version": "1.0.0", "world": profile["world"]}
    manifest["exports"] = [profile["contract"]]
    manifest["imports"] = [{"contract": profile["capability"], "optional": False}] if profile["capability"] else []
    limits = manifest["execution"]["limits"]
    fuel = 100_000_000 if profile["name"] in {"service", "callee"} else 1_000_000_000_000
    if profile["name"] in {"http", "blob"}:
        fuel = 10_000_000_000
    if maximum_fuel is not None:
        if type(maximum_fuel) is not int or not 1 <= maximum_fuel <= fuel:
            raise ValueError("test package fuel narrowing must fit the maintained guest ceiling")
        fuel = maximum_fuel
    limits.update(cpuFuel=fuel,
                  memoryBytes=4_194_304 if profile["name"] in {"service", "callee"} else 16_777_216, wallTimeLimitMillis=5000,
                  childCalls=16 if profile["name"] == "service" else 0,
                  outboundRequests=8 if profile["name"] in {"http", "streaming", "blob", "secrets", "events"} else 0,
                  blobReadBytes=65536 if profile["name"] == "blob" else 0,
                  blobWriteBytes=65536 if profile["name"] == "blob" else 0,
                  logBytes=0, effectCount=0)
    manifest["execution"].update(threading="single-threaded", snapshotEligible=False, fusionEligible=False)
    manifest["compatibility"]["minimumFabricVersion"] = tomllib.loads(
        (ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    write_json(directory / "capsule.json", manifest)
    wit = directory / "wit"
    wit.mkdir(exist_ok=True)
    locked = []
    dependency_ids = []
    if profile["capability"]:
        dependency = (ROOT / "wit/platform" / profile["witDirectory"] / "package.wit").read_bytes()
        (wit / "capability.wit").write_bytes(dependency)
        package, version = profile["capability"].split("/", 1)
        dependency_id = package + "@" + version.split("@")[1]
        dependency_ids.append(dependency_id)
        locked.append({"id": dependency_id, "sourcePath": "wit/capability.wit", "digest": digest(dependency), "dependencies": []})
    (wit / "service.wit").write_bytes(source.read_bytes())
    locked.append({"id": profile["package"], "sourcePath": "wit/service.wit", "digest": digest(source.read_bytes()), "dependencies": dependency_ids})
    write_json(directory / "wit-lock.json", {
        "formatVersion": 1, "world": profile["world"], "contractsDigest": digest(contracts), "packages": locked})
    layer_specs = [("component.wasm", "component", "application/wasm"),
                   ("capsule.json", "capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json"),
                   ("contracts.json", "contracts", "application/vnd.latent.contracts.v1+json"),
                   ("wit-lock.json", "wit-lock", "application/vnd.latent.wit-lock.v1+json"),
                   ("wit/capability.wit", "asset", "text/plain"), ("wit/service.wit", "asset", "text/plain")]
    if not profile["capability"]:
        layer_specs = [entry for entry in layer_specs if entry[0] != "wit/capability.wit"]
    write_json(directory / "package-source.json", {
        "formatVersion": 1, "kind": "capsule", "name": "guest-" + profile["name"], "version": "1.0.0",
        "entrypoint": "component.wasm", "annotations": {},
        "layers": [{"path": path, "source": path, "role": role, "mediaType": media} for path, role, media in layer_specs],
    })


def main() -> None:
    global BUILD_DEADLINE
    BUILD_DEADLINE = time.monotonic() + 900
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "target/guest-capsules")
    parser.add_argument("--update-bindings", action="store_true")
    parser.add_argument("--skip-c", action="store_true", help="local Rust iteration only; never the CI gate")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or (ROOT in output.parents and not output.is_relative_to(ROOT / "target")):
        raise ValueError("guest output must be outside source directories")
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "BUILD-COMPLETE.json"
    marker.unlink(missing_ok=True)
    temporary = output / "tmp"
    temporary.mkdir(exist_ok=True)
    BUILD_ENVIRONMENT.update(build_environment(temporary))
    BUILD_ENVIRONMENT.update({"CARGO_INCREMENTAL": "0", "CARGO_TARGET_DIR": str(Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve())})
    check_tools(include_c=not args.skip_c)
    bindings(output, args.update_bindings)
    sources, started = source_inputs(), int(time.time())
    profiles = [json.loads(path.read_text()) for path in sorted(EXAMPLES.glob("guest_*/profile.json"))]
    command = ["cargo", "build", "-p", "latent-toolchain-smoke", "--target", "wasm32-unknown-unknown", "--release", "--locked"]
    for profile in profiles:
        command.extend(["--example", "guest-" + profile["name"]])
    run(*command)
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target"))
    for profile in profiles:
        component = output / ("rust-" + profile["name"] + ".wasm")
        run("wasm-tools", "component", "new", str(target / "wasm32-unknown-unknown/release/examples" / ("guest_" + profile["name"] + ".wasm")), "-o", str(component))
        run("wasm-tools", "validate", str(component))
        package_inputs(output / ("rust-" + profile["name"]), profile,
                       EXAMPLES / ("guest_" + profile["name"]) / "world.wit", component)
        observation(output, output / ("rust-" + profile["name"]), profile, component, started, sources, "rust")
    if not args.skip_c:
        build_c(output, profiles, sources)
    if sources != source_inputs():
        raise ValueError("guest sources changed before build completion")
    for name, path in TOOL_PATHS.items():
        if file_identity(path, name) != TOOL_MATERIALS[name]:
            raise ValueError("guest compiler tool changed during build")
    names = ["rust-" + p["name"] for p in profiles] + ([] if args.skip_c else ["c-" + name for name in CAPABILITIES])
    write_json(marker, {"formatVersion": 1, "observations": {
        name: digest((output / name / "build-observation.json").read_bytes()) for name in names}})
    print(f"Guest package inputs: {output}")


def build_c(output: Path, profiles: list[dict], sources: bytes) -> None:
    by_name = {profile["name"]: profile for profile in profiles}
    if set(by_name) != set(CAPABILITIES):
        raise ValueError("C and Rust guest capability inventories differ")
    remaining = int(BUILD_DEADLINE - time.monotonic())
    if remaining < 1:
        raise ValueError("guest build deadline exceeded")
    with tempfile.TemporaryDirectory(prefix="c-components-", dir=output) as temporary:
        temporary = Path(temporary)
        compiler = Compiler(temporary / "tmp", min(remaining, 900))
        for name in CAPABILITIES:
            started = int(time.time())
            profile = by_name[name]
            source = ROOT / "sdk/c-guest/blob.c" if name == "blob" else ROOT / "sdk/c-guest/examples" / (name + ".c")
            component, lock = compiler.compile([source], EXAMPLES / ("guest_" + name),
                profile["world"], temporary / name,
                memory_bytes=4_194_304 if name in {"service", "callee"} else 16_777_216,
                trap=name != "blob")
            destination = output / ("c-" + name)
            package_inputs(destination, profile, EXAMPLES / ("guest_" + name) / "world.wit", component)
            write_json(destination / "bindings.json", lock)
            observation(output, destination, profile, component, started, sources, "c")


if __name__ == "__main__":
    main()
