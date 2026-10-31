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
from tools.c_guest import closed_filesystem, standard_facilities
from tools.c_guest.language import DEFAULT as C_STANDARD, selected_standard

ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "sdk/c-guest"
CAPABILITIES = ("blob", "callee", "events", "http", "metrics", "random", "secrets", "service", "streaming")


class Compiler:
    """One caller-owned finite build. No shell, guest execution or download."""

    def __init__(self, temporary: Path, timeout: int = 300, *, sdk: Path = SDK,
                 platform: Path | None = ROOT / "wit/platform", config: dict | None = None,
                 commands=None, installed: dict[str, Path] | None = None,
                 threading_tool: Path | None = None):
        if not 1 <= timeout <= 900:
            raise ValueError("C build deadline must be between 1 and 900 seconds")
        temporary.mkdir(parents=True, exist_ok=True)
        self.environment = build_environment(temporary)
        caches = {"ZIG_GLOBAL_CACHE_DIR": str(temporary / "zig-global"), "ZIG_LOCAL_CACHE_DIR": str(temporary / "zig-local")}
        self.environment.update(caches)
        if commands is not None:
            commands.environment.update(caches)
        self.deadline = time.monotonic() + timeout
        self.sdk, self.platform, self.commands = sdk, platform, commands
        self.isolation = None
        self.paths: dict[str, Path] = {}
        self.materials: dict[str, dict] = {}
        self.compiler_edges = None
        self.compiler_edge_sources = {}
        config = config or tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        versions = {"zig": config["sdk"]["zig"],
                    "wit-bindgen": config["contracts"]["wit-bindgen-cli"],
                    "wasm-tools": config["contracts"]["wasm-tools"]}
        if installed is not None and set(installed) != set(versions):
            raise ValueError("explicit C compiler selection must name exactly the required tools")
        for tool, version in versions.items():
            located = shutil.which(tool, path=self.environment.get("PATH")) if installed is None else installed[tool]
            if not located:
                raise ValueError(f"missing pinned C guest tool: {tool} {version}")
            path = Path(located).resolve(strict=True)
            if installed is not None and (not Path(located).is_absolute() or Path(located).is_symlink()):
                raise ValueError("explicit C compiler paths must be absolute ordinary files")
            self.paths[tool] = path
            self.materials[tool] = file_identity(path, tool)
            actual = self.run(tool, "version" if tool == "zig" else "--version").strip()
            if version not in actual.split():
                raise ValueError(f"{tool}: expected {version}, found {actual}")
        self.closed_filesystem = closed_filesystem.prepare(self.paths['zig'], self.sdk)
        self.materials.update(self.closed_filesystem.materials)
        self.threading_inputs = {}
        self.threading_clock_inputs = {}
        if threading_tool is not None:
            from tools.c_guest import threading
            if not threading_tool.is_absolute() or threading_tool.is_symlink() or not threading_tool.is_file():
                raise ValueError('c-threading-transformer-requires-owned-tool')
            self.paths['c-threading-transformer'] = threading_tool.resolve(strict=True)
            self.materials['c-threading-transformer'] = file_identity(threading_tool, 'c-threading-transformer')
            self.threading_inputs = threading.libc_inputs(self.paths['zig'])
            self.materials.update({name: file_identity(path, threading.libc_material_name(name), 32768)
                                   for name, path in self.threading_inputs.items()})

    def run(self, tool: str, *arguments: str) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("C build deadline exceeded")
        if self.isolation is not None:
            cwd = self.commands.root if self.commands is not None else self.isolation.workspace
            environment = self.commands.environment if self.commands is not None else self.environment
            command = self.isolation.wrap(self.paths[tool], list(map(str, arguments)), cwd, environment)
            if self.commands is not None:
                return self.commands.run(tool, command[0], *command[1:]).decode("utf-8")
            return run_bounded(command, cwd, environment, timeout_seconds=min(remaining, 300),
                               max_output_bytes=4 * 1024 * 1024).stdout.decode("utf-8")
        if self.commands is not None:
            return self.commands.run(tool, self.paths[tool], *arguments).decode("utf-8")
        result = run_bounded((str(self.paths[tool]), *map(str, arguments)), ROOT,
                             self.environment, timeout_seconds=min(remaining, 300),
                             max_output_bytes=4 * 1024 * 1024)
        return result.stdout.decode("utf-8")

    def select_threading_clock_inputs(self) -> None:
        from tools.c_guest import threading
        inputs = threading.clock_libc_inputs(self.paths['zig'])
        identities = {name: file_identity(path, threading.clock_libc_material_name(name), 32768)
                      for name, path in inputs.items()}
        if self.threading_clock_inputs:
            if inputs != self.threading_clock_inputs or any(
                    self.materials[name] != identity for name, identity in identities.items()):
                raise ValueError('c-threading-libc-clock-input-changed')
        else:
            self.threading_clock_inputs = inputs
            self.materials.update(identities)

    def check_unchanged(self) -> None:
        self.closed_filesystem.check_unchanged()
        if self.threading_inputs:
            from tools.c_guest import threading
            if threading.libc_inputs(self.paths['zig']) != self.threading_inputs:
                raise ValueError('c-threading-libc-input-changed')
        for name, path in self.threading_inputs.items():
            if file_identity(path, threading.libc_material_name(name), 32768) != self.materials[name]:
                raise ValueError('c-threading-libc-input-changed')
        if getattr(self, 'threading_clock_inputs', None):
            from tools.c_guest import threading
            if threading.clock_libc_inputs(self.paths['zig']) != self.threading_clock_inputs:
                raise ValueError('c-threading-libc-clock-input-changed')
            for name, path in self.threading_clock_inputs.items():
                if file_identity(path, threading.clock_libc_material_name(name), 32768) != self.materials[name]:
                    raise ValueError('c-threading-libc-clock-input-changed')
        for name, path in self.paths.items():
            if file_identity(path, name) != self.materials[name]:
                raise ValueError("C compiler tool changed during build")
        if self.isolation is not None:
            self.isolation.check_unchanged()

    def enable_captured_isolation(self, workspace: Path) -> dict:
        from tools.captured_compiler_isolation import Isolation
        deadline = getattr(self.commands, '_parent_deadline', None)
        options = {} if deadline is None else {'_deadline': deadline}
        self.isolation = Isolation(workspace, self.paths, {"zig-compiler-and-sysroot": self.paths["zig"].parent}, **options)
        if self.commands is not None:
            self.isolation.protect_inputs(self.commands.root)
        return self.isolation.receipt

    def validate_static_libraries(self, libraries: tuple[Path, ...], destination: Path) -> None:
        """Validate every core object, including members the linker will not extract."""
        from tools.application_dependency_store import read_bytes
        from tools.c_application_dependencies import archive_members
        if len(libraries) > 32:
            raise ValueError("C static archive count exceeds 32")
        receipts = []
        for ordinal, library in enumerate(libraries):
            owned = destination / f"archive-{ordinal:04}"
            owned.mkdir(mode=0o700)
            def validate_member(name, payload):
                path = owned / name
                with path.open("xb") as output:
                    output.write(payload)
                self.run("wasm-tools", "validate", "--features=-threads,-memory64", str(path))
            members = archive_members(read_bytes(library), validator=validate_member)
            receipts.append({"digest": digest(read_bytes(library)), "members": members,
                             "validator": self.materials["wasm-tools"], "threads": False, "memory64": False})
        if self.isolation is not None:
            self.isolation.receipt["staticArchiveValidation"] = receipts

    def compile_static_archive(self, sources: tuple[Path, ...], destination: Path, *,
                               include_directories: tuple[Path, ...] = (), defines: tuple[str, ...] = ()) -> tuple[Path, dict]:
        """The finite captured source recipe; this does not execute or qualify a guest."""
        from tools.c_application_dependencies import archive_members
        from tools.application_dependency_store import read_bytes
        from tools.rust_capsule_project import inventory, snapshot
        if self.isolation is None:
            raise ValueError("C static source recipe requires captured compiler isolation")
        if not 1 <= len(sources) <= 64 or len(include_directories) > 64 or len(defines) > 64:
            raise ValueError("C static source recipe exceeds maintained limits")
        if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 262144 for path in sources):
            raise ValueError("invalid or oversized C source")
        destination.mkdir(mode=0o700)
        options = ["cc", "-std=c11", "-target", "wasm32-wasi", "-O2", "-Wall", "-Wextra", "-Werror",
                   "-I", str(self.sdk / "include")]
        for directory in include_directories:
            options.extend(["-I", str(directory)])
        options.extend("-D" + value for value in defines)
        objects, observed = [], []
        for ordinal, source in enumerate(sources):
            target, depfile = destination / f"source-{ordinal:04}.o", destination / f"inputs-{ordinal:04}.d"
            self.run("zig", *options, "-M", "-MT", "lsf-inputs", "-MF", str(depfile), str(source))
            observed.extend(self.isolation.observe_inputs(depfile))
            self.run("zig", *options, "-c", str(source), "-o", str(target))
            self.run("wasm-tools", "validate", "--features=-threads,-memory64", str(target))
            objects.append(target)
        self.isolation.receipt["preprocessorInputs"] = sorted(
            {row["path"]: row for row in observed}.values(), key=lambda row: row["path"])
        archive = destination / "library.a"
        self.run("zig", "ar", "rcs", str(archive), *map(str, objects))
        profile = {"formatVersion": 1, "target": "wasm32-wasi", "compilerDigest": self.materials["zig"]["digest"],
            "compilerDistributionDigest": digest(json.dumps(self.isolation.receipt["distributions"],
                sort_keys=True, separators=(",", ":")).encode()),
            "runtimeDigest": digest(inventory(snapshot(self.sdk))), "checkpointProfile": "closed-synchronous-v1",
            "members": archive_members(read_bytes(archive))}
        self.check_unchanged()
        return archive, profile

    def compile(self, sources: list[Path], wit_source: Path, world: str,
                destination: Path, *, memory_bytes: int = 16 * 1024 * 1024,
                trap: bool = True, include_directories: tuple[Path, ...] = (),
                static_libraries: tuple[Path, ...] = (), defines: tuple[str, ...] = (),
                runtime_profile: str = standard_facilities.DEFAULT, language_standard: str = C_STANDARD,
                embed_directories: tuple[Path, ...] = (),
                dependency_sources: tuple[Path, ...] = (),
                threading_profile: str = 'single-threaded') -> tuple[Path, dict]:
        standard_facilities.selected_profile({'runtimeProfile': runtime_profile})
        selected_standard({'languageStandard': language_standard})
        threaded = threading_profile != 'single-threaded'
        if threaded:
            from tools.c_guest import threading
            threading.selected({'threadingProfile': threading_profile})
        if runtime_profile in standard_facilities.FETCH_PROFILES and not threaded:
            raise ValueError('c-libfetch-http-requires-cooperative-threading')
        if threaded and ('c-threading-transformer' not in self.paths or static_libraries):
            raise ValueError('c-threading-requires-transformer-and-no-static-archives')
        if embed_directories and (language_standard != 'c23' or len(embed_directories) > 64):
            raise ValueError('c-embed-directories-require-bounded-c23-selection')
        if not sources or len(sources) > 64:
            raise ValueError("C source count must be between 1 and 64")
        if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 262144 for path in sources):
            raise ValueError("invalid or oversized C source")
        if (not isinstance(dependency_sources, tuple) or len(set(dependency_sources)) != len(dependency_sources)
                or any(path not in sources or path.resolve().is_relative_to(self.sdk.resolve())
                       for path in dependency_sources)
                or (dependency_sources and self.isolation is None)):
            raise ValueError('C dependency sources require a distinct captured non-SDK source selection')
        if isinstance(memory_bytes, bool) or memory_bytes < 2 * 1024 * 1024 or memory_bytes > 64 * 1024 * 1024 or memory_bytes % 65536:
            raise ValueError("C memory ceiling must be page-aligned and between 2 and 64 MiB")
        generated, lock = generate(self.run, wit_source, world, destination, self.platform,
                                   sync_core_abi=threaded)
        public = None
        if threaded:
            graph = json.loads(self.run('wasm-tools', 'component', 'wit', '--json', str(destination / 'wit')))
            public = threading.public_export(graph)
            runtime = self.sdk / 'runtime'
            sources = [*sources, runtime / 'threads.c', runtime / 'tls-keys.c', runtime / 'template-copy.c']
            include_directories = (*include_directories, runtime)
            timed_clock = runtime_profile in {standard_facilities.PROFILE, standard_facilities.COMBINED_PROFILE,
                                               standard_facilities.FETCH_STANDARD_PROFILE}
            if timed_clock:
                self.select_threading_clock_inputs()
                defines = threading.linked_defines(defines, timed_clock=True)
            else:
                defines = threading.linked_defines(defines)
        defines = standard_facilities.compiler_defines(runtime_profile, defines)
        self.validate_static_libraries(static_libraries, destination)
        core, component = destination / "core.wasm", destination / "component.wasm"
        command = ["cc", "-std=" + language_standard, "-target", "wasm32-wasi", "-O2",
                   "-Wall", "-Wextra", "-Werror", "-mexec-model=reactor",
                   "-Wl,--no-entry", "-Wl,--export-memory", "-Wl,-z,stack-size=65536",
                   f"-Wl,--max-memory={memory_bytes}", "-I", str(generated),
                   "-I", str(self.sdk / "include"), *map(str, sources)]
        if runtime_profile in standard_facilities.FETCH_PROFILES:
            # Zig maps this to wasm-ld -s: omit debug/name metadata, not code.
            command.append('-Wl,--strip-debug')
        thread_flags = []
        if threaded:
            # The post-link template-copy body is deliberately opaque to its
            # callers; LTO could propagate its temporary refusal into them.
            thread_flags = ['-matomics', '-mbulk-memory', '-pthread', '-fno-lto']
            for family in ('wasm-wasi-musl', 'generic-musl'):
                thread_flags.extend(['-isystem', str(self.paths['zig'].parent / 'lib/libc/include' / family)])
            # One authenticated original-memory reservation: 4KiB guard,
            # 64KiB private root stack, then 64KiB canonical System stack.
            # Canonical realloc clears context slots and cannot borrow a
            # root/child frame suspended during host result lowering.
            command[command.index('-Wl,-z,stack-size=65536')] = '-Wl,-z,stack-size=135168'
            command.extend([*thread_flags, *('-Wl,--export=' + name for name in threading.EXPORTS)])
        for directory in include_directories:
            command.extend(["-I", str(directory)])
        for directory in embed_directories:
            command.append('--embed-dir=' + str(directory))
        command.extend("-D" + define for define in defines)
        command.extend(map(str, static_libraries))
        if trap:
            command.append(str(self.sdk / "src/trap.c"))
        command.extend([str(generated / "probe.c"), str(generated / "probe_component_type.o"),
                        "-o", str(core)])
        if self.isolation is not None:
            preprocessor = ["cc", "-std=" + language_standard, "-target", "wasm32-wasi", "-I", str(generated),
                            "-I", str(self.sdk / "include")]
            for directory in include_directories:
                preprocessor.extend(["-I", str(directory)])
            for directory in embed_directories:
                preprocessor.append('--embed-dir=' + str(directory))
            preprocessor.extend("-D" + define for define in defines)
            preprocessor.extend(thread_flags)
            selected_sources = [*sources, generated / "probe.c"]
            if trap:
                selected_sources.append(self.sdk / "src/trap.c")
            observed = []
            for index, source in enumerate(selected_sources):
                depfile = destination / f"inputs-{index:04}.d"
                self.run("zig", *preprocessor, "-M", "-MT", "lsf-inputs", "-MF", str(depfile), str(source))
                observed.extend(self.isolation.observe_inputs(depfile))
            self.isolation.receipt["preprocessorInputs"] = sorted(
                {row["path"]: row for row in observed}.values(), key=lambda row: row["path"])
        dependency_objects = []
        if dependency_sources:
            # Captured third-party source keeps visible warnings, without
            # imposing the SDK/application's warning-as-error policy on it.
            # Fresh objects use the same target, O2, headers and thread ABI;
            # this does not admit opaque archives or caller-provided flags.
            link_inputs = [*sources, *static_libraries, generated / 'probe.c', generated / 'probe_component_type.o']
            if trap:
                link_inputs.append(self.sdk / 'src/trap.c')
            options = self.translation_options(command, link_inputs)
            options.remove('-Werror')
            rows, replacements, total = [], {}, 0
            for ordinal, source in enumerate(dependency_sources):
                target = destination / f'dependency-{ordinal:04}.o'
                if target.exists() or target.is_symlink():
                    raise ValueError('C dependency object output must be fresh')
                self.run('zig', *options, '-c', str(source), '-o', str(target))
                identity = file_identity(target, target.name, 4 * 1024 * 1024)
                total += identity['size']
                if total > 4 * 1024 * 1024:
                    raise ValueError('C dependency object byte limit exceeded')
                rows.append({'source': file_identity(source, source.name, 262144), 'object': identity})
                replacements[str(source)] = str(target)
                dependency_objects.append(target)
            command = [replacements.get(value, value) for value in command]
            self.isolation.receipt['dependencyCompilation'] = {
                'warningPolicy': 'visible-warnings-without-werror', 'objects': rows}
        self.run("zig", *command)
        if runtime_profile in standard_facilities.FETCH_PROFILES and self.commands is not None:
            from tools.rust_capsule_project import read_file
            payload = read_file(core, 64 * 1024 * 1024)
            observation = {'formatVersion': 1, 'size': len(payload), 'digest': digest(payload),
                           'headerHex': payload[:8].hex(),
                           'originalEnvelopeBytes': 20 + len(public.encode('utf-8')) + len(payload),
                           'maximumEnvelopeBytes': 1024 * 1024,
                           'linkerFlags': ['-Wl,--strip-debug']}
            (self.commands.output / 'c-original-core.json').write_text(
                json.dumps(observation, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            (self.commands.output / 'c-original-core.wasm').write_bytes(payload)
        encoded_core = core
        if threaded:
            derived = destination / 'c-threading'
            self.run('c-threading-transformer', '--c-thread-derive-v1', str(core), public, str(derived))
            encoded_core = derived / 'derived.wasm'
        try:
            component_command = ["component", "new", str(encoded_core), "-o", str(component)]
            if runtime_profile in {standard_facilities.LOGGING_PROFILE, standard_facilities.COMBINED_PROFILE}:
                adapter = destination / "standard-stdio-adapter.wasm"
                self.run("wasm-tools", "parse", str(self.sdk / "src/standard-stdio.wat"), "-o", str(adapter))
                component_command.extend(["--adapt", "wasi_snapshot_preview1=" + str(adapter)])
            self.run("wasm-tools", *component_command)
        except BaseException:
            if self.commands is not None:
                try:
                    from tools.rust_capsule_project import read_file
                    payload = read_file(core, 64 * 1024 * 1024)
                    if payload.startswith(b'\0asm'):
                        (self.commands.output / 'core-componentization-failed.wasm').write_bytes(payload)
                except (OSError, ValueError):
                    pass
            raise
        if threaded:
            bound = destination / 'c-threading-component.wasm'
            self.run('c-threading-transformer', '--c-thread-bind-v1', str(core), str(component), public, str(bound))
            component = bound
            self.run('wasm-tools', 'validate', '--features', 'cm-threading,cm-async-stackful', str(component))
        else:
            self.run("wasm-tools", "validate", str(component))
        actual = self.run("wasm-tools", "component", "wit", str(component))
        if "wasi:" in actual or "wasi_snapshot_preview1" in actual:
            raise ValueError("ambient WASI is outside the C capsule authoring profile")
        if threaded:
            final = json.loads(self.run('wasm-tools', 'component', 'wit', '--json', str(component)))
            if threading.public_export(final) != public:
                raise ValueError('c-threading-final-public-contract-changed')
            lock['threadingProfile'] = threading_profile
            self.threading_result = {'originalCore': core,
                'derivedCore': destination / 'c-threading/derived.wasm',
                'unboundComponent': destination / 'component.wasm',
                'derivation': destination / 'c-threading/derivation.json',
                'publicExport': public, 'finalComponent': component}
        self.check_unchanged()
        if self.compiler_edges is not None:
            link_inputs = [*sources, *dependency_objects, *static_libraries,
                           generated / 'probe.c', generated / 'probe_component_type.o']
            if trap:
                link_inputs.append(self.sdk / 'src/trap.c')
            self.observe_compiler_edges(command, destination, link_inputs, dependency_sources=dependency_sources)
        return component, lock

    @staticmethod
    def translation_options(original, link_inputs):
        """The original compile flags, without source/object inputs or link output."""
        paths = {str(path) for path in link_inputs}
        options, at = [], 0
        while at < len(original):
            value = str(original[at])
            if value == '-o': at += 2; continue
            if value in paths or value.startswith('-Wl,'):
                at += 1; continue
            options.append(value); at += 1
        return options

    def observe_compiler_edges(self, original, destination, link_inputs, *, dependency_sources=()):
        """Passive per-TU O2 metadata under this original finite compiler owner.

        Keep each TU's original compile options and warning policy. Remove its
        link inputs/output and linker-only options; component argv is untouched.
        A missing/large/unmapped witness is unavailable, never support.
        """
        from tools.rust_capsule_project import read_file
        selected = sorted({row['source'] for row in self.compiler_edges.queries})
        options = self.translation_options(original, link_inputs)
        for index, name in enumerate(selected):
            try:
                source = self.compiler_edge_sources[name]
                unit_options = [value for value in options
                                if value != '-Werror' or source not in dependency_sources]
                witness = destination / ('compiler-edge-%04d.ll' % index)
                # Zig's IR-only driver adds an otherwise unused -c internally.
                # Keep that bounded warning visible without making it fatal;
                # normal component argv and every other -Werror stay unchanged.
                self.run('zig', *unit_options, '-S', '-emit-llvm',
                    '-Wno-error=unused-command-line-argument', str(source), '-o', str(witness))
                self.compiler_edges.retain_unit(name, read_file(witness, 4 * 1024 * 1024))
            except Exception:
                self.compiler_edges.fail_unit(name)
        self.check_unchanged()


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
