#!/usr/bin/env python3
"""Build nine actual Java SDK components; execution is a separate required gate."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.java_capsule_project import ROOT, create, runtime_wit
from tools.java_capsule_build import build
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, fresh, read_file, write_json

NAMES = ("http", "streaming", "blob", "secrets", "events", "random", "metrics", "service", "callee")


def project(directory: Path, name: str) -> Path:
    if name not in NAMES: raise ValueError("unknown Java SDK fixture")
    source = ROOT / "tools/toolchain-smoke/examples" / ("guest_" + name)
    profile = json.loads(read_file(source / "profile.json"))
    directory = create(directory, "greeting", "guest-" + name)
    (directory / "wit/world.wit").write_bytes(runtime_wit(read_file(source / "world.wit"), "service"))
    (directory / "src/dev/latent/app/Capsule.java").write_bytes(read_file(ROOT / "sdk/java-guest/examples" / (name + ".java")))
    path = directory / "capsule-project.json"
    value = json.loads(read_file(path))
    value.update(world=profile["world"], tenant=None if name in {"service", "callee"} else "tests",
                 service={"service": "caller", "callee": "callee"}.get(name, "generic"))
    value["limits"].update(cpuFuel=10_000_000_000, childCalls=16 if name == "service" else 0,
        outboundRequests=8 if name in {"http", "streaming", "blob", "secrets", "events"} else 0,
        blobReadBytes=65536 if name == "blob" else 0, blobWriteBytes=65536 if name == "blob" else 0)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return directory


def compile_all(output: Path, wasi_sdk: Path, *, contracts_tool: Path | None = None,
                packager: Path | None = None) -> None:
    if (contracts_tool is None) != (packager is None):
        raise ValueError("supply both packaging tools or neither")
    output = output.absolute()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Java SDK fixtures require an independent output directory")
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output))
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    commands.environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0", CARGO_BUILD_JOBS="2")
    report = {"language": "java", "status": "failed", "runtimeQualified": False, "builds": []}
    deadline = time.monotonic() + 1800
    try:
        if contracts_tool is None:
            commands.run("packaging-tools", "cargo", "--config", ROOT / ".cargo/managed-guest.toml", "build", "--locked", "-p", "latent-packaging",
                         "--example", "package", "--example", "capsule_contracts")
            contracts_tool, packager = target / "debug/examples/capsule_contracts", target / "debug/examples/package"
        # A qualifier supplies its already captured executables. Rebuilding a
        # narrower Cargo package set can change feature unification and replace
        # those files, invalidating the qualification's binary identities.
        paths = {"contracts-tool": checked_path(contracts_tool), "packager": checked_path(packager)}
        before = {name: file_identity(path, name) for name, path in paths.items()}
        report["tools"] = before
        (output / "projects").mkdir()
        for name in NAMES:
            if time.monotonic() >= deadline: raise ValueError("Java SDK matrix deadline exceeded")
            source = project(output / "projects" / name, name)
            build(source, output / ("java-" + name), paths["contracts-tool"],
                  paths["packager"], "https://github.com/KirilsTurkins/latent-service-fabric", wasi_sdk,
                  timeout=min(900, deadline - time.monotonic()))
            report["builds"].append(name)
        report["toolsAfter"] = {name: file_identity(path, name) for name, path in paths.items()}
        if report["toolsAfter"] != before:
            raise ValueError("Java SDK packaging tools changed during the matrix")
        if time.monotonic() >= deadline: raise ValueError("Java SDK matrix deadline exceeded")
        report["status"] = "built-execution-required"
    finally:
        report["commands"] = commands.records
        write_json(output / "SDK-BUILD.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wasi-sdk", type=Path, required=True)
    parser.add_argument("--contracts-tool", type=Path)
    parser.add_argument("--packager", type=Path)
    args = parser.parse_args()
    compile_all(args.output, args.wasi_sdk, contracts_tool=args.contracts_tool, packager=args.packager)
