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
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json


class Compiler:
    def __init__(self, root: Path, sdk: Path, commands, *, offline_cache: Path | None = None,
                 source_root: Path | None = None, application_closure=None):
        self.root, self.sdk, self.commands = root, sdk, commands
        self.source_root = source_root
        self.application_closure, self.isolation = application_closure, None
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
        if application_closure is not None:
            if offline_cache is not None:
                raise ValueError("captured-Go-build-cannot-use-an-additional-cache")
            from tools.go_application_dependencies import selection
            selection(application_closure.lock["selection"])
            roots = [row for row in application_closure.lock["artifacts"]
                     if row["metadata"].get("assetType") == "selected-module-downloads"]
            if len(roots) != 1:
                raise ValueError("captured-Go-module-download-closure-missing")
            offline_cache = application_closure.work / roots[0]["mount"]
            environment.update(GOENV="off", CGO_ENABLED="0", GOOS="wasip1", GOARCH="wasm")
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
                if len(files) >= (32768 if application_closure else 2048) or total > (256 if application_closure else 64) * 1024 * 1024:
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
        if application_closure is not None:
            from tools.captured_compiler_isolation import Isolation
            selected_tools = dict(self.paths)
            selected_tools["gofmt"] = self.goroot / "bin/gofmt"
            for path in sorted((self.goroot / "pkg/tool").rglob("*")):
                if path.is_file():
                    with path.open("rb") as source:
                        if source.read(4) == b"\x7fELF":
                            selected_tools["go-helper/" + path.relative_to(self.goroot).as_posix()] = path
            self.isolation = Isolation(root.parent, selected_tools, {"go-compiler-and-runtime": self.goroot})
            self.isolation.enable_children(self.goroot / "bin")
            environment["GOROOT"] = str(self.goroot)
            self.isolation.protect_inputs(commands.root)
            write_json(commands.output / "compiler-containment.json", self.isolation.receipt)

    def run(self, label: str, tool: str, *arguments) -> str:
        command = (self.isolation.wrap(self.paths[tool], list(map(str, arguments)), self.commands.root, self.commands.environment)
                   if self.isolation is not None else [self.paths[tool], *arguments])
        return self.commands.run(label, *command).decode("utf-8")

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
        selected_module = None
        if self.application_closure is not None:
            from tools.go_application_dependencies import configure
            selected_module = configure(self.application_closure, generated)
        else:
            for name in ("go.mod", "go.sum"):
                module_input = read_file(source.parent / name)
                if module_input != read_file(self.sdk / "runtime-deps" / name):
                    raise ValueError("unreviewed-go-module-input")
                (generated / name).write_bytes(module_input)
        sources = snapshot(source)
        if not sources or self.application_closure is None and any(not name.endswith(".go") for name in sources):
            raise ValueError("Go application source must contain only captured .go files")
        replaced, source_locations, directories, application_source_paths = set(), {}, {}, set()
        for name, data in sources.items():
            if not name.endswith(".go") or name.endswith("_test.go"):
                continue
            text = data.decode("utf-8")
            package = re.search(r"(?m)^package\s+([a-zA-Z0-9_]+)\s*(?://[^\n]*)?$", text)
            if package is None:
                raise ValueError("Go entrypoint must implement its generated export package")
            relative = Path(name).parent.as_posix()
            if package[1].startswith("export_"):
                destination = generated / package[1]
            elif self.application_closure is not None:
                destination = generated / "src" / relative
            else:
                raise ValueError("Go entrypoint must implement its generated export package")
            if relative in directories and directories[relative] != destination:
                raise ValueError("selected-Go-source-directory-has-colliding-packages")
            directories[relative] = destination
        for name, data in sources.items():
            relative = Path(name).parent.as_posix()
            destination = directories.get(relative)
            if destination is None:
                parents = [key for key in directories if relative == key or relative.startswith(key + "/") or key == "."]
                if not parents:
                    if self.application_closure is None:
                        raise ValueError("Go application source must contain only captured .go files")
                    destination = generated / "src" / relative
                else:
                    parent = max(parents, key=len)
                    suffix = Path(relative).relative_to(parent)
                    destination = directories[parent] / suffix
            destination.mkdir(parents=True, exist_ok=True)
            stub = destination / "wit_bindings.go"
            if destination.parent == generated and destination.name.startswith("export_") and destination.name not in replaced:
                if not stub.is_file() or 'panic("not implemented")' not in stub.read_text():
                    raise ValueError("Go export stub does not match the authoritative WIT")
                # This is a generated stub in this fresh compiler-owned output,
                # never a user source or shared module cache.
                stub.unlink()
                replaced.add(destination.name)
            target = destination / Path(name).name
            if target.exists():
                raise ValueError("duplicate-or-generated-Go-application-filename")
            target.write_bytes(data)
            application_source_paths.add(target)
            if self.source_root is not None:
                source_locations[str(target)] = str(self.source_root / name)
                source_locations[target.relative_to(generated).as_posix()] = str(self.source_root / name)
                source_locations["./" + target.relative_to(generated).as_posix()] = str(self.source_root / name)
        if source_locations:
            write_json(self.commands.output / "diagnostic-files.json", source_locations)
        if any('panic("not implemented")' in path.read_text() for path in generated.glob("export_*/*.go")):
            raise ValueError("unimplemented-Go-WIT-export")
        binding_before = {path: path.read_bytes() for path in generated.glob("*/wit_bindings.go")}
        install(self.sdk, generated)
        transforms = []
        for path, before in sorted(binding_before.items()):
            after = path.read_bytes()
            if after != before:
                transforms.append({"name": "go-sdk-resource-owner/" + path.parent.name,
                    "upstreamDigest": digest(before), "adaptedDigest": digest(after), "profile": self.pins["profile"]})
        if selected_module is not None and selected_module["module"] != "wit_component":
            # Only generated SDK/WIT imports are rewritten. Application and
            # transitive source retains ordinary Go module semantics.
            for path in sorted(generated.rglob("*.go")):
                if path in application_source_paths or path.is_relative_to(generated / "dependencies"):
                    continue
                before = path.read_bytes()
                after = before.replace(b'"wit_component/', b'"' + selected_module["module"].encode() + b'/')
                if after != before:
                    path.write_bytes(after)
                    transforms.append({"path": path.relative_to(generated).as_posix(),
                        "upstreamDigest": digest(before), "adaptedDigest": digest(after), "profile": self.pins["profile"]})
        previous = self.commands.root
        self.commands.root = generated
        try:
            self.run("locked-module-download", "go", "mod", "download", "all")
            expected_sums = read_file(source.parent / "go.sum") if self.application_closure else read_file(self.sdk / "runtime-deps/go.sum")
            if (generated / "go.sum").read_bytes() != expected_sums:
                raise ValueError("unreviewed-go-dependency-checksum")
            self.run("vendor-locked-module", "go", "mod", "vendor")
            overlay_path = overlay(self.goroot, output / "runtime-overlay",
                                   generated / "vendor/go.bytecodealliance.org/pkg", sdk=self.sdk)
            self.commands.environment["GOFLAGS"] = "-mod=vendor -overlay=" + str(overlay_path)
            if selected_module is not None:
                if selected_module["tags"]:
                    self.commands.environment["GOFLAGS"] += " -tags=" + ",".join(selected_module["tags"])
                from tools.go_application_dependencies import json_stream, native_assembly
                packages = json_stream(self.run("selected-go-packages", "go", "list", "-deps", "-json", "./...").encode())
                selected_packages = []
                for package in packages:
                    selected_assembly = []
                    for name in package.get("SFiles", []):
                        path = Path(package["Dir"]) / name
                        if not package.get("Standard") and native_assembly(read_file(path)):
                            selected_assembly.append(name)
                    if (selected_assembly or package.get("SysoFiles") or package.get("CgoFiles")) and not package.get("Standard"):
                        raise ValueError("unsupported-native-operation-in-selected-Go-package:" + package["ImportPath"])
                    selected_packages.append({"importPath": package["ImportPath"], "standard": bool(package.get("Standard")),
                        "imports": package.get("Imports", []), "goFiles": package.get("GoFiles", []),
                        "embedFiles": package.get("EmbedFiles", []), "embedPatterns": package.get("EmbedPatterns", []),
                        "module": {key: (package.get("Module") or {}).get(key) for key in ("Path", "Version", "Sum")}})
                replacements = json.loads(overlay_path.read_bytes())["Replace"]
                for upstream, adapted in sorted(replacements.items()):
                    transforms.append({"name": "go-runtime-overlay/" + Path(adapted).name,
                        "upstreamDigest": digest(read_file(Path(upstream))), "adaptedDigest": digest(read_file(Path(adapted))),
                        "profile": self.pins["profile"]})
                write_json(self.commands.output / "go-module-build-inputs.json", {"formatVersion": 1, **selected_module,
                    "packages": selected_packages, "automaticTransformations": transforms, "initialization": "fresh-component-runtime"})
                self.isolation.protect_inputs(generated, overlay_path.parent)
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
        if self.isolation is not None:
            self.isolation.check_unchanged()
