#!/usr/bin/env python3
"""Exercise the real JS compiler's synchronous ABI with original async WIT.

This is a compiler diagnostic, not signed LSF admission or SDK qualification.
Every failed attempt is retained. No ambient runtime features are enabled.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.build_observation import build_environment
from tools.rust_capsule_build import Commands


def semantic(value):
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items() if key != "docs"}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


def projection(graph):
    result = copy.deepcopy(graph)
    for item in result.get("types", []):
        kind = item["kind"]
        if isinstance(kind, dict) and set(kind) & {"future", "stream", "map", "fixed-size-list"}:
            raise ValueError("unsupported-typescript-guest-type")
    functions = [function for interface in result.get("interfaces", [])
                 for function in interface.get("functions", {}).values()]
    for world in result.get("worlds", []):
        for direction in ("imports", "exports"):
            functions.extend(item["function"] for item in world.get(direction, {}).values()
                             if "function" in item)
    for function in functions:
        kind = function["kind"]
        if kind == "async-freestanding":
            function["kind"] = "freestanding"
        elif isinstance(kind, dict):
            for before, after in (("async-method", "method"), ("async-static", "static")):
                if before in kind:
                    function["kind"] = {after: kind[before]}
    return result


def probe(output: Path, node: Path, wasm_tools: Path, compiler: Path) -> None:
    output = output.resolve()
    if output.exists():
        raise ValueError("fresh-probe-output-required")
    output.mkdir(parents=True)
    (output / "tmp").mkdir()
    environment = build_environment(output / "tmp")
    commands = Commands(ROOT, output, environment)
    report = {"status": "failed", "qualified": False, "steps": commands.records}
    try:
        wit = ROOT / "sdk/typescript-guest/probes/world.wit"
        canonical = commands.run("canonical-wit", str(wasm_tools), "component", "wit", str(wit)).decode("utf-8")
        original = semantic(json.loads(commands.run("original-types", str(wasm_tools), "component", "wit", "--json", str(wit))))
        projected = output / "projected.wit"
        projected.write_text(re.sub(r"\basync\s+func\b", "func", canonical), encoding="utf-8")
        actual = semantic(json.loads(commands.run("projected-types", str(wasm_tools), "component", "wit", "--json", str(projected))))
        if actual != projection(original):
            raise ValueError("synchronous-projection-changed-authoritative-types")
        commands.run("componentize", str(node), str(ROOT / "tools/typescript_guest/componentize.mjs"),
                     str(compiler), str(projected), str(ROOT / "sdk/typescript-guest/probes/probe.mjs"), str(output))
        core = output / "core.wasm"
        bare = output / "bare.wasm"
        embedded = output / "embedded.wasm"
        component = output / "component.wasm"
        commands.run("remove-projected-metadata", str(wasm_tools), "strip", "--delete", "^component-type", str(core), "-o", str(bare))
        commands.run("restore-original-contract", str(wasm_tools), "component", "embed", str(wit), str(bare), "-w", "capsule", "-o", str(embedded))
        commands.run("compose", str(wasm_tools), "component", "new", str(embedded), "-o", str(component))
        commands.run("validate", str(wasm_tools), "validate", "--features", "all", str(component))
        final = semantic(json.loads(commands.run("final-types", str(wasm_tools), "component", "wit", "--json", str(component))))
        # This diagnostic has one selected world. Encoding moves that world
        # into a synthetic package; all original interface/type nodes and IDs
        # must remain identical, including async and ownership declarations.
        expected = copy.deepcopy(original)
        if len(expected["worlds"]) != 1 or len(expected["packages"]) != 1:
            raise ValueError("unexpected-probe-contract-shape")
        expected["packages"][0]["worlds"] = {}
        expected["packages"].append({"name": "root:component", "interfaces": {}, "worlds": {"root": 0}})
        expected["worlds"][0].update(name="root", package=1)
        if final != expected:
            raise ValueError("encoded-component-type-graph-drift")
        surface = commands.run("final-wit", str(wasm_tools), "component", "wit", str(component)).decode("utf-8")
        if "import wasi:" in surface or "echo: async func" not in surface or "run: async func" not in surface:
            raise ValueError("component-contract-or-ambient-authority-drift")
        (output / "component.wit").write_text(surface, encoding="utf-8")
        report.update(status="compiled-not-admitted", componentSha256=hashlib.sha256(component.read_bytes()).hexdigest(),
                      componentBytes=component.stat().st_size, originalTypes=original, finalTypes=final)
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--wasm-tools", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    arguments = parser.parse_args()
    probe(arguments.output, arguments.node.resolve(), arguments.wasm_tools.resolve(), arguments.compiler.resolve())
