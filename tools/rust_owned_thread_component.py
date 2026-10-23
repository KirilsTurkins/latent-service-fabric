"""Closed normal-builder boundary for the unqualified owned thread component.

The source/runtime selection is implemented separately. This boundary remains
closed until the actual private executor and canonical ABI graph is checked;
neither a source receipt nor an opaque guest pool handle opens it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

RECIPE = ('tools/rust_owned_thread_component.py',
          'tools/rust_thread_object_graph.py', 'tools/rust_thread_callback_paths.py',
          'crates/latent-component-threading/src/rust_catalogue/original-wit-metadata.bin',
          'crates/latent-component-threading/src/rust_catalogue/adapted-wit-metadata.bin')


def adapt_original_public_wit(core: bytes) -> bytes:
    """Selected THREAD metadata effect; ordinary synchronous Core ABI survives.

    Only the complete authenticated original WIT payload may be adapted. The
    exact original and adapted metadata remain captured recipe inputs. Default
    runtime profiles do not call this explicit thread-specific transformation.
    """
    from tools import rust_thread_object_graph as graph
    from tools.rust_thread_callback_paths import section
    from tools.rust_capsule_project import ROOT, read_file
    graph.require(len(core) <= 1024 * 1024, 'rust-thread-public-wit-core-bound')
    base = ROOT / 'crates/latent-component-threading/src/rust_catalogue'
    original = read_file(base / 'original-wit-metadata.bin', 16 * 1024)
    adapted = read_file(base / 'adapted-wit-metadata.bin', 16 * 1024)
    graph.require(core[:8] == b'\0asm\x01\0\0\0', 'rust-thread-public-wit-core-encoding')
    reader = graph.Reader(core[8:])
    output = bytearray(core[:8])
    changed = False
    count = 0
    while reader.p < len(reader.raw):
        graph.require(count < 512, 'rust-thread-public-wit-section-bound')
        count += 1
        kind = reader.byte()
        payload = reader.blob(reader.number())
        name = graph.Reader(payload).name() if kind == 0 else None
        if name and name.startswith('component-type'):
            graph.require(not changed and payload == original,
                          'rust-thread-authentic-original-wit-required')
            payload = adapted
            changed = True
        output.extend(section(kind, payload))
    graph.require(changed, 'rust-thread-authentic-original-wit-required')
    return bytes(output)


class Route(Protocol):
    def materials(self, output: Path) -> list[dict]: ...
    def assets(self) -> tuple[tuple[str, str, str], ...]: ...
    def check(self) -> None: ...
    def componentize(self, commands, wasm_tools: Path, module: Path,
                     output: Path, source_digest: str) -> None: ...
    def verify_final(self, component: bytes, surface: dict) -> None: ...


def select(prepared_std, rustc: Path) -> Route:
    # Deliberately before application compilation. A future implementation
    # must bind the exact tool/build provenance and final graph here; changing
    # a boolean in a caller-selected document is never an enablement path.
    raise ValueError('rust-thread-private-executor-and-canonical-graph-unqualified')
