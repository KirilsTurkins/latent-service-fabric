#!/usr/bin/env python3
"""Create and build independent Rust capsules using the maintained guest SDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import tomllib

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = ("greeting", "word-count", "shipping")
GUESTS = ("http", "streaming", "blob", "secrets", "events", "random", "metrics", "service", "callee")
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 4096, 4 * 1024 * 1024, 32 * 1024 * 1024
BUILD_TYPE = "https://latent.dev/build/rust-capsule/v1"
SDK_ROOTS = ("sdk/rust-guest/src", "crates/latent-component-bindings", "wit/platform", "examples/echo-contract/wit")
SDK_FILES = ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml", "tools/toolchain.toml", "sdk/rust-guest/Cargo.toml")
RECIPE_FILES = ("tools/rust_capsule.py", "tools/build_process.py", "tools/build_process_linux.py", "tools/build_process_windows.py", "tools/build_process_signals.py", "tools/build_observation.py", "tools/build_snapshot.py")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def read(path: Path, maximum: int = MAX_FILE_BYTES) -> bytes:
    if path.resolve(strict=True) != path.absolute():
        raise ValueError("linked source ancestor")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("source must be a bounded regular file")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    after = path.lstat()
    if len(data) > maximum or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("source changed during capture")
    return data


def write(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def object_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def document(path: Path) -> dict:
    value = json.loads(read(path), object_pairs_hook=object_pairs)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def files(root: Path) -> list[Path]:
    result = []
    pending, visited = [root], 0
    while pending:
        directory = pending.pop()
        if not stat.S_ISDIR(directory.lstat().st_mode):
            raise ValueError("linked source directory")
        for child in sorted(directory.iterdir()):
            visited += 1
            if visited > MAX_FILES:
                raise ValueError("source entry count exceeded")
            if directory == root and child.name in {"target", ".git"}:
                continue
            mode = child.lstat().st_mode
            if stat.S_ISDIR(mode):
                pending.append(child)
            elif stat.S_ISREG(mode):
                result.append(child)
            else:
                raise ValueError("linked or nonregular source")
            if len(result) + len(pending) > MAX_FILES:
                raise ValueError("source file count exceeded")
    return sorted(result)


def inventory(entries: list[tuple[str, Path]]) -> bytes:
    result, seen, total = {}, set(), 0
    if len(entries) > MAX_FILES:
        raise ValueError("source file count exceeded")
    for name, path in sorted(entries):
        if name.casefold() in seen:
            raise ValueError("duplicate or case-colliding source path")
        seen.add(name.casefold())
        data = read(path)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("source byte count exceeded")
        result[name] = {"digest": digest(data), "size": len(data)}
    return canonical(result)


def sdk_inputs(root: Path = ROOT) -> bytes:
    paths = [root / name for name in SDK_FILES]
    for name in SDK_ROOTS:
        paths.extend(files(root / name))
    return inventory([(path.relative_to(root).as_posix(), path) for path in paths])


def new_project(destination: Path, template: str, name: str, root: Path = ROOT) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}[a-z0-9]|[a-z]", name):
        raise ValueError("use a lowercase Cargo name of at most 64 characters")
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if destination == root or root in destination.parents:
        raise ValueError("create the application outside the LSF source checkout")
    if destination.exists() or destination.is_symlink():
        raise ValueError("project destination already exists")
    pin = tomllib.loads(read(root / "tools/toolchain.toml").decode())
    package = tomllib.loads(read(root / "Cargo.toml").decode())["workspace"]["package"]
    if template in TUTORIALS:
        source = root / "tools/toolchain-smoke/examples" / ("tutorial_" + template.replace("-", "_"))
        world, dependency = f"examples:{template}/service@1.0.0", None
    elif template.startswith("guest-") and template[6:] in GUESTS:
        source = root / "tools/toolchain-smoke/examples" / ("guest_" + template[6:])
        profile = document(source / "profile.json")
        world, dependency = profile["world"], profile.get("witDirectory")
    else:
        raise ValueError("unsupported template")
    rust = read(source / "component.rs").decode()
    rust, replacements = re.subn(r'path:\s*(?:\[[^\]]*\]|"[^"]*")', 'path: "wit"', rust, count=1)
    if replacements != 1:
        raise ValueError("template binding declaration changed; review the scaffold")
    wit = read(source / "world.wit")
    sdk = sdk_inputs(root)
    # Validate every selected input before creating the user-owned directory.
    imported = read(root / "wit/platform" / dependency / "package.wit") if dependency else None
    destination.mkdir()
    (destination / "src").mkdir()
    (destination / "wit").mkdir()
    (destination / "src/lib.rs").write_text(rust, encoding="utf-8")
    (destination / "wit/world.wit").write_bytes(wit)
    if imported is not None:
        target = destination / "wit/deps" / dependency
        target.mkdir(parents=True)
        (target / "package.wit").write_bytes(imported)
    # JSON quoting is compatible with TOML basic strings, including Windows paths.
    manifest = f'''[package]
name = {json.dumps(name)}
version = "1.0.0"
edition = "2021"
rust-version = {json.dumps(pin["rust"]["toolchain"])}
license = "Apache-2.0"

[workspace]

[lib]
crate-type = ["cdylib"]

[target.'cfg(target_arch = "wasm32")'.dependencies]
latent-guest = {{ path = {json.dumps(str(root / "sdk/rust-guest"))}, version = "={package["version"]}" }}
wit-bindgen = "={pin["rust"]["dependencies"]["wit-bindgen"]}"

[profile.release]
panic = "abort"
opt-level = "s"
lto = true
codegen-units = 1
strip = "debuginfo"
'''
    (destination / "Cargo.toml").write_text(manifest, encoding="utf-8")
    (destination / "rust-toolchain.toml").write_text(
        f'[toolchain]\nchannel = "{pin["rust"]["toolchain"]}"\nprofile = "minimal"\ntargets = ["wasm32-unknown-unknown"]\n', encoding="utf-8")
    (destination / ".gitignore").write_text("/target/\n", encoding="utf-8")
    write(destination / "capsule-project.json", {
        "formatVersion": 1, "name": name, "version": "1.0.0", "world": world,
        "template": template, "service": name, "sdkSnapshotDigest": digest(sdk),
        "limits": {"cpuFuel": 100_000_000, "memoryBytes": 16_777_216,
                   "wallTimeLimitMillis": 5000, "childCalls": 0, "outboundRequests": 0,
                   "stateReadBytes": 0, "stateWriteBytes": 0, "blobReadBytes": 0,
                   "blobWriteBytes": 0, "logBytes": 0, "effectCount": 0},
    })


def project(path: Path) -> dict:
    value = document(path / "capsule-project.json")
    expected = {"formatVersion", "name", "version", "world", "template", "service", "sdkSnapshotDigest", "limits"}
    if set(value) != expected or value["formatVersion"] != 1:
        raise ValueError("unsupported project format")
    if value["sdkSnapshotDigest"] != digest(sdk_inputs()):
        raise ValueError("SDK source drift: review the new checkout and explicitly recreate/update the project pin")
    manifest = tomllib.loads(read(path / "Cargo.toml").decode())
    if (manifest["package"]["name"] != value["name"] or manifest["package"]["version"] != value["version"]
            or manifest.get("workspace") != {} or manifest.get("lib", {}).get("crate-type") != ["cdylib"]):
        raise ValueError("project and Cargo identities disagree")
    pins = tomllib.loads(read(ROOT / "tools/toolchain.toml").decode())
    package_version = tomllib.loads(read(ROOT / "Cargo.toml").decode())["workspace"]["package"]["version"]
    dependencies = manifest.get("target", {}).get('cfg(target_arch = "wasm32")', {}).get("dependencies", {})
    if dependencies.get("latent-guest") != {"path": str(ROOT / "sdk/rust-guest"), "version": "=" + package_version}:
        raise ValueError("latent-guest must use the captured SDK path and version")
    if dependencies.get("wit-bindgen") != "=" + pins["rust"]["dependencies"]["wit-bindgen"]:
        raise ValueError("wit-bindgen must match the captured component toolchain")
    if set(manifest.get("lib", {})) - {"crate-type"} or manifest.get("patch") or manifest.get("replace"):
        raise ValueError("external library paths and dependency overrides are unsupported")
    if (path / ".cargo").exists() or (path / ".cargo").is_symlink():
        raise ValueError("project Cargo configuration overrides are unsupported")
    for scope in (manifest, *manifest.get("target", {}).values()):
        for table in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, dependency in scope.get(table, {}).items():
                if name == "latent-guest" and dependency == dependencies["latent-guest"]:
                    continue
                if isinstance(dependency, dict) and any(key in dependency for key in ("path", "git", "workspace")):
                    raise ValueError("dependencies outside the captured project/SDK and locked registry are unsupported")
    build_script = manifest["package"].get("build", "build.rs")
    if build_script not in (False, "build.rs"):
        raise ValueError("build scripts must use the captured project build.rs")
    if not isinstance(value["service"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}[a-z0-9]|[a-z]", value["service"]):
        raise ValueError("use a lowercase service name of at most 64 characters")
    if not isinstance(value["limits"], dict) or any(type(n) is not int or n < 0 for n in value["limits"].values()):
        raise ValueError("execution limits must be explicit nonnegative integers")
    return value


class Tools:
    def __init__(self, temporary: Path, cwd: Path):
        from tools.build_observation import build_environment, file_identity, resolve_tools
        self.environment = build_environment(temporary)
        self.cwd, self.deadline = cwd, time.monotonic() + 900
        self.config = tomllib.loads(read(ROOT / "tools/toolchain.toml").decode())
        self.paths, self.materials = resolve_tools(self.config, cwd, self.environment)
        self.environment.update(RUSTC=str(self.paths["rustc"]), CARGO_INCREMENTAL="0",
                                CARGO_TARGET_DIR=str(temporary / "target"))
        executable = shutil.which("wit-bindgen", path=self.environment.get("PATH"))
        if executable is None:
            raise ValueError("install the pinned wit-bindgen CLI")
        self.paths["wit-bindgen"] = Path(executable).resolve(strict=True)
        actual = self.run("wit-bindgen", "--version").decode().split()
        if self.config["rust"]["dependencies"]["wit-bindgen"] not in actual:
            raise ValueError("wit-bindgen version does not match the project toolchain")
        self.materials.append(file_identity(self.paths["wit-bindgen"], "wit-bindgen"))

    def run(self, command: str, *args: str) -> bytes:
        from tools.build_process import run_bounded
        timeout = min(600, self.deadline - time.monotonic())
        if timeout <= 0:
            raise ValueError("capsule build deadline exceeded")
        completed = run_bounded([str(self.paths.get(command, command)), *args], self.cwd,
                                self.environment, timeout_seconds=timeout,
                                max_output_bytes=4 * 1024 * 1024)
        return completed.stdout

    def bindings(self, directory: Path, world: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="lsf-rust-bindings-") as temporary:
            target = Path(temporary)
            self.run("wit-bindgen", "rust", str(directory / "wit"), "--world", world,
                     "--out-dir", str(target), "--generate-all")
            if not list(target.glob("*.rs")):
                raise ValueError("binding generation produced no Rust source")
            return {"formatVersion": 1, "generator": self.config["rust"]["dependencies"]["wit-bindgen"],
                    "world": world, "outputs": json.loads(inventory([
                        (p.relative_to(target).as_posix(), p) for p in files(target)]))}


def lock_project(directory: Path) -> None:
    value = project(directory)
    lock = directory / "bindings.lock.json"
    if lock.exists() or lock.is_symlink():
        raise ValueError("binding lock exists; review and remove it explicitly before regenerating")
    with tempfile.TemporaryDirectory(prefix="lsf-rust-lock-") as temporary:
        tools = Tools(Path(temporary), directory)
        tools.run("cargo", "generate-lockfile", "--manifest-path", str(directory / "Cargo.toml"))
        generated = tools.bindings(directory, value["world"])
        write(lock, generated)


def source_inputs(directory: Path) -> bytes:
    entries = [("application/" + p.relative_to(directory).as_posix(), p) for p in files(directory)]
    sdk = json.loads(sdk_inputs())
    entries.extend(("sdk/" + name, ROOT / name) for name in sdk)
    entries.extend(("recipe/" + name, ROOT / name) for name in RECIPE_FILES)
    return inventory(entries)


def build(directory: Path, output: Path, packager: Path, repository: str) -> None:
    from tools.build_observation import file_identity, public_repository
    repository = public_repository(repository)
    value = project(directory)
    output = output.parent.resolve(strict=True) / output.name
    if (output == ROOT or ROOT in output.parents or output == directory or directory in output.parents
            or output.exists() or output.is_symlink()):
        raise ValueError("choose a fresh output directory outside both source trees")
    read(directory / "Cargo.lock")
    expected_bindings = document(directory / "bindings.lock.json")
    packager = packager.resolve(strict=True)
    packager_material = file_identity(packager, "packager")
    sources = source_inputs(directory)
    output.mkdir()
    started, monotonic = int(time.time()), time.monotonic()
    stage = "toolchain"
    try:
        with tempfile.TemporaryDirectory(prefix="lsf-rust-build-") as temporary:
            tools = Tools(Path(temporary), directory)
            stage = "bindings"
            if tools.bindings(directory, value["world"]) != expected_bindings:
                raise ValueError("generated binding drift; review WIT and regenerate the binding lock explicitly")
            stage = "compile"
            tools.run("cargo", "build", "--manifest-path", str(directory / "Cargo.toml"),
                      "--lib", "--locked", "--release", "--target", "wasm32-unknown-unknown")
            core = Path(tools.environment["CARGO_TARGET_DIR"]) / "wasm32-unknown-unknown/release" / (value["name"].replace("-", "_") + ".wasm")
            component = output / "component.wasm"
            tools.run("wasm-tools", "component", "new", str(core), "-o", str(component))
            tools.run("wasm-tools", "validate", str(component))
            stage = "package-inputs"
            write_inputs(directory, output, value, tools, packager)
            # Production packaging checks the actual binary against WIT and metadata.
            write_inventory(output, value, sources)
            tools.run(str(packager), "build-with-sbom", str(output / "package-source.json"),
                      str(output / "sbom-inputs.json"), str(output), str(output / "package"))
            tools.run(str(packager), "inspect", str(output / "package"))
            stage = "source-recheck"
            if sources != source_inputs(directory):
                raise ValueError("source inputs changed during compilation")
            for material in tools.materials:
                if file_identity(tools.paths[material["name"]], material["name"]) != material:
                    raise ValueError("tool changed during compilation")
            if file_identity(packager, "packager") != packager_material:
                raise ValueError("packager changed during compilation")
            materials = tools.materials + [packager_material]
            for name, data in (("source-snapshot", sources), ("dependency-lock", read(directory / "Cargo.lock")),
                               ("build-recipe", canonical({p: digest(read(ROOT / p)) for p in RECIPE_FILES})),
                               ("toolchain-config", read(ROOT / "tools/toolchain.toml")),
                               ("binding-lock", read(directory / "bindings.lock.json")),
                               ("dependency-inventory", read(output / "sbom-inputs.json"))):
                materials.append({"name": name, "digest": digest(data), "size": len(data)})
            observed = file_identity(component, "component")
            observation = {
                "formatVersion": 1, "buildType": BUILD_TYPE,
                "source": {"repository": repository, "revision": digest(sources)[7:],
                           "snapshotDigest": digest(sources), "repositoryTrust": "operator-asserted",
                           "capture": "explicit-input-files"},
                "componentDigest": observed["digest"], "componentSize": observed["size"],
                "materials": sorted(materials, key=lambda item: item["name"]),
                "parameters": {"cargoPackage": value["name"], "crateType": "cdylib", "target": "wasm32-unknown-unknown",
                               "profile": "release", "locked": True, "incremental": False},
                "startedAt": started, "finishedAt": int(time.time()), "reproducibility": "not-checked",
                "hermetic": False, "dependencyCompleteness": "declared-inputs-incomplete",
            }
            (output / "source-inputs.json").write_bytes(sources)
            write(output / "build-observation.json", observation)
            write(output / "BUILD-COMPLETE.json", {
                "formatVersion": 1, "observationDigest": digest(read(output / "build-observation.json")),
                "elapsedBuildMillis": round((time.monotonic() - monotonic) * 1000),
                "componentBytes": observed["size"], "executed": False,
            })
    except BaseException as error:
        write(output / "BUILD-FAILED.json", {"formatVersion": 1, "stage": stage,
              "errorType": type(error).__name__, "startedAt": started, "finishedAt": int(time.time())})
        raise


def write_inputs(directory: Path, output: Path, value: dict, tools: Tools, packager: Path) -> None:
    sources = {"wit/" + p.relative_to(directory / "wit").as_posix(): read(p).decode("utf-8")
               for p in files(directory / "wit") if p.suffix == ".wit"}
    request = output / "contract-request.json"
    write(request, {"world": value["world"], "sources": sources})
    generated = json.loads(tools.run(str(packager), "derive-contracts", str(request)))
    contracts = generated["contracts"]
    write(output / "contracts.json", contracts)
    lock = generated["witLock"]
    lock["contractsDigest"] = digest(read(output / "contracts.json"))
    write(output / "wit-lock.json", lock)
    for path, text in sources.items():
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode())
    manifest = document(ROOT / "examples/echo-contract/capsule.json")
    manifest["metadata"] = {"name": value["service"], "annotations": {"latent.dev/purpose": "rust-application"}}
    manifest["component"] = {"digest": digest(read(output / "component.wasm", 64 * 1024 * 1024)),
                             "version": value["version"], "world": value["world"]}
    manifest["exports"] = [c["id"] for c in contracts["contracts"]]
    manifest["imports"] = [{"contract": name, "optional": False} for name in generated["imports"]]
    manifest["execution"].update(threading="single-threaded", snapshotEligible=False,
                                  fusionEligible=False, limits=value["limits"])
    manifest["compatibility"]["minimumFabricVersion"] = tomllib.loads(read(ROOT / "Cargo.toml").decode())["workspace"]["package"]["version"]
    write(output / "capsule.json", manifest)
    layers = [("component.wasm", "component", "application/wasm"),
              ("capsule.json", "capsule-manifest", "application/vnd.latent.capsule.manifest.v1+json"),
              ("contracts.json", "contracts", "application/vnd.latent.contracts.v1+json"),
              ("wit-lock.json", "wit-lock", "application/vnd.latent.wit-lock.v1+json")]
    layers.extend((path, "asset", "text/plain") for path in sorted(sources))
    write(output / "package-source.json", {
        "formatVersion": 1, "kind": "capsule", "name": value["name"], "version": value["version"],
        "entrypoint": "component.wasm", "annotations": {},
        "layers": [{"path": p, "source": p, "role": role, "mediaType": media} for p, role, media in layers],
    })


def write_inventory(output: Path, value: dict, sources: bytes) -> None:
    """Inventory exact supplied output/WIT, not an invented dependency closure."""
    lock = document(output / "wit-lock.json")
    component = read(output / "component.wasm", 64 * 1024 * 1024)
    entries = [{"kind": "component", "name": "component.wasm", "path": "component.wasm",
                "digest": digest(component), "size": len(component), "digestScope": "output-bytes",
                "origin": "package-input"}]
    for package in lock["packages"]:
        name, version = package["id"].rsplit("@", 1)
        data = read(output / package["sourcePath"])
        entries.append({"kind": "wit-package", "name": name, "version": version,
                        "path": package["sourcePath"], "source": "urn:lsf:wit:" + package["sourcePath"],
                        "digest": digest(data), "size": len(data), "digestScope": "wit-source",
                        "origin": "captured-source"})
    write(output / "sbom-inputs.json", {"formatVersion": 1, "packageKind": "capsule",
          "packageName": value["name"], "packageVersion": value["version"],
          "sourceSnapshotDigest": digest(sources), "dependencyCompleteness": "declared-inputs-incomplete",
          "entries": entries})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("new")
    create.add_argument("directory", type=Path)
    create.add_argument("--template", choices=(*TUTORIALS, *("guest-" + name for name in GUESTS)), default="greeting")
    create.add_argument("--name", required=True)
    lock = commands.add_parser("lock")
    lock.add_argument("directory", type=Path)
    compile_command = commands.add_parser("build")
    compile_command.add_argument("directory", type=Path)
    compile_command.add_argument("--output", required=True, type=Path)
    compile_command.add_argument("--packager", required=True, type=Path)
    compile_command.add_argument("--repository", required=True)
    args = parser.parse_args()
    if args.command == "new":
        new_project(args.directory, args.template, args.name)
    elif args.command == "lock":
        lock_project(args.directory.resolve(strict=True))
    else:
        build(args.directory.resolve(strict=True), args.output, args.packager, args.repository)


if __name__ == "__main__":
    from tools.build_process import BuildProcessError
    try:
        main()
    except (OSError, ValueError, BuildProcessError) as error:
        raise SystemExit(f"Rust capsule workflow failed: {error}") from error
