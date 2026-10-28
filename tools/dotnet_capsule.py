#!/usr/bin/env python3
"""Create, compile and package an independent C# component using the pinned SDK."""
from __future__ import annotations
import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import sys
import tomllib
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, AUTHORING_TEMPLATES, fresh, read_file, snapshot, write_json
from tools.rust_capsule_build import Commands
from tools.build_observation import build_environment
from tools.dotnet_guest.project import create
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.dotnet_guest.runtime import ADAPTERS
from tools.dotnet_guest import http_errors


def install(directory: Path, wasi_sdk: Path):
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("the pinned NativeAOT toolchain requires Linux x86-64")
    wasi_sdk = wasi_sdk.resolve(strict=True)
    if read_file(wasi_sdk / "VERSION").decode().splitlines() != [
            "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
        raise ValueError("WASI SDK 29.0 with the pinned LLVM 21.1.4 toolchain is required")
    directory = fresh(directory)
    sdk = ROOT / "sdk/dotnet-guest"
    for source, destination in (("global.json", "global.json"), ("nuget.config", "nuget.config"),
            ("probes/smoke/Smoke.csproj", "Smoke.csproj"), ("probes/smoke/packages.lock.json", "packages.lock.json")):
        (directory / destination).write_bytes(read_file(sdk / source))
    environment = build_environment(directory)
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
        DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", DOTNET_ROLL_FORWARD="Disable",
        DOTNET_CLI_HOME=str(directory / "cli-home"), MSBUILDDISABLENODEREUSE="1")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode())["rust"]["toolchain"]
    command = Commands(directory, directory, environment)
    dotnet, wasm = shutil.which("dotnet"), shutil.which("wasm-tools")
    if not dotnet or command.run("dotnet-version", dotnet, "--version").strip() != b"10.0.100":
        raise ValueError(".NET SDK 10.0.100 is required")
    if not wasm or command.run("wasm-tools-version", wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
        raise ValueError("wasm-tools 1.254.0 is required")
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    before = runtime_inputs(ROOT)
    command.run("runtime-compiler-version", "rustc", "--version")
    command.run("locked-restore", dotnet, "restore", directory / "Smoke.csproj", "--configfile", directory / "nuget.config",
        "--locked-mode", "--packages", directory / "packages", "--disable-parallel")
    for name, data in snapshot(sdk / "tools/package-hash").items():
        path = directory / "package-hash-source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    command.run("package-hash-build", dotnet, "build", directory / "package-hash-source/PackageHash.csproj",
        "-c", "Release", "--output", directory / "package-hash", "--artifacts-path", directory / "package-hash-artifacts",
        "-p:NuGetAudit=false", "-nodeReuse:false")
    http_errors.install(sdk, directory, Path(dotnet), command.run)
    command.run("closed-runtime-compile", "cargo", "build", "--quiet", "--locked",
        "--manifest-path", ROOT / "tools/toolchain-smoke/Cargo.toml", "-p", "latent-toolchain-smoke",
        *(argument for example, _binary in ADAPTERS.values() for argument in ("--example", example)),
        "--target", "wasm32-unknown-unknown", "--release", "--target-dir", target)
    for profile, (example, binary) in ADAPTERS.items():
        command.run(profile + "-runtime-component", wasm, "component", "new",
            target / "wasm32-unknown-unknown/release/examples" / (example.replace("-", "_") + ".wasm"),
            "-o", directory / binary)
    if runtime_inputs(ROOT) != before:
        raise ValueError("runtime sources changed during compilation")
    (directory / "runtime-inputs.json").write_bytes(before)
    from tools.dotnet_guest.composer import install as install_composer
    install_composer(directory, sdk, command)
    write_json(directory / "wasi-sdk.json", {"path": str(wasi_sdk)})
    write_json(directory / "INSTALL-COMPLETE.json", {"commands": command.records})
    return directory



# Qualification-only acquisition. The ordinary twelve-adapter installer above
# remains the standard SDK path; this marker is never INSTALL-COMPLETE.json.
MANAGED_STAGE_PROFILE = "dotnet-managed-stage-diagnostic-v3"
MANAGED_STAGE_PROFILES = ("runtime-managed", "entropy", "wall")
MANAGED_STAGE_MANIFEST = "MANAGED-STAGE-INSTALL.json"
MANAGED_STAGE_SOURCE_ROOTS = (
    "sdk/dotnet-guest", "tools/dotnet_guest", "tools/toolchain-smoke",
    "tools/optimization-workloads", "crates/latent-component-bindings",
    "sdk/rust-guest", "sdk/rust-standard-stdio", "wit", "examples/echo-contract/wit")



MANAGED_STAGE_METADATA_MAX = 64 * 1024**2  # Produced evidence, not source-file allowance.


def _managed_stage_remaining(deadline):
    import math
    import time
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("managed-stage-original-deadline")
    value = deadline - 5 - time.monotonic()
    if value <= 0:
        raise ValueError("managed-stage-original-deadline")
    return value


def _managed_stage_file_identity(path, name, maximum, deadline):
    """Same finite identity shape, with the original clock checked per chunk."""
    import hashlib
    import stat
    _managed_stage_remaining(deadline)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
        raise ValueError("managed-stage-input-file-bound")
    hasher, observed = hashlib.sha256(), 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        while True:
            _managed_stage_remaining(deadline)
            chunk = source.read(min(65536, maximum + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > maximum:
                raise ValueError("managed-stage-input-file-bound")
            hasher.update(chunk)
        after = os.fstat(source.fileno())
    if (observed != before.st_size or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError("managed-stage-input-file-changed")
    return {"name": name, "digest": "sha256:" + hasher.hexdigest(), "size": observed}


def _managed_stage_tree_identity(roots, *, deadline):
    """Complete logical tool input inventory, unchanged 65536/4GiB ceilings."""
    from tools.rust_capsule_project import digest
    rows, total = [], 0
    for prefix, root in sorted(roots.items()):
        _managed_stage_remaining(deadline)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("managed-stage-input-root")
        for path in root.rglob("*"):
            _managed_stage_remaining(deadline)
            name = prefix + "/" + path.relative_to(root).as_posix()
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if resolved != root and root not in resolved.parents:
                    raise ValueError("managed-stage-input-link")
                target = resolved.relative_to(root).as_posix().encode()
                row = {"path": name, "digest": digest(target), "size": len(target), "kind": "symlink"}
            elif path.is_dir():
                continue
            else:
                size = path.lstat().st_size
                if total + size > 4 * 1024**3 or len(rows) >= 65536:
                    raise ValueError("managed-stage-tool-input-closure-bound")
                identity = _managed_stage_file_identity(path, "compiler-file", 512 * 1024**2, deadline)
                row = {"path": name, "digest": identity["digest"], "size": identity["size"]}
            total += row["size"]
            rows.append(row)
            if len(rows) > 65536 or total > 4 * 1024**3:
                raise ValueError("managed-stage-tool-input-closure-bound")
    rows.sort(key=lambda row: row["path"])
    return {"files": rows, "bytes": total}


def _write_managed_stage_metadata(path, value, *, deadline):
    _managed_stage_remaining(deadline)
    data = json.dumps(value, indent=2, ensure_ascii=False).encode() + b"\n"
    if len(data) > MANAGED_STAGE_METADATA_MAX:
        raise ValueError("managed-stage-produced-metadata-bound")
    _managed_stage_remaining(deadline)
    with path.open("xb") as stream:
        for offset in range(0, len(data), 65536):
            _managed_stage_remaining(deadline)
            stream.write(data[offset:offset + 65536])
    _managed_stage_remaining(deadline)


def _managed_stage_command_stages():
    stages = ["managed-stage-" + name + "-version" for name in
        ("dotnet", "wasm-tools", "rustc", "cargo", "wit-bindgen")]
    stages += ["managed-stage-locked-restore", "managed-stage-package-hash-build"]
    stages += ["managed-stage-nuget-content-hash"] * 7
    stages += ["managed-stage-http-errors-build", "managed-stage-runtime-compile"]
    stages += ["managed-stage-" + name + "-component" for name in MANAGED_STAGE_PROFILES]
    return stages + ["managed-stage-composer-version"]


def _managed_stage_runtime_argv(directory, root, cargo):
    return (cargo, "build", "--quiet", "--locked", "-j", "2", "--manifest-path",
        root / "tools/toolchain-smoke/Cargo.toml", "-p", "latent-toolchain-smoke",
        *(arg for name in MANAGED_STAGE_PROFILES for arg in ("--example", ADAPTERS[name][0])),
        "--target", "wasm32-unknown-unknown", "--release", "--target-dir", directory / "runtime-target")


def managed_stage_source_inputs(root: Path, *, deadline: float) -> dict:
    """Complete explicit acquisition source closure, separate from Git archive caps.

    Include all twelve original runtime sources and the real Cargo local-package
    and WIT build-script closure even though only three examples are compiled.
    The owner additionally retains current full Git and generic capture maps.
    """
    from tools.dotnet_guest.build import RECIPE
    result, total = {}, 0

    def capture(name, path):
        nonlocal total
        _managed_stage_remaining(deadline)
        if name in result:
            return
        row = _managed_stage_file_identity(path, name, 4 * 1024**2, deadline)
        result[name] = {"digest": row["digest"], "size": row["size"]}
        total += row["size"]
        if len(result) > 8992 or total > 75 * 1024**2:
            raise ValueError("managed-stage-acquisition-source-bound")

    for prefix in MANAGED_STAGE_SOURCE_ROOTS:
        _managed_stage_remaining(deadline)
        selected = root / prefix
        if selected.is_symlink() or not selected.is_dir():
            raise ValueError("managed-stage-source-root")
        for path in selected.rglob("*"):
            _managed_stage_remaining(deadline)
            if path.is_symlink():
                raise ValueError("managed-stage-source-link")
            if not path.is_dir():
                capture(prefix + "/" + path.relative_to(selected).as_posix(), path)
    for name in (*RECIPE, "tools/toolchain.toml", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml"):
        capture(name, root / name)
    _managed_stage_remaining(deadline)
    original = json.loads(runtime_inputs(root))
    if not result or not original.keys() <= result.keys() or any(result[name] != row for name, row in original.items()):
        raise ValueError("managed-stage-original-runtime-inputs")
    _managed_stage_remaining(deadline)
    return dict(sorted(result.items()))


def _managed_stage_runtime_cache(directory: Path, root: Path, *, deadline: float):
    from tools.build_observation import file_identity
    _managed_stage_remaining(deadline)
    if (directory / "INSTALL-COMPLETE.json").exists():
        raise ValueError("managed-stage-cache-is-not-standard-sdk")
    expected = {ADAPTERS[name][1] for name in MANAGED_STAGE_PROFILES}
    actual = {path.name for path in directory.glob("*.wasm")}
    if actual != expected:
        raise ValueError("managed-stage-exact-three-runtime-binaries")
    if read_file(directory / "runtime-inputs.json") != runtime_inputs(root):
        raise ValueError("managed-stage-installed-runtime-source-drift")
    return {name: file_identity(directory / ADAPTERS[name][1], name, 64 * 1024**2)
            for name in MANAGED_STAGE_PROFILES}


def _managed_stage_installed_identity(directory: Path, root: Path, tools: dict, *, deadline: float) -> dict:
    from tools.build_observation import file_identity
    from tools.dotnet_guest.composer import observed, selection
    from tools.rust_capsule_project import digest, read_json
    sdk = root / "sdk/dotnet-guest"
    binaries = _managed_stage_runtime_cache(directory, root, deadline=deadline)
    if snapshot(directory / "package-hash-source") != snapshot(sdk / "tools/package-hash"):
        raise ValueError("managed-stage-package-hash-source-drift")
    http_errors.verify_installed(sdk, directory)
    composer = observed(directory, sdk)
    rust = Path(tools["rustc"]["path"]).parent.parent
    dotnet = Path(tools["dotnet"]["path"]).parent
    wasi = Path(read_json(directory / "wasi-sdk.json")["path"])
    dependency_roots = {name: directory / name for name in (
        "packages", "package-hash-source", "package-hash", "http-errors-source", "http-errors", "cargo-home")}
    dependency_roots.update({"rust-library-inputs": rust / "lib", "wasi-sdk": wasi,
        "dotnet-sdk": dotnet / "sdk/10.0.100",
        "dotnet-runtime": dotnet / "shared/Microsoft.NETCore.App/10.0.0",
        "dotnet-ref": dotnet / "packs/Microsoft.NETCore.App.Ref/10.0.0",
        "dotnet-ref-aspnet": dotnet / "packs/Microsoft.AspNetCore.App.Ref/10.0.0",
        "dotnet-hostfxr": dotnet / "host/fxr"})
    return {
        "runtimeInputs": json.loads(runtime_inputs(root)),
        "runtimeBinaries": binaries,
        "setupInputs": _managed_stage_tree_identity(dependency_roots, deadline=deadline),
        "composer": {"selection": selection(sdk), "binary": file_identity(composer, "component-composer")},
        "wasiSdk": read_json(directory / "wasi-sdk.json"),
        "sourceInputsDigest": digest(read_file(directory / "managed-stage-source-inputs.json", MANAGED_STAGE_METADATA_MAX))}


def verify_managed_stage_tools(directory: Path, root: Path, *, deadline: float) -> dict:
    """Validate ONLY the private cache; normal Compiler must reject its marker."""
    from tools.build_observation import file_identity
    from tools.rust_capsule_project import read_json
    _managed_stage_remaining(deadline)
    data = read_json(directory / MANAGED_STAGE_MANIFEST, MANAGED_STAGE_METADATA_MAX)
    if (type(data) is not dict or set(data) != {"formatVersion", "profile", "selectedProfiles",
            "standardSdkComplete", "inputs", "tools", "commands"}
            or type(data["formatVersion"]) is not int or data["formatVersion"] != 1
            or data["profile"] != MANAGED_STAGE_PROFILE
            or data["selectedProfiles"] != list(MANAGED_STAGE_PROFILES)
            or data["standardSdkComplete"] is not False):
        raise ValueError("managed-stage-private-cache-profile")
    captured = read_json(directory / "managed-stage-source-inputs.json", MANAGED_STAGE_METADATA_MAX)
    if json.dumps(captured, sort_keys=True) != json.dumps(managed_stage_source_inputs(root, deadline=deadline), sort_keys=True):
        raise ValueError("managed-stage-private-cache-source")
    if type(data["tools"]) is not dict or set(data["tools"]) != {"dotnet", "wasm-tools", "rustc", "cargo", "wit-bindgen"}:
        raise ValueError("managed-stage-private-cache-tools")
    for name, row in data["tools"].items():
        if type(row) is not dict or set(row) != {"path", "identity"}:
            raise ValueError("managed-stage-private-cache-tool-shape")
        path = Path(row["path"])
        if not path.is_absolute() or file_identity(path, name) != row["identity"]:
            raise ValueError("managed-stage-private-cache-tool-drift")
    if json.dumps(data["inputs"], sort_keys=True) != json.dumps(
            _managed_stage_installed_identity(directory, root, data["tools"], deadline=deadline), sort_keys=True):
        raise ValueError("managed-stage-private-cache-input-drift")
    expected_stages = _managed_stage_command_stages()
    if (type(data["commands"]) is not list or len(data["commands"]) != 20
            or any(type(row) is not dict for row in data["commands"])
            or [row.get("stage") for row in data["commands"]] != expected_stages
            or any(type(row.get("exitCode")) is not int or row["exitCode"] != 0 for row in data["commands"])):
        raise ValueError("managed-stage-private-cache-command-closure")
    _managed_stage_remaining(deadline)
    return data


def install_managed_stage_diagnostic(directory: Path, wasi_sdk: Path, commands, *,
                                     deadline: float, source_inputs: dict, composer_source: Path, tool_paths: dict):
    """Acquire the private three-adapter SDK under the caller's ORIGINAL owner.

    Composer download is a separately pinned owner acquisition, never the normal
    installer's independent download clock. No Commands object or new timer is
    constructed here; all twenty children share the caller's count/log budget.
    """
    import math
    from tools.build_observation import file_identity
    from tools.dotnet_guest.compiler import packages
    from tools.dotnet_guest.composer import SIZE, DIGEST, observed, selection
    from tools.rust_capsule_project import digest

    def remaining():
        return _managed_stage_remaining(deadline)

    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or getattr(commands, "original_deadline", None) != deadline
            or commands.deadline > deadline - 5 or not 0 < commands.command_seconds <= 600
            or type(commands.shared) is not dict or set(commands.shared) != {"records", "bytes"}):
        raise ValueError("managed-stage-original-command-owner-required")
    remaining()
    if type(tool_paths) is not dict or set(tool_paths) != {"dotnet", "wasm-tools", "rustc", "cargo", "wit-bindgen"}:
        raise ValueError("managed-stage-exact-tool-paths")
    selected_tools = {}
    for name, value in tool_paths.items():
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("managed-stage-absolute-tool-path")
        selected_tools[name] = path.resolve(strict=True)
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("the pinned NativeAOT toolchain requires Linux x86-64")
    if type(source_inputs) is not dict or source_inputs != managed_stage_source_inputs(ROOT, deadline=deadline):
        raise ValueError("managed-stage-exact-source-inputs-required")
    wasi_sdk = wasi_sdk.resolve(strict=True)
    if read_file(wasi_sdk / "VERSION").decode().splitlines() != [
            "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
        raise ValueError("WASI SDK 29.0 with the pinned LLVM 21.1.4 toolchain is required")
    composer_bytes = read_file(composer_source, SIZE)
    if len(composer_bytes) != SIZE or digest(composer_bytes) != DIGEST:
        raise ValueError("managed-stage-original-composer-identity")
    directory = fresh(directory)
    sdk = ROOT / "sdk/dotnet-guest"
    selection(sdk)
    _write_managed_stage_metadata(directory / "managed-stage-source-inputs.json", source_inputs, deadline=deadline)
    for source, destination in (("global.json", "global.json"), ("nuget.config", "nuget.config"),
            ("probes/smoke/Smoke.csproj", "Smoke.csproj"), ("probes/smoke/packages.lock.json", "packages.lock.json")):
        (directory / destination).write_bytes(read_file(sdk / source))
    original_root, original_environment = commands.root, commands.environment
    environment = dict(original_environment)
    environment.update(TEMP=str(directory), TMP=str(directory), TMPDIR=str(directory), CARGO_BUILD_JOBS="2",
        CARGO_HOME=str(directory / "cargo-home"),
        DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
        DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", DOTNET_ROLL_FORWARD="Disable",
        DOTNET_CLI_HOME=str(directory / "cli-home"), MSBUILDDISABLENODEREUSE="1", RUSTUP_AUTO_INSTALL="0")
    rust = tomllib.loads(read_file(ROOT / "tools/toolchain.toml").decode())["rust"]["toolchain"]
    environment["RUSTUP_TOOLCHAIN"] = rust
    environment["RUSTC"] = str(selected_tools["rustc"])
    commands.root, commands.environment = directory, environment
    start = len(commands.records)

    def run(stage, *argv):
        remaining()
        if len(commands.shared["records"]) >= 128 or commands.shared["bytes"] >= 16 * 1024**2:
            raise ValueError("managed-stage-shared-command-bound")
        return commands.run("managed-stage-" + stage, *argv)

    try:
        tools = {}
        for name, expected in (("dotnet", b"10.0.100"), ("wasm-tools", b"wasm-tools 1.254.0"),
                ("rustc", ("rustc " + rust).encode()), ("cargo", ("cargo " + rust).encode()),
                ("wit-bindgen", b"wit-bindgen-cli 0.62.0")):
            path = selected_tools[name]
            raw = run(name + "-version", path, "--version").strip()
            if (raw != expected if name in ("dotnet", "wit-bindgen") else raw.split()[:2] != expected.split()):
                raise ValueError("managed-stage-tool-version:" + name)
            tools[name] = {"path": str(path), "identity": file_identity(path, name)}
        dotnet, wasm = Path(tools["dotnet"]["path"]), Path(tools["wasm-tools"]["path"])
        run("locked-restore", dotnet, "restore", directory / "Smoke.csproj", "--configfile", directory / "nuget.config",
            "--locked-mode", "--packages", directory / "packages", "--disable-parallel")
        for name, body in snapshot(sdk / "tools/package-hash").items():
            path = directory / "package-hash-source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        run("package-hash-build", dotnet, "build", directory / "package-hash-source/PackageHash.csproj",
            "-c", "Release", "--output", directory / "package-hash", "--artifacts-path", directory / "package-hash-artifacts",
            "-p:NuGetAudit=false", "-nodeReuse:false")
        packages(json.loads(read_file(sdk / "probes/smoke/packages.lock.json")), directory / "packages",
            lambda archive: run("nuget-content-hash", dotnet, directory / "package-hash/PackageHash.dll", archive).decode().strip())
        http_errors.install(sdk, directory, dotnet, run)
        target = directory / "runtime-target"
        run("runtime-compile", *_managed_stage_runtime_argv(directory, ROOT, tools["cargo"]["path"]))
        for name in MANAGED_STAGE_PROFILES:
            example, binary = ADAPTERS[name]
            run(name + "-component", wasm, "component", "new",
                target / "wasm32-unknown-unknown/release/examples" / (example.replace("-", "_") + ".wasm"),
                "-o", directory / binary)
        (directory / "runtime-inputs.json").write_bytes(runtime_inputs(ROOT))
        output = directory / "component-composer"
        output.mkdir()
        binary = output / "wac"
        with binary.open("xb") as stream:
            stream.write(composer_bytes)
        binary.chmod(0o755)
        if run("composer-version", binary, "--version").strip() != b"wac-cli 0.10.1":
            raise ValueError("managed-stage-composer-version")
        observed(directory, sdk)
        write_json(directory / "wasi-sdk.json", {"path": str(wasi_sdk)})
        remaining()
        if (source_inputs != managed_stage_source_inputs(ROOT, deadline=deadline)
                or any(file_identity(Path(row["path"]), name) != row["identity"] for name, row in tools.items())):
            raise ValueError("managed-stage-acquisition-inputs-changed")
        manifest = {"formatVersion": 1, "profile": MANAGED_STAGE_PROFILE,
            "selectedProfiles": list(MANAGED_STAGE_PROFILES), "standardSdkComplete": False,
            "inputs": _managed_stage_installed_identity(directory, ROOT, tools, deadline=deadline), "tools": tools,
            "commands": commands.records[start:]}
        remaining()
        _write_managed_stage_metadata(directory / MANAGED_STAGE_MANIFEST, manifest, deadline=deadline)
        remaining()
        return directory
    finally:
        commands.root, commands.environment = original_root, original_environment


# Official fixed acquisition metadata; no channel or latest-version resolution.
MANAGED_STAGE_FIXED_ARCHIVES = ({'kind': 'dotnet-sdk', 'url': 'https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.100/dotnet-sdk-10.0.100-linux-x64.tar.gz', 'hashAlgorithm': 'sha512', 'digest': 'f78dbac30c9af2230d67ff5c224de3a5dbf63f8a78d1c206594dedb80e6909d2cc8a9d865d5105c72c2fd2aa266fc0c6c77dedac60408cbccf272b116bd11b07', 'size': 239125653, 'expectedTopDirectory': None}, {'kind': 'rustc', 'url': 'https://static.rust-lang.org/dist/2026-07-16/rustc-1.97.1-x86_64-unknown-linux-gnu.tar.xz', 'hashAlgorithm': 'sha256', 'digest': '9819d0a32d56bd339585319c80260e332779f5541fd66838ab7e016d6c814819', 'size': 81050916, 'expectedTopDirectory': 'rustc-1.97.1-x86_64-unknown-linux-gnu', 'target': 'x86_64-unknown-linux-gnu', 'component': 'rustc'}, {'kind': 'cargo', 'url': 'https://static.rust-lang.org/dist/2026-07-16/cargo-1.97.1-x86_64-unknown-linux-gnu.tar.xz', 'hashAlgorithm': 'sha256', 'digest': 'e1be5f5ff7f7f80ca506fb65770b759edbdc6d303781ed71c5de8ec8a8394779', 'size': 11150208, 'expectedTopDirectory': 'cargo-1.97.1-x86_64-unknown-linux-gnu', 'target': 'x86_64-unknown-linux-gnu', 'component': 'cargo'}, {'kind': 'rust-std', 'url': 'https://static.rust-lang.org/dist/2026-07-16/rust-std-1.97.1-x86_64-unknown-linux-gnu.tar.xz', 'hashAlgorithm': 'sha256', 'digest': '1c1e704ae80126b7de34f72ea2825f7fd01736dec20732faed47374b95282fba', 'size': 30108400, 'expectedTopDirectory': 'rust-std-1.97.1-x86_64-unknown-linux-gnu', 'target': 'x86_64-unknown-linux-gnu', 'component': 'rust-std-x86_64-unknown-linux-gnu'}, {'kind': 'rust-std', 'url': 'https://static.rust-lang.org/dist/2026-07-16/rust-std-1.97.1-wasm32-unknown-unknown.tar.xz', 'hashAlgorithm': 'sha256', 'digest': 'fa0edb6e9f34faae5735554d62d50875eded839dc707d0f1c01467a918d8453b', 'size': 21949220, 'expectedTopDirectory': 'rust-std-1.97.1-wasm32-unknown-unknown', 'target': 'wasm32-unknown-unknown', 'component': 'rust-std-wasm32-unknown-unknown'}, {'kind': 'wasm-tools', 'url': 'https://github.com/bytecodealliance/wasm-tools/releases/download/v1.254.0/wasm-tools-1.254.0-x86_64-linux.tar.gz', 'hashAlgorithm': 'sha256', 'digest': 'd0efb16c9c859137b7ab3e99151c299cd47caee106ed4594561002f7a04945bd', 'size': 5862464, 'expectedTopDirectory': 'wasm-tools-1.254.0-x86_64-linux'})
MANAGED_STAGE_RUST_TEMPLATE_SHA256 = "a7e58d6671dcf7aa3593dcecbf96b49d006b9ef5cce1440d2d6709ea443c1e1d"


class _ManagedStageTarReader:
    """Forward-only decompressed stream with bounded metadata reads/clock."""
    def __init__(self, stream, deadline):
        self.stream, self.deadline, self.position, self.zero_headers = stream, deadline, 0, 0

    def tell(self):
        return self.position

    def read(self, size):
        _managed_stage_remaining(self.deadline)
        if not 0 <= size <= 1024**2 or self.position + size > 4 * 1024**3:
            raise ValueError("managed-stage-tar-stream-bound")
        data = self.stream.read(size)
        self.position += len(data)
        self.zero_headers = self.zero_headers + 1 if size == 512 and data == b"\0" * 512 else 0
        _managed_stage_remaining(self.deadline)
        return data

    def seek(self, offset, whence=0):
        if whence != 0 or offset < self.position:
            raise ValueError("managed-stage-tar-backward-seek")
        while self.position < offset:
            if not self.read(min(65536, offset - self.position)):
                raise ValueError("managed-stage-tar-truncated")
        return self.position


def _managed_stage_archive_hash(path, pin, *, deadline):
    import hashlib
    import stat
    _managed_stage_remaining(deadline)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != pin["size"] or before.st_size > 512 * 1024**2:
        raise ValueError("managed-stage-archive-size")
    hasher, count = hashlib.new(pin["hashAlgorithm"]), 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        while True:
            _managed_stage_remaining(deadline)
            data = stream.read(65536)
            if not data:
                break
            count += len(data)
            if count > pin["size"]:
                raise ValueError("managed-stage-archive-size")
            hasher.update(data)
        after = os.fstat(stream.fileno())
    if (count != pin["size"] or hasher.hexdigest() != pin["digest"] or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise ValueError("managed-stage-archive-digest")
    return {"size": count, "algorithm": pin["hashAlgorithm"], "digest": hasher.hexdigest()}


def _managed_stage_tar_path(name, *, parent=(), link=False):
    if (type(name) is not str or not name or name.startswith("/") or "\\" in name
            or len(name.encode("utf-8")) > 4096 or any(ord(c) < 32 for c in name)):
        raise ValueError("managed-stage-tar-path")
    parts = list(parent)
    for item in name.split("/"):
        if item in ("", "."):
            continue
        if item == "..":
            if not link or not parts:
                raise ValueError("managed-stage-tar-path")
            parts.pop()
        else:
            if len(item.encode("utf-8")) > 255:
                raise ValueError("managed-stage-tar-path")
            parts.append(item)
    return "/".join(parts)


def _managed_stage_tar_open(path, pin, deadline):
    import gzip
    import lzma
    opener = lzma.open if pin["url"].endswith(".tar.xz") else gzip.open
    return opener(path, "rb")


def _managed_stage_rust_grammar(body, component):
    """Authenticate the whole generated script against the pinned template."""
    import hashlib
    import re
    if len(body) > 1024**2:
        raise ValueError("managed-stage-rust-installer-source")
    normalized = body
    variables = ("PRODUCT_NAME", "REL_MANIFEST_DIR", "SUCCESS_MESSAGE", "LEGACY_MANIFEST_DIRS", "RUST_INSTALLER_VERSION")
    for variable in variables:
        key = "TEMPLATE_" + variable
        pattern = re.compile(rb"(?m)^" + key.encode() + rb"=([^\n]*)\n")
        matches = list(pattern.finditer(normalized))
        if len(matches) != 1 or not re.fullmatch(rb"[A-Za-z0-9 _.,!:'/\-]*", matches[0].group(1)):
            raise ValueError("managed-stage-rust-installer-assignment")
        scalar = matches[0].group(1)
        if scalar.startswith(b"'") and scalar.endswith(b"'"):
            scalar = scalar[1:-1]
        if b"'" in scalar:
            raise ValueError("managed-stage-rust-installer-assignment")
        if ((variable == "REL_MANIFEST_DIR" and scalar not in (b"rustlib", b"cargo"))
                or (variable == "LEGACY_MANIFEST_DIRS" and scalar not in
                    (b"", b"rustlib", b"cargo", b"rustlib,cargo", b"cargo,rustlib"))
                or (variable == "RUST_INSTALLER_VERSION" and scalar != b"3")):
            raise ValueError("managed-stage-rust-installer-assignment")
        normalized = pattern.sub(key.encode() + b"=%%" + key.encode() + b"%%\n", normalized)
    if hashlib.sha256(normalized).hexdigest() != MANAGED_STAGE_RUST_TEMPLATE_SHA256:
        raise ValueError("managed-stage-rust-installer-template")
    # These declarations and their actual parser/ldconfig fence are included in
    # the whole-template digest, rather than accepted by substring alone.
    if (body.count(b'valopt prefix "/usr/local" "set installation prefix"') != 1
            or body.count(b'opt ldconfig 1 "run ldconfig after installation (Linux only)"') != 1):
        raise ValueError("managed-stage-rust-installer-options")
    return {"component": component, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
        "normalizedTemplateSha256": MANAGED_STAGE_RUST_TEMPLATE_SHA256,
        "argv": ["--prefix=<one-owned-rust-prefix>", "--disable-ldconfig"]}


def _managed_stage_tar_visit(path, pin, *, deadline, destination=None, expected=None):
    """Preflight all members before any extraction; second pass is exact."""
    import hashlib
    import tarfile
    from pathlib import PurePosixPath
    _managed_stage_archive_hash(path, pin, deadline=deadline)
    rows, payloads, total, seen_names = [], {}, 0, set()
    with _managed_stage_tar_open(path, pin, deadline) as decompressed:
        reader = _ManagedStageTarReader(decompressed, deadline)
        with tarfile.open(fileobj=reader, mode="r:") as archive:
            for member in archive:
                _managed_stage_remaining(deadline)
                if len(rows) >= 65536 or member.size < 0 or member.size > 512 * 1024**2 or member.mode & 0o7000:
                    raise ValueError("managed-stage-tar-member-bound")
                name = _managed_stage_tar_path(member.name)
                if not name and not member.isdir():
                    raise ValueError("managed-stage-tar-path")
                top = pin["expectedTopDirectory"]
                if top is not None and name != top and not name.startswith(top + "/"):
                    raise ValueError("managed-stage-tar-top-directory")
                if name in seen_names:
                    raise ValueError("managed-stage-tar-duplicate")
                seen_names.add(name)
                if member.sparse is not None or any(k.startswith("GNU.sparse") for k in member.pax_headers):
                    raise ValueError("managed-stage-tar-sparse")
                kind = "file" if member.isfile() else "directory" if member.isdir() else "symlink" if member.issym() else "hardlink" if member.islnk() else None
                if kind is None or (kind != "file" and member.size != 0):
                    raise ValueError("managed-stage-tar-member-type")
                row = {"path": name, "kind": kind, "size": member.size, "mode": member.mode & 0o777}
                if kind in ("symlink", "hardlink"):
                    row["link"] = member.linkname
                    row["target"] = _managed_stage_tar_path(member.linkname,
                        parent=PurePosixPath(name).parts[:-1] if kind == "symlink" else (), link=True)
                if kind == "file":
                    total += member.size
                    if total > 4 * 1024**3:
                        raise ValueError("managed-stage-tar-expanded-bound")
                    capture = name.endswith(("/install.sh", "/components", "/manifest.in", "/rust-installer-version"))
                    kept, hashed, actual = bytearray(), hashlib.sha256(), 0
                    with archive.extractfile(member) as source:
                        while True:
                            _managed_stage_remaining(deadline)
                            block = source.read(65536)
                            if not block:
                                break
                            actual += len(block)
                            hashed.update(block)
                            if capture:
                                kept.extend(block)
                                if len(kept) > 1024**2:
                                    raise ValueError("managed-stage-installer-material-bound")
                    if actual != member.size:
                        raise ValueError("managed-stage-tar-truncated")
                    row["sha256"] = hashed.hexdigest()
                    if capture:
                        payloads[name] = bytes(kept)
                rows.append(row)
            zeros, trailing = reader.zero_headers, 0
            while True:
                block = reader.read(65536)
                if not block:
                    break
                trailing += len(block)
                if any(block):
                    raise ValueError("managed-stage-tar-trailing-data")
            if zeros < 1 or trailing < max(0, 2 - zeros) * 512:
                raise ValueError("managed-stage-tar-end-records")
    entries = {row["path"]: row for row in rows}
    directories = {""}
    for name, row in entries.items():
        for parent in PurePosixPath(name).parents:
            key = "" if str(parent) == "." else str(parent)
            directories.add(key)
            if key in entries and entries[key]["kind"] != "directory":
                raise ValueError("managed-stage-tar-nondirectory-parent")
        if row["kind"] == "directory":
            directories.add(name)
    if len(entries.keys() | directories) > 65536:
        raise ValueError("managed-stage-tar-entry-bound")
    for row in rows:
        if row["kind"] not in ("symlink", "hardlink"):
            continue
        target, seen = row["target"], {row["path"]}
        while target in entries and entries[target]["kind"] in ("symlink", "hardlink"):
            if target in seen or row["kind"] == "hardlink":
                raise ValueError("managed-stage-tar-link-cycle")
            seen.add(target)
            target = entries[target]["target"]
        if target not in entries and target not in directories:
            raise ValueError("managed-stage-tar-link-target")
        if row["kind"] == "hardlink" and entries.get(target, {}).get("kind") != "file":
            raise ValueError("managed-stage-tar-hardlink-target")
    result = {"members": rows, "expandedBytes": total, "entryCount": len(entries.keys() | directories),
        "fileCount": sum(row["kind"] != "directory" for row in rows), "directoryCount": len(directories)}
    if not rows:
        raise ValueError("managed-stage-tar-empty")
    if expected is not None and result != expected:
        raise ValueError("managed-stage-tar-preflight-changed")
    if destination is None:
        return result, payloads
    # The complete second preflight above finishes BEFORE opening destination.
    destination = fresh(destination)
    for name in sorted(directories, key=lambda item: (item.count("/"), item)):
        if name:
            (destination / name).mkdir(parents=True, exist_ok=True)
    # A third forward pass copies only regular bytes. Links are last, so a
    # verified link can never redirect creation of a later child.
    with _managed_stage_tar_open(path, pin, deadline) as decompressed:
        reader = _ManagedStageTarReader(decompressed, deadline)
        with tarfile.open(fileobj=reader, mode="r:") as archive:
            for member in archive:
                _managed_stage_remaining(deadline)
                name = _managed_stage_tar_path(member.name)
                row = entries[name]
                if row["kind"] != "file":
                    continue
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                hashed, actual = hashlib.sha256(), 0
                with archive.extractfile(member) as source, target.open("xb") as output:
                    while True:
                        _managed_stage_remaining(deadline)
                        block = source.read(65536)
                        if not block:
                            break
                        output.write(block)
                        hashed.update(block)
                        actual += len(block)
                if actual != row["size"] or hashed.hexdigest() != row["sha256"]:
                    raise ValueError("managed-stage-tar-copy-changed")
                target.chmod(0o755 if row["mode"] & 0o111 else 0o644)
    for row in rows:
        _managed_stage_remaining(deadline)
        target = destination / row["path"]
        if row["kind"] == "hardlink":
            os.link(destination / row["target"], target)
        elif row["kind"] == "symlink":
            os.symlink(row["link"], target)
    _managed_stage_archive_hash(path, pin, deadline=deadline)
    return result, payloads


def acquire_managed_stage_tools(directory: Path, commands, *, deadline: float, curl: Path, sh: Path):
    """Six pinned archives + four copied-component installs, same parent owner."""
    import re
    from tools.rust_capsule_project import digest
    _managed_stage_remaining(deadline)
    if (getattr(commands, "original_deadline", None) != deadline or commands.deadline > deadline - 5
            or not 0 < commands.command_seconds <= 600 or set(commands.shared) != {"records", "bytes"}):
        raise ValueError("managed-stage-original-command-owner-required")
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("managed-stage-fixed-linux-x64-required")
    curl, sh = Path(curl).resolve(strict=True), Path(sh).resolve(strict=True)
    if sh.name != "bash":
        raise ValueError("managed-stage-fixed-bash-required")
    host_tools = {name: {"path": str(path), "identity": _managed_stage_file_identity(path, name, 512 * 1024**2, deadline)}
                  for name, path in (("curl", curl), ("bash", sh))}
    directory = fresh(directory)
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,4096}", str(directory)):
        raise ValueError("managed-stage-rust-prefix-grammar")
    archives = directory / "archives"
    archives.mkdir()
    old_root, old_environment, old_seconds = commands.root, commands.environment, commands.command_seconds
    commands.root, commands.environment = directory, dict(old_environment)
    start, plans, expanded, entries = len(commands.records), [], 0, 0
    try:
        for ordinal, pin in enumerate(MANAGED_STAGE_FIXED_ARCHIVES):
            remaining = _managed_stage_remaining(deadline)
            commands.command_seconds = min(old_seconds, 180)
            if len(commands.shared["records"]) >= 128 or commands.shared["bytes"] >= 16 * 1024**2:
                raise ValueError("managed-stage-shared-command-bound")
            path = archives / pin["url"].rsplit("/", 1)[1]
            commands.run("managed-stage-fixed-download-" + str(ordinal), curl, "--fail", "--silent", "--show-error",
                "--location", "--proto", "=https", "--tlsv1.2", "--retry", "0", "--connect-timeout", "15",
                "--max-time", str(min(180, remaining)), "--max-filesize", str(pin["size"]), "--output", path, pin["url"])
            _managed_stage_archive_hash(path, pin, deadline=deadline)
            plan, payloads = _managed_stage_tar_visit(path, pin, deadline=deadline)
            expanded += plan["expandedBytes"]
            entries += plan["entryCount"]
            if expanded > 4 * 1024**3 or entries > 65536:
                raise ValueError("managed-stage-fixed-tool-aggregate-bound")
            plans.append((pin, path, plan, payloads))
        # All six inventories are admitted before extraction of the first.
        rust_prefix = directory / "rust"
        rust_prefix.mkdir()
        script_records, tools = [], {}
        for ordinal, (pin, path, plan, payloads) in enumerate(plans):
            extracted = directory / ("unpacked-" + str(ordinal))
            _managed_stage_tar_visit(path, pin, deadline=deadline, destination=extracted, expected=plan)
            if "component" in pin:
                top, component = pin["expectedTopDirectory"], pin["component"]
                if payloads.get(top + "/components") != (component + "\n").encode():
                    raise ValueError("managed-stage-rust-exact-component")
                script = payloads.get(top + "/install.sh")
                if script is None or next(row for row in plan["members"] if row["path"] == top + "/install.sh")["kind"] != "file":
                    raise ValueError("managed-stage-rust-regular-installer")
                record = _managed_stage_rust_grammar(script, component)
                manifest = payloads.get(top + "/" + component + "/manifest.in")
                if manifest is None:
                    raise ValueError("managed-stage-rust-component-manifest")
                known = {row["path"]: row["kind"] for row in plan["members"]}
                for raw in manifest.decode("utf-8").splitlines():
                    kind, relative = raw.split(":", 1)
                    safe = _managed_stage_tar_path(relative)
                    source_kind = known.get(top + "/" + component + "/" + safe)
                    if (kind not in ("file", "dir") or safe != relative
                            or (kind == "dir" and source_kind != "directory")
                            or (kind == "file" and source_kind not in ("file", "symlink", "hardlink"))):
                        raise ValueError("managed-stage-rust-manifest-path")
                record["manifestSha256"] = digest(manifest)
                record["source"] = script.decode("utf-8")
                script_records.append(record)
                commands.command_seconds = old_seconds
                if len(commands.shared["records"]) >= 128 or commands.shared["bytes"] >= 16 * 1024**2:
                    raise ValueError("managed-stage-shared-command-bound")
                _managed_stage_remaining(deadline)
                commands.run("managed-stage-fixed-install-" + component, sh, extracted / top / "install.sh",
                    "--prefix=" + str(rust_prefix), "--disable-ldconfig")
            elif pin["kind"] == "dotnet-sdk":
                tools["dotnet"] = extracted / "dotnet"
            else:
                tools["wasm-tools"] = extracted / pin["expectedTopDirectory"] / "wasm-tools"
        tools.update(rustc=rust_prefix / "bin/rustc", cargo=rust_prefix / "bin/cargo")
        source_pins = directory / "source-pins.json"
        _write_managed_stage_metadata(source_pins, {"profile": MANAGED_STAGE_PROFILE,
            "fixedArchives": MANAGED_STAGE_FIXED_ARCHIVES, "rustTemplateSha256": MANAGED_STAGE_RUST_TEMPLATE_SHA256}, deadline=deadline)
        identities = {name: _managed_stage_file_identity(path, name, 512 * 1024**2, deadline) for name, path in tools.items()}
        inventory = _managed_stage_tree_identity({"fixed-acquisition": directory}, deadline=deadline)
        receipt = directory / "acquisition-receipt.json"
        _write_managed_stage_metadata(receipt, {"profile": MANAGED_STAGE_PROFILE, "standardSdkComplete": False,
            "hostTools": host_tools, "archives": [{"pin": pin, "preflight": plan} for pin, _path, plan, _payload in plans],
            "scripts": script_records, "installedTools": {name: {"path": str(tools[name]), "identity": identity}
                for name, identity in identities.items()}, "allAcquisitionInputs": inventory,
            "commands": commands.records[start:], "versionProbesPendingPrivateInstaller": True}, deadline=deadline)
        return {"tools": tools, "receipt": receipt, "sourcePins": source_pins}
    finally:
        commands.root, commands.environment, commands.command_seconds = old_root, old_environment, old_seconds


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tools = commands.add_parser("install-tools")
    tools.add_argument("directory", type=Path)
    tools.add_argument("--wasi-sdk", type=Path, required=True)
    new = commands.add_parser("new")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=AUTHORING_TEMPLATES, default="greeting")
    new.add_argument("--name")
    resolve_ = commands.add_parser('resolve')
    resolve_.add_argument('project', type=Path)
    resolve_.add_argument('--candidate', type=Path, required=True)
    resolve_.add_argument('--dotnet', type=Path, required=True)
    resolve_.add_argument('--tools', type=Path, required=True)
    resolve_.add_argument('--feed-config', type=Path)
    resolve_.add_argument('--update-lock', action='store_true')
    for operation in ('add', 'update', 'remove'):
        command = commands.add_parser(operation, help='Edit exact application PackageReference inputs without restoring')
        command.add_argument('project', type=Path)
        command.add_argument('identity')
        if operation in {'add', 'update'}:
            command.add_argument('--version', required=True)
    review = commands.add_parser('review-lock', help='Accept an exact reviewed captured NuGet candidate')
    review.add_argument('project', type=Path)
    review.add_argument('--candidate', type=Path, required=True)
    review.add_argument('--expect', required=True)
    status = commands.add_parser('dependencies', help='Verify original NuGet inputs offline')
    status.add_argument('project', type=Path)
    for operation in ('test', 'watch'):
        command = commands.add_parser(operation, help='Delegate reviewed inputs to the maintained frontend')
        command.add_argument('project', type=Path)
        command.add_argument('--workspace', required=True)
        command.add_argument('--state-root', type=Path)
        command.add_argument('--select', action='append', default=[])
        command.add_argument('--frontend', type=Path)
        command.add_argument('--frontend-sha256')
        command.add_argument('--frontend-timeout', type=int, default=600)
        if operation == 'test':
            command.add_argument('--environment', choices=('node', 'portable'), default='node')
        else:
            command.add_argument('--tool-root')
    compile_ = commands.add_parser("build")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--tools", type=Path, required=True)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True)
    compile_.add_argument('--executable-approval')
    compile_.add_argument('--compiler-methods', action='store_true',
                          help='Collect bounded compiler method observations; no API execution or support claim')
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    authoring = args.command in {'add', 'update', 'remove', 'resolve', 'review-lock', 'dependencies', 'test', 'watch'}
    try:
        if authoring:
            from tools import dotnet_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            if args.command in {'test', 'watch'}:
                from tools import guest_authoring_frontend
                from tools.guest_dependency_inputs import layout
                owner, _app, _descriptor = layout(args.project, 'dotnet')
                delegated = dependencies.frontend(owner, args.command, workspace=args.workspace,
                    state_root=args.state_root, tool_root=getattr(args, 'tool_root', None),
                    selections=tuple(args.select), environment=getattr(args, 'environment', 'node'))
                outcome = guest_authoring_frontend.execute(owner, args.command, delegated,
                    frontend=args.frontend, expected=args.frontend_sha256, timeout_seconds=args.frontend_timeout)
                guest_authoring_frontend.emit(outcome)
                try:
                    dependencies.record(owner, {**outcome.evidence, 'stage': 'nuget-dependency-' + args.command,
                        'compilerExecution': 'maintained-frontend'})
                except (ValueError, OSError):
                    print('NuGet dependency frontend receipt unavailable; inspect workspace status.', file=sys.stderr)
                return outcome.exit_code
            if args.command in {'add', 'update', 'remove'}:
                result = dependencies.edit(args.project, args.command, identity=args.identity, version=getattr(args, 'version', None))
            elif args.command == 'resolve':
                from tools.application_dependency_store import DependencyError
                from tools.dotnet_application_dependencies import resolve
                candidate = dependencies.candidate_location(args.project, args.candidate)
                if any(os.path.lexists(candidate.with_name(candidate.name + suffix)) for suffix in ('.receipt.json', '.failed.json')):
                    raise DependencyError('nuget-dependency-candidate-use-fresh-attempt')
                lock = resolve(args.project, candidate, dotnet=args.dotnet, tools=args.tools,
                    policy=json.loads(read_file(args.feed_config)) if args.feed_config else None, update_lock=args.update_lock)
                result = dependencies.resolved(args.project, candidate, lock)
                paths.write_new(candidate.with_name(candidate.name + '.receipt.json'), canonical(result) + b'\n')
            elif args.command == 'review-lock':
                result = dependencies.review(args.project, args.candidate, args.expect)
            else:
                result = dependencies.status(args.project)
            receipt = dependencies.record(args.project, result)
            print(canonical({**result, 'receipt': str(receipt)}).decode())
            return 0
        if args.command == "install-tools":
            result = install(args.directory, args.wasi_sdk)
        elif args.command == "new":
            result = create(args.directory, args.template, args.name)
        else:
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository, tools=args.tools,
                executable_approval=args.executable_approval,
                **({'compiler_methods': True} if args.compiler_methods else {}))
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        if authoring:
            from tools import dotnet_dependency_authoring as dependencies
            from tools.build_snapshot import canonical
            from tools.dev_workflow import paths
            result = dependencies.failure(args.command, error)
            try:
                dependencies.record(args.project, result)
                if args.command == 'resolve' and result['reason'] not in {
                        'dependency-candidate-exists', 'nuget-dependency-candidate-use-fresh-attempt',
                        'nuget-candidate-cannot-overwrite-reviewed-input'}:
                    candidate = dependencies.candidate_location(args.project, args.candidate)
                    failed = candidate.with_name(candidate.name + '.failed.json')
                    if not os.path.lexists(failed):
                        failed.parent.mkdir(parents=True, exist_ok=True)
                        paths.write_new(failed, canonical(result) + b'\n')
            except (ValueError, OSError):
                pass
            print(canonical(result).decode(), file=sys.stderr)
            return 1
        print(f"C# capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
