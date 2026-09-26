"""Pinned maintained TypeScript/Jco/ComponentizeJS, without ambient guest WASI."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, write_json
from tools.phase3_resource_identity import inventory as tree_identity
from tools.typescript_guest.probe import semantic, projection


def import_identities(graph: dict, selected: str) -> list[str]:
    def identity(package, name):
        base, separator, version = graph["packages"][package]["name"].rpartition("@")
        if not separator:
            raise ValueError("TypeScript contracts require explicit package versions")
        return base + "/" + name + "@" + version
    worlds = [world for world in graph["worlds"]
              if identity(world["package"], world["name"]) == selected]
    if len(worlds) != 1:
        raise ValueError("exact selected WIT world required")
    imports = []
    for name, item in worlds[0].get("imports", {}).items():
        if set(item) != {"interface"} or not name.startswith("interface-"):
            raise ValueError("unsupported named or freestanding WIT import; use a versioned interface")
        interface = graph["interfaces"][item["interface"]["id"]]
        imports.append(identity(interface["package"], interface["name"]))
    return sorted(imports)


class Compiler:
    def __init__(self, tools: Path, commands, expected: dict[str, bytes]):
        self.tools, self.commands = tools.resolve(), commands
        self.node = Path(shutil.which("node", path=commands.environment["PATH"]) or "missing-node")
        self.wasm = Path(shutil.which("wasm-tools", path=commands.environment["PATH"]) or "missing-wasm-tools")
        if commands.run("node-version", self.node, "--version").strip() != b"v24.19.0":
            raise ValueError("unreviewed Node compiler host")
        if commands.run("wasm-tools-version", self.wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
            raise ValueError("unreviewed component validator")
        modules = self.tools / "node_modules"
        self.jco = modules / "@bytecodealliance/jco/dist/jco.js"
        self.tsc = modules / "typescript/bin/tsc"
        self.compiler = modules / "@bytecodealliance/componentize-js/src/componentize.js"
        self.esbuild = modules / "esbuild/lib/main.js"
        package = json.loads(expected["package.json"])
        for name, version in package["dependencies"].items():
            actual = json.loads(read_file(modules / name / "package.json"))
            if actual["version"] != version:
                raise ValueError("compiler dependency pin mismatch:" + name)
        for name, data in expected.items():
            if read_file(self.tools / name) != data:
                raise ValueError("compiler lock differs from captured project")
        commands.run("prepare-compiler-adapter", self.node, ROOT / "tools/typescript_guest/componentize.mjs", self.compiler)
        self.before = self.identity()

    def identity(self):
        # npm's .bin links are launch conveniences, never compiler inputs: use
        # exact JS entrypoints above. All actual package content is hashed.
        rows = []
        from tools.build_observation import file_identity
        total = 0
        for path in sorted((self.tools / "node_modules").rglob("*")):
            if ".bin" in path.relative_to(self.tools).parts:
                continue
            if path.is_symlink():
                raise ValueError("compiler dependency symlink")
            if path.is_dir():
                continue
            row = (file_identity(path, "compiler-file") if path.stat().st_size else
                   {"digest": digest(read_file(path)), "size": 0})
            total += row["size"]
            rows.append({"path": path.relative_to(self.tools).as_posix(), "digest": row["digest"], "size": row["size"]})
            if len(rows) > 32768 or total > 1024 * 1024 * 1024:
                raise ValueError("compiler dependency closure limit")
        return {"files": rows, "bytes": total}

    def compile(self, work: Path, world: str, output: Path):
        output.mkdir()
        command, wasm = self.commands, self.wasm
        source = work / "wit"
        canonical = command.run("canonical-wit", wasm, "component", "wit", source, "--no-docs").decode()
        graph = semantic(json.loads(command.run("authoritative-types", wasm, "component", "wit", source, "--json")))
        projected = output / "stackful.wit"
        projected.write_text(re.sub(r"\basync\s+func\b", "func", canonical), encoding="utf-8")
        actual = semantic(json.loads(command.run("projected-types", wasm, "component", "wit", projected, "--json")))
        if actual != projection(graph):
            raise ValueError("stackful projection changed the authoritative type graph")
        generated = work / "generated"
        command.run("generate-types", self.node, self.jco, "types", projected, "--world-name", world, "--name", "capsule", "--out-dir", generated)
        second = output / "generated-check"
        command.run("regenerate-types", self.node, self.jco, "types", projected, "--world-name", world, "--name", "capsule", "--out-dir", second)
        first_identity = tree_identity(generated)
        if first_identity != tree_identity(second):
            raise ValueError("generated binding drift between identical inputs")
        paths = {}
        for path in sorted(generated.rglob("*.d.ts")):
            match = re.search(r"@module Interface ([^ ]+)", path.read_text())
            if match:
                paths[match[1]] = ["./" + path.relative_to(work).as_posix()]
        imports = import_identities(graph, world)
        missing = [name for name in imports if name not in paths]
        if missing:
            raise ValueError("unsupported or colliding generated WIT import identities: " + ", ".join(missing))
        # Compiler-generated wrappers use stackful calls: asynchronous host WIT
        # still suspends in Wasmtime, never a hidden JavaScript event loop.
        config = {"compilerOptions": {"target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler",
                  "strict": True, "noEmit": True, "lib": ["ES2022"], "types": [], "paths": paths},
                  "include": ["src/**/*.ts", "generated/**/*.d.ts"]}
        write_json(work / "tsconfig.json", config)
        command.run("typecheck", self.node, self.tsc, "--project", work / "tsconfig.json")
        allowed = output / "imports.json"
        write_json(allowed, imports)
        bundle = output / "application.mjs"
        command.run("bundle", self.node, ROOT / "tools/typescript_guest/bundle.mjs", self.esbuild,
                    work, work / "src/main.ts", bundle, allowed)
        command.run("componentize", self.node, ROOT / "tools/typescript_guest/componentize.mjs", self.compiler,
                    projected, bundle, output, world)
        bare, embedded, component = (output / name for name in ("bare.wasm", "embedded.wasm", "component.wasm"))
        command.run("strip-projection", wasm, "strip", "--delete", "^component-type", output / "core.wasm", "-o", bare)
        command.run("restore-authoritative-contract", wasm, "component", "embed", source, bare, "--world", world, "-o", embedded)
        command.run("compose", wasm, "component", "new", embedded, "-o", component)
        command.run("validate", wasm, "validate", "--features", "all", component)
        surface = command.run("surface", wasm, "component", "wit", component).decode()
        if "import wasi:" in surface:
            raise ValueError("ambient WASI import survived compilation")
        (output / "component.wit").write_text(surface, encoding="utf-8")
        return component, first_identity

    def check_unchanged(self):
        if self.identity() != self.before:
            raise ValueError("installed compiler inputs changed during build")
