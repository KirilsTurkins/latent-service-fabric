"""Current WIT-to-Java bridge. Never uses the removed TeaVM-WASI generator."""
from __future__ import annotations
import json
from pathlib import Path
from tools.java_guest import c, java
from tools.java_guest.model import Graph
from tools.rust_capsule_project import digest, inventory


def generate(run, source: Path, world: str, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    graph = json.loads(run("wit-graph", "wasm-tools", "component", "wit", source, "--json"))
    # The maintained generator supports synchronous ABI lowering for async WIT
    # operations. Wasmtime suspends the activation; Java owns no event loop.
    run("wit-bindings", "wit-bindgen", "c", source, "--world", world,
        "--rename-world", "probe", "--no-sig-flattening", "--async=-all", "--out-dir", destination)
    model = Graph(graph, world, (destination / "probe.h").read_text(encoding="utf-8"))
    (destination / "Bindings.java").write_text(java.generate(model), encoding="utf-8", newline="\n")
    (destination / "bridge.c").write_text(c.generate(model), encoding="utf-8", newline="\n")
    files = {p.name: p.read_bytes() for p in sorted(destination.iterdir()) if p.is_file()}
    if set(files) != {"Bindings.java", "bridge.c", "probe.h", "probe.c", "probe_component_type.o"}:
        raise ValueError("unexpected Java binding output")
    return {"formatVersion": 1, "world": world, "generator": "lsf-java-wit-v1+wit-bindgen-0.62.0",
            "outputs": json.loads(inventory(files)), "digest": digest(inventory(files)),
            "imports": len(model.imports), "exports": len(model.exports), "resources": len(model.resources)}
