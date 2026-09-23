#!/usr/bin/env python3
"""Pinned, bounded C-to-component compilation; never executes a guest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.build_process import run_bounded
from tools.build_observation import build_environment, file_identity
from tools.stage_runtime_wit import stage

SDK = ROOT / "sdk/c-guest"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Compiler:
    """One caller-owned finite build. No shell, guest execution or download."""

    def __init__(self, temporary: Path, timeout: int = 300):
        if not 1 <= timeout <= 900:
            raise ValueError("C build deadline must be between 1 and 900 seconds")
        temporary.mkdir(parents=True, exist_ok=True)
        self.environment = build_environment(temporary)
        self.deadline = time.monotonic() + timeout
        self.paths: dict[str, Path] = {}
        self.materials: dict[str, dict] = {}
        config = tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        versions = {"zig": config["sdk"]["zig"],
                    "wit-bindgen": config["rust"]["dependencies"]["wit-bindgen"],
                    "wasm-tools": config["contracts"]["wasm-tools"]}
        for tool, version in versions.items():
            located = shutil.which(tool, path=self.environment.get("PATH"))
            if not located:
                raise ValueError(f"missing pinned C guest tool: {tool} {version}")
            path = Path(located).resolve(strict=True)
            self.paths[tool] = path
            self.materials[tool] = file_identity(path, tool)
            actual = self.run(tool, "version" if tool == "zig" else "--version").strip()
            if version not in actual.split():
                raise ValueError(f"{tool}: expected {version}, found {actual}")

    def run(self, tool: str, *arguments: str) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("C build deadline exceeded")
        result = run_bounded((str(self.paths[tool]), *map(str, arguments)), ROOT,
                             self.environment, timeout_seconds=min(remaining, 300),
                             max_output_bytes=4 * 1024 * 1024)
        return result.stdout.decode("utf-8")

    def check_unchanged(self) -> None:
        for name, path in self.paths.items():
            if file_identity(path, name) != self.materials[name]:
                raise ValueError("C compiler tool changed during build")

    def compile(self, sources: list[Path], wit_source: Path, world: str,
                destination: Path, *, memory_bytes: int = 16 * 1024 * 1024,
                trap: bool = True) -> tuple[Path, dict]:
        if not sources or len(sources) > 64:
            raise ValueError("C source count must be between 1 and 64")
        if memory_bytes < 2 * 1024 * 1024 or memory_bytes > 64 * 1024 * 1024 or memory_bytes % 65536:
            raise ValueError("C memory ceiling must be page-aligned and between 2 and 64 MiB")
        destination.mkdir(parents=True, exist_ok=False)
        staged = destination / "wit"
        stage(staged, wit_source)
        generated = destination / "bindings"
        generated.mkdir()
        self.run("wit-bindgen", "c", str(staged), "--world", world,
                 "--rename-world", "probe", "--out-dir", str(generated))
        names = {path.name for path in generated.iterdir()}
        if names != {"probe.h", "probe.c", "probe_component_type.o"}:
            raise ValueError("unexpected generated C binding outputs")
        binding_identity = {name: digest((generated / name).read_bytes()) for name in sorted(names)}
        core, component = destination / "core.wasm", destination / "component.wasm"
        command = ["cc", "-std=c11", "-target", "wasm32-wasi", "-O2",
                   "-Wall", "-Wextra", "-Werror", "-mexec-model=reactor",
                   "-Wl,--no-entry", "-Wl,--export-memory", "-Wl,-z,stack-size=65536",
                   f"-Wl,--max-memory={memory_bytes}", "-I", str(generated),
                   "-I", str(SDK / "include"), *map(str, sources)]
        if trap:
            command.append(str(SDK / "src/trap.c"))
        command.extend([str(generated / "probe.c"), str(generated / "probe_component_type.o"),
                        "-o", str(core)])
        self.run("zig", *command)
        self.run("wasm-tools", "component", "new", str(core), "-o", str(component))
        self.run("wasm-tools", "validate", str(component))
        actual = self.run("wasm-tools", "component", "wit", str(component))
        if "wasi:" in actual or "wasi_snapshot_preview1" in actual:
            raise ValueError("ambient WASI is outside the C capsule authoring profile")
        self.check_unchanged()
        return component, {"formatVersion": 1, "world": world,
                           "generator": self.run("wit-bindgen", "--version").strip(),
                           "outputs": binding_identity}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output == ROOT or (output in ROOT.parents):
        raise ValueError("choose a new, non-source output directory")
    output.mkdir(parents=True)
    compiler = Compiler(output / "tmp", 900)
    profiles = ROOT / "tools/toolchain-smoke/examples"
    for source in sorted((SDK / "examples").glob("*.c")):
        profile_path = profiles / ("guest_" + source.stem) / "profile.json"
        if not profile_path.is_file():
            continue
        profile = json.loads(profile_path.read_text())
        component, lock = compiler.compile([source], profile_path.parent, profile["world"], output / source.stem)
        print(json.dumps({"name": source.stem, "componentDigest": digest(component.read_bytes()),
                          "componentBytes": component.stat().st_size, "bindings": lock}))
    component, lock = compiler.compile([SDK / "blob.c"], profiles / "guest_blob",
        "tests:local-blobs/service@1.0.0", output / "blob", trap=False)
    print(json.dumps({"name": "blob", "componentBytes": component.stat().st_size, "bindings": lock}))


if __name__ == "__main__":
    main()
