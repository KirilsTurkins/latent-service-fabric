#!/usr/bin/env python3
"""Generate C# stackful canonical bindings without changing the WIT contract.

The Component Model permits the synchronous canonical ABI for async-typed WIT
functions. The pinned C# generator cannot yet lower indirect async arguments.
Only its implementation projection is normalized; the linker receives the
original, parsed WIT, including async function kinds and resource identities.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


class BindingError(ValueError):
    """An unqualified toolchain or unsupported contract is never a fallback."""


def run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if completed.returncode:
        raise BindingError(f"binding-command-failed:{Path(command[0]).name}:{completed.returncode}:{completed.stderr[-4000:]}")
    return completed.stdout


def contract_graph(value):
    """Documentation is not a component type; preserve every other graph field."""
    if isinstance(value, dict):
        return {key: contract_graph(item) for key, item in value.items() if key != "docs"}
    if isinstance(value, list):
        return [contract_graph(item) for item in value]
    return value


def stackful_projection(document: dict) -> dict:
    """The only permitted graph edit is async implementation calling convention."""
    result = copy.deepcopy(document)
    for item in result.get("types", []):
        kind = item["kind"]
        if isinstance(kind, dict) and set(kind) & {"future", "stream", "map", "fixed-size-list"}:
            raise BindingError("unsupported-dotnet-guest-type:" + next(iter(kind)))
    functions = []
    for interface in result.get("interfaces", []):
        functions.extend(interface.get("functions", {}).values())
    for world in result.get("worlds", []):
        for direction in ("imports", "exports"):
            functions.extend(item["function"] for item in world.get(direction, {}).values() if "function" in item)
    for function in functions:
        kind = function["kind"]
        if kind == "async-freestanding":
            function["kind"] = "freestanding"
        elif isinstance(kind, dict):
            for asynchronous, synchronous in (("async-method", "method"), ("async-static", "static")):
                if asynchronous in kind:
                    function["kind"] = {synchronous: kind[asynchronous]}
    return result


def generate(source: Path, output: Path, world: str, bindgen: str, wasm_tools: str) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    if output == source or output in source.parents or source in output.parents:
        raise BindingError("binding-output-overlaps-source")
    if run([bindgen, "--version"]).strip() != "wit-bindgen-cli 0.62.0":
        raise BindingError("unqualified-wit-bindgen-version")
    if not run([wasm_tools, "--version"]).startswith("wasm-tools 1.254.0 "):
        raise BindingError("unqualified-wasm-tools-version")
    original = run([wasm_tools, "component", "wit", str(source), "--no-docs"])
    graph = contract_graph(json.loads(run([wasm_tools, "component", "wit", str(source), "--json"])))
    projected_graph = stackful_projection(graph)
    with tempfile.TemporaryDirectory(prefix="lsf-dotnet-bindings-") as temporary:
        directory = Path(temporary)
        projection = directory / "stackful-bindings.wit"
        # Work only on wasm-tools' parsed, comment-free serialization, never on
        # arbitrary source text. Reparse and compare the entire graph below.
        projection.write_text(re.sub(r"\basync\s+func\b", "func", original))
        actual = json.loads(run([wasm_tools, "component", "wit", str(projection), "--json"]))
        if actual != projected_graph:
            raise BindingError("stackful-projection-changed-contract")
        generated = directory / "generated"
        run([bindgen, "c-sharp", str(projection), "--world", world,
             "--runtime", "native-aot", "--with-wit-results", "--out-dir", str(generated)])
        metadata = list(generated.glob("*_component_type.wit"))
        if len(metadata) != 1:
            raise BindingError("missing-unique-component-type")
        # This is the authority used by NativeAOT's component linker. Async WIT
        # remains async; generated managed methods merely use the stackful ABI.
        metadata[0].write_text(original)
        linked_graph = json.loads(run([wasm_tools, "component", "wit", str(metadata[0]), "--json"]))
        if linked_graph != graph:
            raise BindingError("component-type-changed-contract")
        receipt = {"schemaVersion": "latent.dotnet.bindings.v1", "world": world,
                   "canonicalAbi": "stackful", "generator": "wit-bindgen-cli 0.62.0",
                   "authoritativeWitSha256": hashlib.sha256(original.encode()).hexdigest(),
                   "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(generated.iterdir()) if p.is_file()}}
        output.mkdir(parents=True, exist_ok=True)
        # The SDK supplies a dedicated owned generated directory. Do not delete
        # other extensions; reject them instead of destroying user sources.
        if any(p.is_symlink() or not p.is_file() or p.suffix not in {".cs", ".wit", ".json", ".txt"}
               for p in output.iterdir()):
            raise BindingError("unowned-binding-output")
        for path in output.iterdir():
            path.unlink()
        for path in generated.iterdir():
            shutil.copyfile(path, output / path.name)
        (output / "bindings.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["c-sharp", "csharp"])
    parser.add_argument("wit", type=Path)
    parser.add_argument("--world", required=True)
    parser.add_argument("--runtime", choices=["native-aot"], required=True)
    parser.add_argument("--with-wit-results", action="store_true", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        generate(args.wit, args.out_dir, args.world,
                 os.environ.get("LSF_WIT_BINDGEN", "wit-bindgen"),
                 os.environ.get("LSF_WASM_TOOLS", "wasm-tools"))
        return 0
    except (BindingError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        parser.exit(1, f".NET guest bindings failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
