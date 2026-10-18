"""Current WIT-to-Java bridge. Never uses the removed TeaVM-WASI generator."""
from __future__ import annotations
import json
from pathlib import Path
from tools.java_guest import c, java, async_imports
from tools.java_guest.model import Graph
from tools.rust_capsule_project import digest, inventory, read_file


def generate(run, source: Path, world: str, destination: Path, *, activation_profile: bool = False,
             fiber_io_profile: bool = False) -> dict:
    if type(fiber_io_profile) is not bool or fiber_io_profile and not activation_profile:
        raise ValueError('Java fiber I/O requires an explicitly selected activation profile')
    destination.mkdir(parents=True, exist_ok=False)
    graph = json.loads(run("wit-graph", "wasm-tools", "component", "wit", source, "--json"))
    try:
        Graph.preflight(graph, world)
    except ValueError as error:
        raise ValueError("java-binding-profile: " + str(error)) from error
    # The maintained generator supports synchronous ABI lowering for async WIT
    # operations. Wasmtime suspends the activation; Java owns no event loop.
    selection = ['-all']
    if fiber_io_profile:
        selected = Graph.preflight(graph, world)
        for function in selected.imports:
            if function['kind'] != 'async-freestanding': continue
            interface = graph['interfaces'][function['interface']]
            package = graph['packages'][interface['package']]['name']
            base, _, version = package.partition('@')
            identity = base + '/' + interface['name'] + ('@' + version if version else '')
            selection.insert(0, 'import:' + identity + '#' + function['name'])
        if len(selection) == 1: raise ValueError('Java fiber I/O requires actual async imports')
    run("wit-bindings", "wit-bindgen", "c", source, "--world", world,
        "--rename-world", "probe", "--no-sig-flattening", "--async=" + ','.join(selection), "--out-dir", destination)
    try:
        model = Graph(graph, world, (destination / "probe.h").read_text(encoding="utf-8"), async_imports=fiber_io_profile)
        if fiber_io_profile and any(function['kind'] == 'async-freestanding' and not function.get('asyncLowered')
                                    for function in model.imports):
            raise ValueError('requested asynchronous Java import was not lowered asynchronously')
    except ValueError as error:
        raise ValueError("java-c-abi: " + str(error)) from error
    # Some WIT parser shapes (for example an empty record) cannot be encoded
    # as valid component types. Check the maintained generator's real metadata
    # before invoking javac/TeaVM, not only after compiling the core module.
    run("bindings-metadata", "wasm-tools", "component", "wit", destination / "probe_component_type.o")
    bridge = async_imports.generate(model) if fiber_io_profile else c.generate(model)
    for name, text in (("Bindings.java", java.generate(model, activation_profile=activation_profile,
                        fiber_io_profile=fiber_io_profile)), ("bridge.c", bridge)):
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
