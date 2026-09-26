#!/usr/bin/env python3
"""Build actual Go SDK ownership fixtures; execution is a separate required gate."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.go_capsule_project import ROOT, RUNTIME_IMPORTS, create
from tools.go_capsule_build import build
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, fresh, read_file, snapshot, write_json

NAMES = ("http", "streaming", "blob", "secrets", "events", "random", "metrics", "service", "callee")


def project(directory: Path, name: str) -> Path:
    source = ROOT / "tools/toolchain-smoke/examples" / ("guest_" + name)
    profile = json.loads(read_file(source / "profile.json"))
    directory = create(directory, "greeting", "guest-" + name)
    world = read_file(source / "world.wit").decode()
    extra = [identity for identity in RUNTIME_IMPORTS if "import " + identity + ";" not in world]
    if world.count("world service {") != 1:
        raise ValueError("guest SDK fixture world drift")
    world = world.replace("world service {", "world service {\n" +
                          "\n".join("    import " + identity + ";" for identity in extra))
    (directory / "wit/world.wit").write_text(world, encoding="utf-8")
    (directory / "src/main.go").write_bytes(read_file(ROOT / "sdk/go-guest/examples" / (name + ".go")))
    if profile["capability"]:
        for path, data in snapshot(ROOT / "wit/platform" / profile["witDirectory"]).items():
            destination = directory / "wit/deps" / profile["witDirectory"] / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    path = directory / "capsule-project.json"
    value = json.loads(read_file(path))
    # Reusable contracts keep their tests: namespace. As with the Rust/C
    # fixtures, only the operator's admission selects tenant-a; the capsule
    # itself must not assert a conflicting owner for that namespace.
    value.update(world=profile["world"], tenant=None if name in {"service", "callee"} else "tests",
                 service={"service": "caller", "callee": "callee"}.get(name, "generic"))
    value["limits"].update(cpuFuel=10_000_000_000, childCalls=16 if name == "service" else 0,
        outboundRequests=8 if name in {"http", "streaming", "blob", "secrets", "events"} else 0,
        blobReadBytes=65536 if name == "blob" else 0, blobWriteBytes=65536 if name == "blob" else 0)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return directory


def packaging_tools(commands, target: Path, contracts_tool: Path | None, packager: Path | None):
    if (contracts_tool is None) != (packager is None):
        raise ValueError("provide both captured packaging executables")
    if contracts_tool is None:
        commands.run("packaging-tools", "cargo", "--config", ROOT / ".cargo/managed-guest.toml", "build", "--locked", "-p", "latent-packaging",
                     "--example", "package", "--example", "capsule_contracts")
        contracts_tool, packager = (target / "debug/examples/capsule_contracts", target / "debug/examples/package")
    return checked_path(contracts_tool), checked_path(packager)


def compile_all(output: Path, *, contracts_tool: Path | None = None, packager: Path | None = None) -> None:
    if (contracts_tool is None) != (packager is None):
        raise ValueError("provide both captured packaging executables")
    output = output.absolute()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Go SDK fixtures require an independent output directory")
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output))
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    commands.environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0")
    report = {"language": "go", "status": "failed", "runtimeQualified": False, "builds": []}
    try:
        contracts_tool, packager = packaging_tools(commands, target, contracts_tool, packager)
        paths = {"contracts-tool": contracts_tool, "packager": packager}
        report["packagingTools"] = {name: file_identity(path, name) for name, path in paths.items()}
        (output / "projects").mkdir()
        for name in NAMES:
            source = project(output / "projects" / name, name)
            build(source, output / ("go-" + name), contracts_tool,
                  packager, "https://github.com/KirilsTurkins/latent-service-fabric")
            report["builds"].append(name)
        if {name: file_identity(path, name) for name, path in paths.items()} != report["packagingTools"]:
            raise ValueError("Go SDK packaging executables changed")
        report["status"] = "built-execution-required"
    finally:
        report["commands"] = commands.records
        write_json(output / "SDK-BUILD.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contracts-tool", type=Path)
    parser.add_argument("--packager", type=Path)
    args = parser.parse_args()
    compile_all(args.output, contracts_tool=args.contracts_tool, packager=args.packager)
