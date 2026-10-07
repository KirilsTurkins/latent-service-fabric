"""Pinned maintained TypeScript/Jco/ComponentizeJS, without ambient guest WASI."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil
from tools.rust_capsule_project import ROOT, checked_path, digest, inventory, read_file, write_json
from tools.phase3_resource_identity import inventory as tree_identity
from tools.typescript_guest.probe import semantic, projection


def declaration_aliases(source: str) -> str:
    """Repair the exact pinned Jco reserved-word .d.ts declaration gap.

    Jco 1.34.0 emits an exported alias for WIT `delete`, followed by a bare
    function declaration. TypeScript 7 requires `declare` in a .d.ts file.
    Names, parameters, return type and wire metadata remain generated inputs.
    The finite exact match makes any different generator shape fail closed.
    """
    if "export { _delete as delete };" not in source:
        return source
    expected = ("export { _delete as delete };\n"
                "function _delete(transaction: Transaction, key: Uint8Array): void;")
    if (source.count(expected) != 1 or
            "/** @module Interface latent:state/key-value@0.2.0 **/" not in source):
        raise ValueError("unreviewed Jco reserved declaration alias shape")
    return source.replace(expected, expected.replace("\nfunction ", "\ndeclare function "))


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
    def __init__(self, tools: Path, commands, expected: dict[str, bytes], *, isolated_workspace: Path | None = None,
                 runtime_profile: str = 'spidermonkey-public-sync-v1', engine: Path | None = None,
                 engine_receipt: Path | None = None):
        from tools.typescript_guest.runtime_profile import NATIVE_PROFILES, SYNC_PROFILE, selection, validate_engine
        from tools.typescript_guest.activation_engine import engine_input_paths
        selection(runtime_profile)
        self.runtime_profile = runtime_profile
        self.engine, self.engine_original, self.engine_before = None, None, None
        self.engine_metadata = None
        self.runtime_observation = None
        if runtime_profile == SYNC_PROFILE and (engine is not None or engine_receipt is not None):
            raise ValueError('native engine input requires an explicit TypeScript runtime selection')
        if runtime_profile in NATIVE_PROFILES:
            if engine is None or engine_receipt is None:
                raise ValueError('selected TypeScript Promise candidate requires actual source-bound engine inputs')
            engine, engine_receipt = map(checked_path, (engine, engine_receipt))
            core, envelope = read_file(engine, 64*1024*1024), read_file(engine_receipt, 65536)
            sdk = {name: read_file(ROOT/name) for name in engine_input_paths(runtime_profile)}
            self.engine_metadata = validate_engine(json.loads(envelope), core, sdk,
                read_file(ROOT/'wit/platform/activation-runtime/package.wit'), profile=runtime_profile)
            self.engine_original = (engine, engine_receipt)
            self.engine_before = (core, envelope)
            self.engine = engine
            if isolated_workspace is not None:
                prefix = isolated_workspace/'selected-runtime-engine'
                prefix.mkdir()
                self.engine = prefix/'engine.wasm'
                self.engine.write_bytes(core)
                (prefix/'engine-input.json').write_bytes(envelope)
        self.tools, self.commands = tools.resolve(), commands
        self.isolation = None
        self.recipe = ROOT / "tools/typescript_guest"
        self.original_tools, self.original_before = None, None
        self.expected = expected
        self.node = Path(shutil.which("node", path=commands.environment["PATH"]) or "missing-node")
        self.wasm = Path(shutil.which("wasm-tools", path=commands.environment["PATH"]) or "missing-wasm-tools")
        if commands.run("node-version", self.node, "--version").strip() != b"v24.19.0":
            raise ValueError("unreviewed Node compiler host")
        if commands.run("wasm-tools-version", self.wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
            raise ValueError("unreviewed component validator")
        if isolated_workspace is not None:
            self.original_tools, self.original_before = self.tools, self.identity()
            staged = isolated_workspace / "compiler"
            staged.mkdir()
            for name in expected:
                (staged / name).write_bytes(read_file(self.tools / name))
            for row in self.original_before["files"]:
                source, destination = self.tools / row["path"], staged / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                destination.chmod(source.stat().st_mode & 0o777)
            self.tools = staged
            self.recipe = isolated_workspace / "compiler-recipe"
            self.recipe.mkdir()
            for name in ("bundle.mjs", "componentize.mjs", "signed64.mjs", "resources.mjs"):
                (self.recipe / name).write_bytes(read_file(ROOT / "tools/typescript_guest" / name))
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
        commands.run("prepare-compiler-adapter", self.node, self.recipe / "componentize.mjs", self.compiler)
        self.before = self.identity()
        if isolated_workspace is not None:
            from tools.captured_compiler_isolation import Isolation
            selected_tools = {"node": self.node, "wasm-tools": self.wasm}
            # Native helpers are SDK compiler inputs. Application .node files
            # are never loaded into this host Node process.
            for path in sorted((self.tools / "node_modules").rglob("*")):
                if path.is_file():
                    with path.open("rb") as source:
                        if source.read(4) == b"\x7fELF":
                            selected_tools["sdk-native/" + path.relative_to(self.tools).as_posix()] = path
            inputs = {"typescript-compiler": self.tools}
            if self.engine is not None:
                inputs['typescript-runtime-engine'] = self.engine.parent
            self.isolation = Isolation(isolated_workspace, selected_tools, inputs)
            self.isolation.protect_inputs(self.recipe)

    def run(self, stage, tool, *arguments):
        if self.isolation is None:
            return self.commands.run(stage, tool, *arguments)
        return self.commands.run(stage, *self.isolation.wrap(Path(tool), [str(value) for value in arguments],
                                                           self.commands.root, self.commands.environment))

    def identity(self, tools=None):
        # npm's .bin links are launch conveniences, never compiler inputs: use
        # exact JS entrypoints above. All actual package content is hashed.
        rows = []
        from tools.build_observation import file_identity
        total = 0
        tools = tools or self.tools
        for path in sorted((tools / "node_modules").rglob("*")):
            if ".bin" in path.relative_to(tools).parts:
                continue
            if path.is_symlink():
                raise ValueError("compiler dependency symlink")
            if path.is_dir():
                continue
            row = (file_identity(path, "compiler-file") if path.stat().st_size else
                   {"digest": digest(read_file(path)), "size": 0})
            total += row["size"]
            rows.append({"path": path.relative_to(tools).as_posix(), "digest": row["digest"], "size": row["size"]})
            if len(rows) > 32768 or total > 1024 * 1024 * 1024:
                raise ValueError("compiler dependency closure limit")
        return {"files": rows, "bytes": total}

    def compile(self, work: Path, world: str, output: Path, *, application_modules: dict | None = None):
        from tools.typescript_guest import runtime_profile as runtime
        output.mkdir()
        command, wasm = self, self.wasm
        source = work / "wit"
        canonical = command.run("canonical-wit", wasm, "component", "wit", source, "--no-docs").decode()
        graph = semantic(json.loads(command.run("authoritative-types", wasm, "component", "wit", source, "--json")))
        application_graph, application_world = graph, world
        application_canonical = canonical
        if self.runtime_profile in runtime.NATIVE_PROFILES:
            runtime.check_application_bindings(application_graph, application_world, profile=self.runtime_profile)
            from tools.typescript_guest.activation_engine import NATIVE_SOURCES
            from tools.typescript_guest.clock_engine import CLOCK_NATIVE_SOURCES
            selected_native = NATIVE_SOURCES + (CLOCK_NATIVE_SOURCES if self.runtime_profile == runtime.CLOCK_PROFILE else ())
            declarations = ('runtime-globals.d.ts',) + (('clock-globals.d.ts',) if self.runtime_profile == runtime.CLOCK_PROFILE else ())
            for name in (*selected_native, *declarations):
                path = 'sdk/typescript-guest/activation/'+name
                if read_file(work/'vendor/lsf'/path) != read_file(ROOT/path):
                    raise ValueError('captured TypeScript native runtime differs from the selected engine')
            # The actual maintained parser proves every original public type and
            # import survives. SDK runtime imports add no application authority.
            captured = work/'vendor/lsf/wit/platform/activation-runtime/package.wit'
            runtime_wit = read_file(captured)
            if runtime_wit != read_file(ROOT/'wit/platform/activation-runtime/package.wit'):
                raise ValueError('captured TypeScript activation interface differs from the selected engine')
            selected = output/'selected-wit'
            selected.mkdir()
            if self.runtime_profile == runtime.CLOCK_PROFILE:
                from tools.typescript_guest.clock_engine import derive_clock_world
                clock_wit = read_file(work/'vendor/lsf/wit/platform/clock/package.wit')
                if clock_wit != read_file(ROOT/'wit/platform/clock/package.wit'):
                    raise ValueError('captured TypeScript clock interface differs from the selected engine')
                files = derive_clock_world(canonical.encode(), graph, world, runtime_wit, clock_wit)
            else:
                files = runtime.derive_world(canonical.encode(), graph, world, runtime_wit)
            for name, raw in files.items():
                target = selected/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            activation = output/'activation-wit'
            (activation/'deps/activation').mkdir(parents=True)
            (activation/'deps/activation/package.wit').write_bytes(runtime_wit)
            (activation/'world.wit').write_text('package lsf:typescript-abi@1.0.0;\nworld abi { import latent:runtime/activation@0.1.0; }\n', encoding='utf-8')
            actual = semantic(json.loads(command.run('selected-runtime-types', wasm, 'component', 'wit', selected, '--json')))
            abi = semantic(json.loads(command.run('selected-activation-types', wasm, 'component', 'wit', activation, '--json')))
            if self.runtime_profile == runtime.CLOCK_PROFILE:
                from tools.typescript_guest.clock_engine import check_clock_world
                clocks = output/'clock-wit'
                (clocks/'deps/clock').mkdir(parents=True)
                (clocks/'deps/clock/package.wit').write_bytes(clock_wit)
                (clocks/'world.wit').write_text('package lsf:clock-abi@1.0.0;\nworld abi { import latent:clock/monotonic@0.1.0; import latent:clock/wall@0.1.0; }\n',encoding='utf-8')
                clock_graph = semantic(json.loads(command.run('selected-clock-types', wasm, 'component', 'wit', clocks, '--json')))
                self.runtime_observation = check_clock_world(graph, actual, abi, clock_graph, world)
            else:
                self.runtime_observation = runtime.check_derived_world(graph, actual, abi, world)
            self.runtime_observation['engineInput'] = self.engine_metadata
            write_json(output/'typescript-runtime-selection.json', self.runtime_observation)
            write_json(output/'selected-wit-inputs.json', {'world': runtime.SELECTED_WORLD, 'sources': [
                {'path': 'wit/'+name, 'content': raw.decode('utf-8')} for name, raw in sorted(files.items())]})
            source, graph, world = selected, actual, runtime.SELECTED_WORLD
            canonical = command.run('selected-runtime-wit', wasm, 'component', 'wit', selected, '--no-docs').decode()
        # Only application bindings are projected. The exact native activation
        # async-lower imports remain in the selected engine metadata and cannot
        # be replaced by synchronous generated JS wrappers during world merge.
        binding_canonical, binding_graph, binding_world = (
            (application_canonical, application_graph, application_world)
            if self.runtime_profile in runtime.NATIVE_PROFILES else (canonical, graph, world))
        projected = output / "stackful.wit"
        projected.write_text(re.sub(r"\basync\s+func\b", "func", binding_canonical), encoding="utf-8")
        actual = semantic(json.loads(command.run("projected-types", wasm, "component", "wit", projected, "--json")))
        if actual != projection(binding_graph):
            raise ValueError("stackful projection changed the authoritative type graph")
        generated = work / "generated"
        # The selected engine genuinely returns ordinary Promises. Generate
        # source declarations from the original async contract; only the
        # compiler's core binding ABI uses the established projection.
        declaration_wit = work / 'wit' if self.runtime_profile in runtime.NATIVE_PROFILES else projected
        command.run("generate-types", self.node, self.jco, "types", declaration_wit, "--world-name", binding_world, "--name", "capsule", "--out-dir", generated)
        second = output / "generated-check"
        command.run("regenerate-types", self.node, self.jco, "types", declaration_wit, "--world-name", binding_world, "--name", "capsule", "--out-dir", second)
        # Preserve raw generated declarations separately from the reviewed
        # compiler spelling projection and compare both independent outputs.
        write_json(output / "raw-generated-bindings.json", tree_identity(generated))
        for directory in (generated, second):
            for path in sorted(directory.rglob("*.d.ts")):
                original = path.read_text(encoding="utf-8")
                adapted = declaration_aliases(original)
                if adapted != original:
                    path.write_text(adapted, encoding="utf-8")
            if self.runtime_profile in runtime.NATIVE_PROFILES:
                (directory/'activation-runtime-globals.d.ts').write_bytes(
                    read_file(ROOT/'sdk/typescript-guest/activation/runtime-globals.d.ts'))
                if self.runtime_profile == runtime.CLOCK_PROFILE:
                    (directory/'clock-runtime-globals.d.ts').write_bytes(
                        read_file(ROOT/'sdk/typescript-guest/activation/clock-globals.d.ts'))
        first_identity = tree_identity(generated)
        if first_identity != tree_identity(second):
            raise ValueError("generated binding drift between identical inputs")
        paths = {}
        for path in sorted(generated.rglob("*.d.ts")):
            match = re.search(r"@module Interface ([^ ]+)", path.read_text())
            if match:
                paths[match[1]] = ["./" + path.relative_to(work).as_posix()]
        imports = import_identities(binding_graph, binding_world)
        missing = [name for name in imports if name not in paths]
        if missing:
            raise ValueError("unsupported or colliding generated WIT import identities: " + ", ".join(missing))
        # Compiler-generated wrappers use stackful calls: asynchronous host WIT
        # still suspends in Wasmtime, never a hidden JavaScript event loop.
        config = {"compilerOptions": {"target": "ES2022", "module": "ESNext", "moduleResolution": "Bundler",
                  "strict": True, "noEmit": True, "lib": ["ES2022"], "types": [], "paths": paths},
                  "include": ["src/**/*.ts", "generated/**/*.d.ts"]}
        if application_modules is not None:
            config["compilerOptions"]["paths"]["*"] = ["./" + application_modules["moduleRoot"] + "/*"]
            config["compilerOptions"]["customConditions"] = application_modules["conditions"]
        write_json(work / "tsconfig.json", config)
        command.run("typecheck", self.node, self.tsc, "--project", work / "tsconfig.json")
        allowed = output / "imports.json"
        write_json(allowed, imports)
        bundle = output / "application.mjs"
        bundle_configuration = output / "bundle-configuration.json"
        write_json(bundle_configuration, application_modules or {})
        if self.isolation is not None:
            self.isolation.protect_inputs(work)
        command.run("bundle", self.node, self.recipe / "bundle.mjs", self.esbuild,
                    work, work / "src/main.ts", bundle, allowed, bundle_configuration,
                    self.tools / "node_modules/acorn/dist/acorn.mjs")
        arguments = [self.compiler, projected, bundle, output, binding_world]
        if self.engine is not None:
            arguments.extend((self.engine, output/'typescript-runtime-selection.json'))
        command.run("componentize", self.node, self.recipe / "componentize.mjs", *arguments)
        bare, embedded, component = (output / name for name in ("bare.wasm", "embedded.wasm", "component.wasm"))
        command.run("strip-projection", wasm, "strip", "--delete", "^component-type", output / "core.wasm", "-o", bare)
        command.run("restore-authoritative-contract", wasm, "component", "embed", source, bare, "--world", world, "-o", embedded)
        command.run("compose", wasm, "component", "new", embedded, "-o", component)
        command.run("validate", wasm, "validate", "--features", "all", component)
        surface = command.run("surface", wasm, "component", "wit", component).decode()
        if "import wasi:" in surface:
            raise ValueError("ambient WASI import survived compilation")
        (output / "component.wit").write_text(surface, encoding="utf-8")
        if self.runtime_profile in runtime.NATIVE_PROFILES:
            # Bind an independently decoded final component, not just generated
            # metadata. The existing projection path remains the sync contract.
            final = semantic(json.loads(command.run('final-runtime-types', wasm, 'component', 'wit', component, '--json')))
            if runtime.public_component_graph(final) != runtime.public_graph(graph, world):
                raise ValueError('compiled TypeScript selected-world type graph changed')
        return component, first_identity

    def check_unchanged(self):
        if self.engine_original is not None:
            if tuple(read_file(path, 64*1024*1024 if index == 0 else 65536)
                     for index, path in enumerate(self.engine_original)) != self.engine_before:
                raise ValueError('original selected TypeScript engine inputs changed')
            if read_file(self.engine, 64*1024*1024) != self.engine_before[0]:
                raise ValueError('staged selected TypeScript engine changed')
        if self.identity() != self.before:
            raise ValueError("installed compiler inputs changed during build")
        if self.original_tools is not None and self.identity(self.original_tools) != self.original_before:
            raise ValueError("original compiler installation changed during isolated build")
        if self.original_tools is not None and any(read_file(self.original_tools / name) != data for name, data in self.expected.items()):
            raise ValueError("original compiler declarations changed during isolated build")
        if self.isolation is not None:
            self.isolation.check_unchanged()
