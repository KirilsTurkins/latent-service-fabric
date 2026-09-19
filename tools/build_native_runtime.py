#!/usr/bin/env python3
"""Build an unsigned native release candidate from one exact clean commit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
import tomllib

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_runtime import files, verify
from tools.native_runtime.common import InstallError, document, execute, require
from tools.native_runtime_build import assemble, dependency_inventory, elf_identity

ROOT = Path(__file__).resolve().parents[1]


def build(arguments) -> dict:
    require(sys.platform == "linux" and platform.machine() == "x86_64", "native-linux-x86_64-build-required")
    require('VERSION_ID="24.04"' in files.read(Path("/usr/lib/os-release"), 8192).decode(),
            "ubuntu-24.04-build-required")
    toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    baseline = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text())
    require(arguments.version == workspace["workspace"]["package"]["version"], "release-version-must-match-source")
    require(toolchain == baseline["rust"]["toolchain"], "toolchain-baseline-mismatch")
    output = files.absolute(arguments.output)
    require(output.is_relative_to(ROOT / "target") and output != ROOT / "target", "build-output-must-be-under-own-target")
    environment = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "LANG": "C.UTF-8", "LC_ALL": "C",
                   "TZ": "UTC", "CARGO_TERM_COLOR": "never", "CARGO_INCREMENTAL": "0",
                   "CARGO_TARGET_DIR": str(ROOT / "target/native-build"), "CARGO_BUILD_JOBS": "2",
                   "CARGO_PROFILE_RELEASE_DEBUG": "0", "CARGO_PROFILE_RELEASE_STRIP": "debuginfo",
                   "RUSTFLAGS": "-C target-cpu=x86-64"}

    def run(command, timeout=60, maximum=1_048_576):
        status, captured = execute(command, timeout=timeout, maximum=maximum, cwd=str(ROOT), environment=environment)
        if status != 0:
            (ROOT / "target").mkdir(exist_ok=True)
            files.replace(ROOT / "target/native-build-failure.txt", captured[-65536:])
        require(status == 0, "native-build-command-failed-" + Path(command[0]).name)
        return captured

    commit = run(["git", "rev-parse", "HEAD"]).decode().strip()
    require(verify.SOURCE.fullmatch(arguments.commit) and arguments.commit == commit, "exact-source-commit-required")
    require(not run(["git", "status", "--porcelain", "--untracked-files=all"]).strip(), "clean-reviewed-source-required")
    epoch = int(run(["git", "show", "-s", "--format=%ct", "HEAD"]).decode())
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    compiler = run(["rustc", "+" + toolchain, "--version", "--verbose"]).decode()
    require(f"release: {toolchain}\n" in compiler and f"host: {verify.TARGET}\n" in compiler, "actual-toolchain-identity-mismatch")
    wasm_tools = run(["wasm-tools", "--version"]).decode().strip()
    require(re.fullmatch(r"wasm-tools " + re.escape(baseline["contracts"]["wasm-tools"])
                         + r"(?: \([^()\r\n]{1,128}\))?", wasm_tools),
            "pinned-wasm-tools-required")
    build_command = ["cargo", "+" + toolchain, "build", "--locked", "--release", "--target", verify.TARGET,
                     "-p", "latent", "-p", "latentd", "-p", "latent-wasmtime",
                     "--bin", "latent", "--bin", "latentd", "--bin", "latent-aot-compiler"]
    started = datetime.now(timezone.utc).isoformat()
    run(build_command, timeout=7200, maximum=8_388_608)
    run([sys.executable, "tools/build_echo_capsule.py"], timeout=1800, maximum=2_097_152)
    binary_root = Path(environment["CARGO_TARGET_DIR"]) / verify.TARGET / "release"
    materialized = Path(tempfile.mkdtemp(prefix="native-bundle-inputs-", dir=ROOT / "target"))
    assets = {}
    for name in ("latent", "latentd", "latent-aot-compiler"):
        require((binary_root / name).is_file() and not (binary_root / name).is_symlink(), "build-output-not-regular")
        shutil.copyfile(binary_root / name, materialized / name)
        assets["bin/" + name] = materialized / name
    dependencies = sorted({dependency for path in assets.values() for dependency in elf_identity(path, run)})
    abi = document(files.read(ROOT / "wit/host-abi-phase3-v4.json"))
    identity = {"version": arguments.version, "sourceCommit": commit, "target": verify.TARGET,
                "toolchain": {"rust": toolchain, "lockSha256": files.digest(ROOT / "Cargo.lock")},
                "engine": {"wasmtimeVersion": abi["wasmtimeVersion"], "hostAbiProfile": abi["id"],
                           "compilerSha256": files.digest(assets["bin/latent-aot-compiler"]),
                           "dynamicDependencies": dependencies}}
    for name in ("echo-capsule.wasm", "capsule.json", "contracts.json", "deployment.json", "input.json"):
        assets["examples/echo/" + name] = Path(environment["CARGO_TARGET_DIR"]) / "capsules/echo" / name
    for name in ("LICENSE", "NOTICE"):
        assets[name] = ROOT / name
    assets.update({"systemd/lsf.service": ROOT / "packaging/linux/lsf.service",
                   "INSTALL.md": ROOT / "packaging/linux/INSTALL.md",
                   "config/local-experimental-v1.json": ROOT / "packaging/linux/local-experimental-v1.json",
                   "config/external-capsule-v1.json": ROOT / "packaging/linux/external-capsule-v1.json"})
    metadata = json.loads(run(["cargo", "+" + toolchain, "metadata", "--locked", "--format-version", "1",
                               "--filter-platform", verify.TARGET], maximum=16_777_216))
    sbom, licenses = dependency_inventory(metadata, tomllib.loads((ROOT / "Cargo.lock").read_text()), commit, epoch)
    assets.update(licenses)
    provenance = {"_type": "https://in-toto.io/Statement/v1", "predicateType": "https://slsa.dev/provenance/v1",
                  "subject": [{"name": name, "digest": {"sha256": files.digest(path)}}
                              for name, path in sorted(assets.items()) if name.startswith(("bin/", "examples/echo/"))],
                  "predicate": {"buildDefinition": {"buildType": "https://github.com/KirilsTurkins/latent-service-fabric/native-build/v1",
                  "externalParameters": {"version": arguments.version, "sourceCommit": commit, "target": verify.TARGET},
                  "internalParameters": {"rustc": compiler, "wasmTools": wasm_tools,
                                         "command": build_command, "rustflags": environment["RUSTFLAGS"],
                                         "hostKernel": platform.release(), "distribution": "ubuntu-24.04",
                                         "crossHostReproducibilityTested": False},
                  "resolvedDependencies": [{"uri": "git+https://github.com/KirilsTurkins/latent-service-fabric",
                                            "digest": {"gitCommit": commit}},
                                           {"uri": "Cargo.lock", "digest": {"sha256": identity["toolchain"]["lockSha256"]}}]},
                  "runDetails": {"builder": {"id": "lsf-native-runtime-builder-v1-observed-local-build"},
                                 "metadata": {"startedOn": started, "finishedOn": datetime.now(timezone.utc).isoformat()}}}}
    compatibility = document(files.read(ROOT / "packaging/linux/compatibility.json"))
    require(not run(["git", "status", "--porcelain", "--untracked-files=all"]).strip(), "source-changed-during-build")
    manifest = assemble(output, ROOT, identity, assets, compatibility, provenance, sbom, epoch)
    require(run(["git", "rev-parse", "HEAD"]).decode().strip() == commit
            and not run(["git", "status", "--porcelain", "--untracked-files=all"]).strip(), "source-changed-during-assembly")
    staging = output / "artifact-check"
    staging.mkdir(mode=0o700)
    from tools.native_runtime.archive import check_tree, extract
    with files.regular(output / manifest["archive"]["name"]) as descriptor:
        extract(descriptor, staging, manifest["files"])
    check_tree(staging, manifest["files"])
    files.remove_tree(staging, maximum=8192)
    files.remove_tree(materialized, maximum=16)
    return {"schemaVersion": "latent.native-build-result.v1", "version": arguments.version, "sourceCommit": commit,
            "archiveSha256": manifest["archive"]["sha256"], "signed": False, "published": False,
            "cleanVmValidated": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = build(arguments)
    except (InstallError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"buildFailed": True, "diagnostic": str(error) if isinstance(error, InstallError) else "build-prerequisite-failure"}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
