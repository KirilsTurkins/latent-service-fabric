"""Pinned, activation-only Go Component Model compiler; no signing or grants."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from tools.build_observation import file_identity
from tools.go_guest.runtime import overlay
from tools.go_guest.sdk import install
from tools.rust_capsule_project import inventory, read_file, snapshot, write_json


class Compiler:
    def __init__(self, root: Path, sdk: Path, commands, *, offline_cache: Path | None = None,
                 source_root: Path | None = None):
        self.root, self.sdk, self.commands = root, sdk, commands
        self.source_root = source_root
        self.pins = json.loads(read_file(sdk / "toolchain.lock.json"))
        self.paths = {}
        for name in ("go", "componentize-go", "wasm-tools"):
            path = shutil.which(name, path=commands.environment["PATH"])
            if path is None:
                raise ValueError("missing-pinned-go-compiler-tool:" + name)
            self.paths[name] = Path(path).resolve(strict=True)
        self.materials = {name: file_identity(path, name) for name, path in self.paths.items()}
        self.root.mkdir()
        environment = commands.environment
        environment.update(GOTOOLCHAIN="local", GOWORK="off", GOFLAGS="-mod=readonly",
                           GOCACHE=str(root / "cache"), GOMODCACHE=str(root / "modules"))
        if offline_cache is not None:
            # Only module download records are copied. Go verifies their locked
            # sums when expanding them into this fresh private module cache.
            files, total = [], 0
            for path in sorted(offline_cache.rglob("*")):
                if path.is_symlink():
                    raise ValueError("offline-Go-cache-link")
                if path.is_dir():
                    continue
                raw = read_file(path, 32 * 1024 * 1024)
                total += len(raw)
                if len(files) >= 2048 or total > 64 * 1024 * 1024:
                    raise ValueError("offline-Go-cache-bound")
                files.append((path.relative_to(offline_cache), raw))
            for relative, raw in files:
                target = root / "modules/cache/download" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            environment.update(GOPROXY="off", GOSUMDB="off")
        version = self.run("go-version", "go", "version").split()
        if len(version) < 3 or version[2] != self.pins["go"]["version"]:
            raise ValueError("unreviewed-go-toolchain")
        if self.run("generator-version", "componentize-go", "--version").strip() != "componentize-go " + self.pins["componentizeGo"]["version"]:
            raise ValueError("unreviewed-componentize-go")
        if self.run("validator-version", "wasm-tools", "--version").split()[:2] != ["wasm-tools", "1.254.0"]:
            raise ValueError("unreviewed-go-component-validator")
        self.goroot = Path(self.run("go-root", "go", "env", "GOROOT").strip())

    def run(self, label: str, tool: str, *arguments) -> str:
        return self.commands.run(label, self.paths[tool], *arguments).decode("utf-8")

    def compile(self, source: Path, wit: Path, world: str, output: Path) -> tuple[Path, dict]:
        output.mkdir()
        generated = output / "module"
        comparison = output / "independent-bindings"
        arguments = ["--ignore-toml-files", "-d", wit, "-w", world]
        for directory in (generated, comparison):
            self.run("typed-bindings", "componentize-go", *arguments, "bindings", "--generate-stubs", "--format", "-o", directory)
        originals = snapshot(generated)
        if originals != snapshot(comparison):
            raise ValueError("non-reproducible-go-binding-generation")
        # No other module graph can be selected by a generated or handwritten
        # go.mod. The single reviewed package is vendored before runtime overlay.
        module = (generated / "go.mod").read_text()
        if module != "module wit_component\n\ngo 1.25\n\nrequire (\n    go.bytecodealliance.org/pkg v0.2.3\n)\n":
            raise ValueError("generated-go-module-drift")
        for name in ("go.mod", "go.sum"):
            module_input = read_file(source.parent / name)
            if module_input != read_file(self.sdk / "runtime-deps" / name):
                raise ValueError("unreviewed-go-module-input")
            (generated / name).write_bytes(module_input)
        sources = snapshot(source)
        if not sources or any(not name.endswith(".go") for name in sources):
            raise ValueError("Go application source must contain only captured .go files")
        replaced, source_locations = set(), {}
        for name, data in sources.items():
            text = data.decode("utf-8")
            package = re.search(r"(?m)^package\s+(export_[a-zA-Z0-9_]+)\s*$", text)
            if package is None:
                raise ValueError("Go entrypoint must implement its generated export package")
            destination = generated / package[1]
            stub = destination / "wit_bindings.go"
            if package[1] not in replaced:
                if not stub.is_file() or 'panic("not implemented")' not in stub.read_text():
                    raise ValueError("Go export stub does not match the authoritative WIT")
                # This is a generated stub in this fresh compiler-owned output,
                # never a user source or shared module cache.
                stub.unlink()
                replaced.add(package[1])
            target = destination / Path(name).name
            if target.exists():
                raise ValueError("duplicate-or-generated-Go-application-filename")
            target.write_bytes(data)
            if self.source_root is not None:
                source_locations[str(target)] = str(self.source_root / name)
                source_locations[target.relative_to(generated).as_posix()] = str(self.source_root / name)
                source_locations["./" + target.relative_to(generated).as_posix()] = str(self.source_root / name)
        if source_locations:
            write_json(self.commands.output / "diagnostic-files.json", source_locations)
        if any('panic("not implemented")' in path.read_text() for path in generated.glob("export_*/*.go")):
            raise ValueError("unimplemented-Go-WIT-export")
        install(self.sdk, generated)
        previous = self.commands.root
        self.commands.root = generated
        try:
            self.run("locked-module-download", "go", "mod", "download", "all")
            if (generated / "go.sum").read_bytes() != read_file(self.sdk / "runtime-deps/go.sum"):
                raise ValueError("unreviewed-go-dependency-checksum")
            self.run("vendor-locked-module", "go", "mod", "vendor")
            overlay_path = overlay(self.goroot, output / "runtime-overlay",
                                   generated / "vendor/go.bytecodealliance.org/pkg", sdk=self.sdk)
            self.commands.environment["GOFLAGS"] = "-mod=vendor -overlay=" + str(overlay_path)
            adapter = output / "closed-runtime.wasm"
            self.run("closed-runtime", "wasm-tools", "parse", self.sdk / "runtime/deny-wasi.wat", "-o", adapter)
            component = output / "component.wasm"
            self.run("component-build", "componentize-go", *arguments, "build", "--go", self.paths["go"], "--adapt", adapter, "-o", component)
            self.run("component-validate", "wasm-tools", "validate", "--features", "all", component)
            surface = self.run("component-wit", "wasm-tools", "component", "wit", component)
            if "import wasi:" in surface:
                raise ValueError("Go component retained ambient WASI authority")
            (output / "component.wit").write_text(surface, encoding="utf-8")
            self.check_unchanged()
            return component, json.loads(inventory(originals))
        finally:
            self.commands.root = previous

    def check_unchanged(self):
        if {name: file_identity(path, name) for name, path in self.paths.items()} != self.materials:
            raise ValueError("Go compiler tools changed during the build")
