#!/usr/bin/env python3
"""Compose the maintained real Angular fixture with the fixed public adapter.

The observed production application builder is a separate contract (#234).
Run npm ci --ignore-scripts and npm run build in examples/renderer-profile first.
No generated binary or bulk test output belongs in Git.
"""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    fixture = ROOT / "examples/renderer-profile"
    target = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")).resolve()
    subprocess.run(["node", "componentize-runtime.mjs"], cwd=fixture, check=True, timeout=300)
    subprocess.run(["cargo", "build", "--locked", "-p", "latent-angular-renderer-adapter",
                    "--target", "wasm32-unknown-unknown", "--release"],
                   cwd=ROOT, check=True, timeout=300)
    subprocess.run(["cargo", "clippy", "--locked", "-p", "latent-angular-renderer-adapter",
                    "--target", "wasm32-unknown-unknown", "--release", "--no-deps", "--", "-D", "warnings"],
                   cwd=ROOT, check=True, timeout=300)
    core = target / "wasm32-unknown-unknown/release/latent_angular_renderer_adapter.wasm"
    adapter = fixture / "dist/runtime/adapter.wasm"
    component = fixture / "dist/runtime/application.wasm"
    subprocess.run(["wasm-tools", "component", "new", str(core), "-o", str(adapter)],
                   check=True, timeout=30)
    # This composes a private synchronous JS instance inside the public async
    # component. It neither installs a host import nor executes during prepare.
    subprocess.run(["wasm-tools", "compose", str(adapter), "-d",
                    str(fixture / "dist/runtime/renderer.wasm"), "-o", str(component)],
                   check=True, timeout=30)
    subprocess.run(["wasm-tools", "validate", str(component)], check=True, timeout=30)
    print(component)


if __name__ == "__main__":
    main()
