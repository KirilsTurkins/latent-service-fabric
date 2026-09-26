#!/usr/bin/env python3
"""Compile the maintained C SDK probes using an exact staged compiler inventory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_guest_capsules as owner
from tools.build_observation import file_identity
from tools.build_portable_dev_guests import builtin_inputs
from tools.build_process_signals import owned_cancellation
from tools.c_guest.compiler import Compiler, safe_output
from tools.dev_guest_tools import unpack_zig
from tools.dev_workflow import paths, tool_inventory
from tools.dev_workflow.common import decode, encode, require


def build(output: Path, payload: Path) -> None:
    output = safe_output(output)
    descriptor = decode(paths.read(payload, "templates/c/greeting/template.json"))["project"]
    with owned_cancellation() as cancellation:
        deadline = time.monotonic() + 900
        def check():
            cancellation.check()
            require(time.monotonic() < deadline, "c-portable-fixture-build-deadline")
        identity = tool_inventory.check(payload, descriptor, "linux-x86_64", observe=check)
        source = owner.source_inputs()
        fixture = owner.ROOT / "tools/portable-test-host/fixtures/capabilities.c"
        recipes = [file_identity(path, path.name) for path in (Path(__file__), fixture)]
        output.mkdir(mode=0o700, parents=True)
        with tempfile.TemporaryDirectory(prefix="lsf-c-portable-") as temporary:
            temporary = Path(temporary)
            zig = unpack_zig(payload / "sdk/zig.tar.xz", temporary / "zig", check)
            compiler = Compiler(temporary / "compiler", 900, installed={"zig": zig,
                **{name: payload / "sdk/bin" / name for name in ("wit-bindgen", "wasm-tools")}})
            bindings = {}
            for name in ("random", "metrics", "http"):
                check()
                profile = owner.EXAMPLES / ("guest_" + name)
                value = json.loads((profile / "profile.json").read_bytes())
                component, bindings[name] = compiler.compile([owner.ROOT / "sdk/c-guest/examples" / (name + ".c")],
                    profile, value["world"], temporary / name)
                owner.package_inputs(output / name, value, profile / "world.wit", component, maximum_fuel=10_000_000_000)
            component, bindings["capabilities"] = compiler.compile([fixture], owner.EXAMPLES / "capabilities_capsule",
                "tests:capabilities/service@0.1.0", temporary / "capabilities")
            (output / "capabilities").mkdir(mode=0o700)
            shutil.copyfile(component, output / "capabilities/component.wasm")
            builtin_inputs(output / "capabilities")
            compiler.check_unchanged()
        require(identity == tool_inventory.check(payload, descriptor, "linux-x86_64", observe=check)
            and source == owner.source_inputs(), "c-portable-fixture-inputs-changed")
        require(recipes == [file_identity(path, path.name) for path in (Path(__file__), fixture)], "c-portable-recipe-changed")
        (output / "build.json").write_bytes(encode({"formatVersion": 1, "language": "c", "ownerIssue": 545,
            "toolInventory": identity, "sourceDigest": owner.digest(source), "recipes": recipes, "bindings": bindings,
            "publisherAuthenticated": False, "executed": False,
            "components": {name: owner.digest((output / name / "component.wasm").read_bytes()) for name in bindings}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    args = parser.parse_args()
    build(args.output, args.tool_root.resolve(strict=True))
