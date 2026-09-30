"""Current WIT-to-Java bridge. Never uses the removed TeaVM-WASI generator."""
from __future__ import annotations
import json
from pathlib import Path
from tools.java_guest import c, java
from tools.java_guest.model import Graph
from tools.rust_capsule_project import digest, inventory, read_file


def generate(run, source: Path, world: str, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    graph = json.loads(run("wit-graph", "wasm-tools", "component", "wit", source, "--json"))
    try:
        Graph.preflight(graph, world)
    except ValueError as error:
        raise ValueError("java-binding-profile: " + str(error)) from error
    # The maintained generator supports synchronous ABI lowering for async WIT
    # operations. Wasmtime suspends the activation; Java owns no event loop.
    run("wit-bindings", "wit-bindgen", "c", source, "--world", world,
        "--rename-world", "probe", "--no-sig-flattening", "--async=-all", "--out-dir", destination)
    try:
        model = Graph(graph, world, (destination / "probe.h").read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError("java-c-abi: " + str(error)) from error
    # Some WIT parser shapes (for example an empty record) cannot be encoded
    # as valid component types. Check the maintained generator's real metadata
    # before invoking javac/TeaVM, not only after compiling the core module.
    run("bindings-metadata", "wasm-tools", "component", "wit", destination / "probe_component_type.o")
    for name, text in (("Bindings.java", java.generate(model)), ("bridge.c", c.generate(model))):
        value = text.encode()
        if len(value) > 4 * 1024 * 1024:
            raise ValueError("java-generated-code: binding output exceeds its finite four MiB limit")
        (destination / name).write_bytes(value)
    files = {p.name: read_file(p) for p in sorted(destination.iterdir()) if p.is_file()}
    if set(files) != {"Bindings.java", "bridge.c", "probe.h", "probe.c", "probe_component_type.o"}:
        raise ValueError("unexpected Java binding output")
    return {"formatVersion": 1, "world": world, "generator": "lsf-java-wit-v1+wit-bindgen-0.62.0",
            "outputs": json.loads(inventory(files)), "digest": digest(inventory(files)),
            "imports": len(model.imports), "exports": len(model.exports), "resources": len(model.resources)}
