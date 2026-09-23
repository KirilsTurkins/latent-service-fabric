#!/usr/bin/env python3
"""Generate C# stackful bindings while preserving the authoritative WIT graph.

Only the implementation calling convention is projected. The component linker
receives the original async types, identities and owned-resource declarations.
Generated output is exclusively owned and hash checked; --check never edits it.
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

SCHEMA = "latent.dotnet.bindings.v1"
GENERATOR = "wit-bindgen-cli 0.62.0"
MAX_BYTES = 16 * 1024 * 1024
MAX_FILES = 1024


class BindingError(ValueError):
    """An unsupported contract or unowned output is never a fallback."""


def run(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, encoding="utf-8",
                               timeout=90, check=False)
    if completed.returncode:
        raise BindingError(f"binding-command-failed:{Path(command[0]).name}:{completed.returncode}")
    if len(completed.stdout.encode("utf-8")) > MAX_BYTES:
        raise BindingError("binding-command-output-limit")
    return completed.stdout


def contract_graph(value):
    """Documentation is not a component type; preserve every other field."""
    if isinstance(value, dict):
        return {key: contract_graph(item) for key, item in value.items() if key != "docs"}
    if isinstance(value, list):
        return [contract_graph(item) for item in value]
    return value


def stackful_projection(document: dict) -> dict:
    """Change only async implementation kinds, never signatures or identities."""
    result = copy.deepcopy(document)
    for item in result.get("types", []):
        kind = item["kind"]
        unsupported = set(kind) & {"future", "stream", "map", "fixed-size-list"} if isinstance(kind, dict) else set()
        if unsupported:
            raise BindingError("unsupported-dotnet-guest-type:" + sorted(unsupported)[0])
    functions = []
    for interface in result.get("interfaces", []):
        functions.extend(interface.get("functions", {}).values())
    for world in result.get("worlds", []):
        for direction in ("imports", "exports"):
            functions.extend(item["function"] for item in world.get(direction, {}).values()
                             if "function" in item)
    for function in functions:
        kind = function["kind"]
        if kind == "async-freestanding":
            function["kind"] = "freestanding"
        elif isinstance(kind, dict):
            for asynchronous, synchronous in (("async-method", "method"), ("async-static", "static")):
                if asynchronous in kind:
                    function["kind"] = {synchronous: kind[asynchronous]}
    return result


def read_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise BindingError("binding-file-invalid-or-oversized")
    with path.open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise BindingError("binding-file-oversized")
    return data


def output_hashes(directory: Path) -> dict[str, str]:
    paths = sorted(directory.iterdir())
    if len(paths) > MAX_FILES:
        raise BindingError("binding-file-count-limit")
    hashes, total = {}, 0
    for path in paths:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", path.name):
            raise BindingError("binding-file-name-invalid")
        data = read_bytes(path)
        total += len(data)
        if total > MAX_BYTES:
            raise BindingError("binding-output-byte-limit")
        hashes[path.name] = hashlib.sha256(data).hexdigest()
    return hashes


def require_owned(output: Path) -> None:
    """Refuse unknown or modified files, including handwritten .cs files."""
    if output.is_symlink():
        raise BindingError("unowned-binding-output")
    if not output.exists():
        return
    if not output.is_dir():
        raise BindingError("unowned-binding-output")
    actual = output_hashes(output)
    if not actual:
        return
    try:
        receipt = json.loads(read_bytes(output / "bindings.json"))
    except (OSError, ValueError) as error:
        raise BindingError("unowned-binding-output") from error
    if (not isinstance(receipt, dict) or receipt.get("schemaVersion") != SCHEMA
            or receipt.get("generator") != GENERATOR
            or receipt.get("canonicalAbi") != "stackful"
            or not isinstance(receipt.get("outputs"), dict)):
        raise BindingError("unowned-binding-output")
    actual.pop("bindings.json", None)
    if receipt["outputs"] != actual:
        raise BindingError("modified-or-unowned-binding-output")


def install(generated: Path, output: Path, receipt: dict, *, check: bool = False) -> None:
    """Replace a verified owned directory as a unit, or compare without writes."""
    require_owned(output)
    expected = output_hashes(generated)
    if receipt.get("outputs") != expected or "bindings.json" in expected:
        raise BindingError("generated-receipt-disagrees")
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    expected["bindings.json"] = hashlib.sha256(receipt_bytes).hexdigest()
    if check:
        if not output.is_dir() or output_hashes(output) != expected:
            raise BindingError("generated-binding-drift")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".lsf-bindings-", dir=output.parent) as temporary:
        scratch = Path(temporary)
        new = scratch / "new"
        new.mkdir()
        for path in generated.iterdir():
            shutil.copyfile(path, new / path.name)
        (new / "bindings.json").write_bytes(receipt_bytes)
        if output_hashes(new) != expected:
            raise BindingError("generated-bindings-changed")
        # Recheck ownership after generation and copying, before any replacement.
        require_owned(output)
        old = scratch / "previous"
        if output.exists():
            output.rename(old)
        try:
            new.rename(output)
        except BaseException:
            if old.exists():
                old.rename(output)
            raise


def generate(source: Path, output: Path, world: str, bindgen: str, wasm_tools: str,
             *, check: bool = False) -> dict:
    source = source.resolve(strict=True)
    if output.is_symlink():
        raise BindingError("unowned-binding-output")
    output = output.resolve()
    if output == source or output in source.parents or source in output.parents:
        raise BindingError("binding-output-overlaps-source")
    require_owned(output)
    if run([bindgen, "--version"]).strip() != GENERATOR:
        raise BindingError("unqualified-wit-bindgen-version")
    if run([wasm_tools, "--version"]).split()[:2] != ["wasm-tools", "1.254.0"]:
        raise BindingError("unqualified-wasm-tools-version")
    original = run([wasm_tools, "component", "wit", str(source), "--no-docs"])
    graph = contract_graph(json.loads(run([wasm_tools, "component", "wit", str(source), "--json"])))
    projected_graph = stackful_projection(graph)
    with tempfile.TemporaryDirectory(prefix="lsf-dotnet-bindings-") as temporary:
        directory = Path(temporary)
        projection = directory / "stackful-bindings.wit"
        # Rewrite parsed, comment-free serialization, then compare the entire
        # reparsed graph. Matching text alone is not proof of type preservation.
        projection.write_text(re.sub(r"\basync\s+func\b", "func", original), encoding="utf-8")
        actual = contract_graph(json.loads(run([wasm_tools, "component", "wit", str(projection), "--json"])))
        if actual != projected_graph:
            raise BindingError("stackful-projection-changed-contract")
        generated = directory / "generated"
        run([bindgen, "c-sharp", str(projection), "--world", world,
             "--runtime", "native-aot", "--with-wit-results", "--out-dir", str(generated)])
        metadata = list(generated.glob("*_component_type.wit"))
        if len(metadata) != 1:
            raise BindingError("missing-unique-component-type")
        if metadata[0].is_symlink():
            raise BindingError("binding-file-invalid-or-oversized")
        metadata[0].write_text(original, encoding="utf-8")
        linked = contract_graph(json.loads(run([wasm_tools, "component", "wit", str(metadata[0]), "--json"])))
        if linked != graph:
            raise BindingError("component-type-changed-contract")
        receipt = {"schemaVersion": SCHEMA, "world": world, "canonicalAbi": "stackful",
                   "generator": GENERATOR,
                   "authoritativeWitSha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                   "outputs": output_hashes(generated)}
        install(generated, output, receipt, check=check)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["c-sharp", "csharp"])
    parser.add_argument("wit", type=Path)
    parser.add_argument("--world", required=True)
    parser.add_argument("--runtime", choices=["native-aot"], required=True)
    parser.add_argument("--with-wit-results", action="store_true", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="regenerate and fail on drift without editing output")
    args = parser.parse_args()
    try:
        generate(args.wit, args.out_dir, args.world,
                 os.environ.get("LSF_WIT_BINDGEN", "wit-bindgen"),
                 os.environ.get("LSF_WASM_TOOLS", "wasm-tools"), check=args.check)
        return 0
    except (BindingError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        parser.exit(1, f".NET guest bindings failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
