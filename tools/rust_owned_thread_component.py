"""Closed normal-builder boundary for the unqualified owned thread component.

The source/runtime selection is implemented separately. This boundary remains
closed until the actual private executor and canonical ABI graph is checked;
neither a source receipt nor an opaque guest pool handle opens it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

RECIPE = ('tools/rust_owned_thread_component.py',)


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
