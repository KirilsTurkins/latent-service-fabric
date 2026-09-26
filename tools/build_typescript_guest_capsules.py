#!/usr/bin/env python3
"""Compile actual generated-binding SDK fixtures; execution is a separate gate."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, fresh, read_file, snapshot, write_json
from tools.typescript_guest.project import create
from tools.typescript_guest.build import build

NAMES = ("http", "streaming", "blob", "secrets", "events", "random", "metrics", "service", "callee")


def project(directory: Path, name: str) -> Path:
    if name not in NAMES:
        raise ValueError("unknown SDK fixture")
    source = ROOT / "tools/toolchain-smoke/examples" / ("guest_" + name)
    profile = json.loads(read_file(source / "profile.json"))
    directory = create(directory, "greeting", "guest-" + name)
    (directory / "wit/world.wit").write_bytes(read_file(source / "world.wit"))
    (directory / "src/main.ts").write_bytes(read_file(ROOT / "sdk/typescript-guest/examples" / (name + ".ts")))
    if profile["capability"]:
        for path, data in snapshot(ROOT / "wit/platform" / profile["witDirectory"]).items():
            destination = directory / "wit/deps" / profile["witDirectory"] / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    path = directory / "capsule-project.json"
    value = json.loads(read_file(path))
    value.update(world=profile["world"], tenant=None if name in {"service", "callee"} else "tests",
                 service={"service": "caller", "callee": "callee"}.get(name, "generic"))
    value["limits"].update(cpuFuel=10_000_000_000, childCalls=16 if name == "service" else 0,
        wallTimeLimitMillis=240_000 if name == "service" else 120_000,
        outboundRequests=8 if name in {"http", "streaming", "blob", "secrets", "events"} else 0,
        blobReadBytes=65536 if name == "blob" else 0, blobWriteBytes=65536 if name == "blob" else 0)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return directory


def compile_all(output: Path, tools: Path, names=NAMES):
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("SDK fixtures require an independent output directory")
    output = fresh(output)
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    suffix = ".exe" if os.name == "nt" else ""
    report = {"language": "typescript", "status": "failed", "runtimeQualified": False, "builds": []}
    try:
        (output / "projects").mkdir()
        for name in names:
            source = project(output / "projects" / name, name)
            build(source, output / ("typescript-" + name), target / ("debug/examples/capsule_contracts" + suffix),
                  target / ("debug/examples/package" + suffix), "https://github.com/KirilsTurkins/latent-service-fabric", tools=tools)
            report["builds"].append(name)
        report["status"] = "built-execution-required"
    finally:
        write_json(output / "SDK-BUILD.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--only", nargs="+", choices=NAMES, help="local iteration only; never full qualification")
    arguments = parser.parse_args()
    compile_all(arguments.output, arguments.tools, arguments.only or NAMES)
