"""Pinned, bounded C-to-component compilation; never executes a guest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time
import tomllib

from tools.build_process import run_bounded
from tools.build_observation import build_environment, file_identity
from tools.c_guest.bindings import digest, generate

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk/c-guest"
CAPABILITIES = ("blob", "callee", "events", "http", "metrics", "random", "secrets", "service", "streaming")


class Compiler:
    """One caller-owned finite build. No shell, guest execution or download."""

    def __init__(self, temporary: Path, timeout: int = 300, *, sdk: Path = SDK,
                 platform: Path | None = ROOT / "wit/platform", config: dict | None = None,
                 commands=None):
        if not 1 <= timeout <= 900:
            raise ValueError("C build deadline must be between 1 and 900 seconds")
        temporary.mkdir(parents=True, exist_ok=True)
        self.environment = build_environment(temporary)
        self.deadline = time.monotonic() + timeout
        self.sdk, self.platform, self.commands = sdk, platform, commands
        self.paths: dict[str, Path] = {}
        self.materials: dict[str, dict] = {}
        config = config or tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
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
        if self.commands is not None:
            return self.commands.run(tool, self.paths[tool], *arguments).decode("utf-8")
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
        if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 262144 for path in sources):
            raise ValueError("invalid or oversized C source")
        if isinstance(memory_bytes, bool) or memory_bytes < 2 * 1024 * 1024 or memory_bytes > 64 * 1024 * 1024 or memory_bytes % 65536:
            raise ValueError("C memory ceiling must be page-aligned and between 2 and 64 MiB")
        generated, lock = generate(self.run, wit_source, world, destination, self.platform)
        core, component = destination / "core.wasm", destination / "component.wasm"
        command = ["cc", "-std=c11", "-target", "wasm32-wasi", "-O2",
                   "-Wall", "-Wextra", "-Werror", "-mexec-model=reactor",
                   "-Wl,--no-entry", "-Wl,--export-memory", "-Wl,-z,stack-size=65536",
                   f"-Wl,--max-memory={memory_bytes}", "-I", str(generated),
                   "-I", str(self.sdk / "include"), *map(str, sources)]
        if trap:
            command.append(str(self.sdk / "src/trap.c"))
        command.extend([str(generated / "probe.c"), str(generated / "probe_component_type.o"),
                        "-o", str(core)])
        self.run("zig", *command)
        self.run("wasm-tools", "component", "new", str(core), "-o", str(component))
        self.run("wasm-tools", "validate", str(component))
        actual = self.run("wasm-tools", "component", "wit", str(component))
        if "wasi:" in actual or "wasi_snapshot_preview1" in actual:
            raise ValueError("ambient WASI is outside the C capsule authoring profile")
        self.check_unchanged()
        return component, lock


def safe_output(output: Path) -> Path:
    original = output.absolute()
    if any(path.is_symlink() for path in (original, *original.parents)):
        raise ValueError("C output cannot traverse a symlink")
    output = original.resolve()
    if (output.exists() or output == ROOT or output in ROOT.parents or
            (ROOT in output.parents and ROOT / "target" not in output.parents)):
        raise ValueError("choose a new output under target or outside the repository")
    return output


def build_capabilities(compiler: Compiler, output: Path) -> dict:
    profiles = ROOT / "tools/toolchain-smoke/examples"
    actual = {path.stem for path in (SDK / "examples").glob("*.c")}
    if actual != set(CAPABILITIES) - {"blob"}:
        raise ValueError("missing or unregistered C capability example")
    observations = {}
    for name in CAPABILITIES:
        profile_path = profiles / ("guest_" + name) / "profile.json"
        profile = json.loads(profile_path.read_text())
        source = SDK / "blob.c" if name == "blob" else SDK / "examples" / (name + ".c")
        print(f"C guest compile: {name}", flush=True)
        component, lock = compiler.compile([source], profile_path.parent, profile["world"],
                                          output / name, trap=name != "blob")
        observations[name] = {"componentDigest": digest(component.read_bytes()),
                              "componentBytes": component.stat().st_size, "bindings": lock}
        print(json.dumps({"name": name, **observations[name]}), flush=True)
    return observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = safe_output(args.output)
    output.mkdir(parents=True)
    compiler = Compiler(output / "tmp", 900)
    build_capabilities(compiler, output)


if __name__ == "__main__":
    main()
