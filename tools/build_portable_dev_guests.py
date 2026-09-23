#!/usr/bin/env python3
"""Compile the maintained Rust SDK probes for the closed portable test profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_guest_capsules as owner
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_process import run_bounded


def build(output: Path) -> None:
    deadline = time.monotonic() + 900
    output = output.absolute()
    if not output.is_relative_to(owner.ROOT / "target"):
        raise ValueError("repository fixture outputs must be under target")
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "tmp"
    temporary.mkdir(exist_ok=True)
    environment = build_environment(temporary)
    tools, materials = resolve_tools(tomllib.loads((owner.ROOT / "tools/toolchain.toml").read_text()), owner.ROOT, environment)
    environment.update({"RUSTC": str(tools["rustc"]), "CARGO_INCREMENTAL": "0",
        "CARGO_TARGET_DIR": str(Path(os.environ.get("CARGO_TARGET_DIR", owner.ROOT / "target")).absolute())})
    sources = owner.source_inputs()
    recipe = file_identity(Path(__file__), "portable-fixture-recipe", 1024 * 1024)
    names = ("random", "metrics", "http")
    def run(*command):
        timeout = min(600, deadline - time.monotonic())
        if timeout <= 0:
            raise ValueError("portable fixture build deadline")
        result = run_bounded([str(tools.get(command[0], command[0])), *command[1:]], owner.ROOT,
            environment, timeout_seconds=timeout, max_output_bytes=4 * 1024 * 1024)
        print(result.stdout.decode("utf-8", errors="replace"), end="")
        print(result.stderr.decode("utf-8", errors="replace"), end="")
    examples = [part for name in names for part in ("--example", "guest-" + name)]
    examples.extend(["--example", "capabilities-capsule"])
    run("cargo", "build", "-p", "latent-toolchain-smoke", "--target", "wasm32-unknown-unknown", "--release", "--locked", *examples)
    for name in names:
        source = owner.EXAMPLES / ("guest_" + name)
        component = output / (name + ".wasm")
        run("wasm-tools", "component", "new", str(Path(environment["CARGO_TARGET_DIR"]) /
            "wasm32-unknown-unknown/release/examples" / ("guest_" + name + ".wasm")), "-o", str(component))
        run("wasm-tools", "validate", str(component))
        owner.package_inputs(output / name, json.loads((source / "profile.json").read_bytes()), source / "world.wit",
            component, maximum_fuel=10_000_000_000)
    # The maintained capabilities conformance fixture intentionally derives its
    # value types from the actual component, as its production Rust tests do.
    directory = output / "capabilities"
    directory.mkdir(exist_ok=True)
    component = directory / "component.wasm"
    run("wasm-tools", "component", "new", str(Path(environment["CARGO_TARGET_DIR"]) /
        "wasm32-unknown-unknown/release/examples/capabilities_capsule.wasm"), "-o", str(component))
    run("wasm-tools", "validate", str(component))
    manifest = json.loads((owner.ROOT / "examples/echo-contract/capsule.json").read_bytes())
    manifest["metadata"] = {"name": "generic", "annotations": {"latent.dev/purpose": "portable-conformance-fixture"}}
    manifest["compatibility"]["minimumFabricVersion"] = tomllib.loads((owner.ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"]
    manifest["component"].update(digest=owner.digest(component.read_bytes()), world="tests:capabilities/service@0.1.0")
    manifest["exports"] = ["tests:capabilities/api@0.1.0"]
    manifest["imports"] = [{"contract": name, "optional": False} for name in (
        "latent:context/context@0.1.0", "latent:log/log@0.1.0", "latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0")]
    owner.write_json(directory / "capsule.json", manifest)
    owner.write_json(directory / "contracts.json", {"format_version": 1, "contracts": []})
    if sources != owner.source_inputs() or materials != [file_identity(path, name) for name, path in sorted(tools.items())]:
        raise ValueError("fixture inputs changed during build")
    if recipe != file_identity(Path(__file__), "portable-fixture-recipe", 1024 * 1024):
        raise ValueError("fixture recipe changed during build")
    owner.write_json(output / "build.json", {"formatVersion": 1, "sourceDigest": owner.digest(sources),
        "tools": materials, "recipe": recipe, "owner": "tools/build_guest_capsules.py", "maximumFuel": "10000000000",
        "components": {name: owner.digest((output / name / "component.wasm").read_bytes()) for name in (*names, "capabilities")}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
