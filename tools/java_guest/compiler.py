"""Compile actual Java sources using the current maintained TeaVM C backend."""
from __future__ import annotations
import json
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import time
import tomllib

from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.java_guest.bindings import generate
from tools.java_guest.surface import surface as wit_surface
from tools.rust_capsule_project import ROOT, canonical, digest, inventory, read_file, snapshot, write_json
from tools.stage_runtime_wit import copy_wit_tree, dependencies


def source_module(path: Path):
    """Load this captured SDK helper, never a prior project's module cache.

    Use the standard file loader, with bytecode writes disabled, for an explicit
    captured path. Legacy diagnostic helpers may adjust sys.path; isolate it.
    """
    read_file(path)  # Bound and reject nonregular source before importing it.
    spec = importlib.util.spec_from_file_location("lsf_java_captured_" + path.stem, path)
    if spec is None or spec.loader is None: raise ValueError("invalid captured Java helper module")
    module = importlib.util.module_from_spec(spec)
    search, bytecode = list(sys.path), sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = search
        sys.dont_write_bytecode = bytecode
    return module


def sdk_snapshot(root: Path) -> dict:
    # Exact production compiler inputs; never capture local feasibility build
    # output, Gradle caches, Python bytecode, or unreferenced diagnostic sources.
    files = {name: read_file(root / name) for name in (
        "compiler.gradle", "bindings.lock.json", "feasibility/settings.gradle", "feasibility/dependencies.lock.json",
        "feasibility/gradle/verification-metadata.xml", "feasibility/platform.c",
        "feasibility/closed-runtime.wat", "tools/feasibility.py", "tools/dependencies.py",
        "tools/teavm_platform.py", "tools/capture.py")}
    for folder in ("runtime", "templates", "wit"):
        files.update({folder + "/" + name: data for name, data in snapshot(root / folder).items()})
    return dict(sorted(files.items()))


def tool_inventory(roots: dict[str, Path]) -> bytes:
    files, total = {}, 0
    for label, root in sorted(roots.items()):
        root = root.resolve(strict=True)
        for path in sorted(root.rglob("*")):
            if path.is_symlink() and path.is_dir(): raise ValueError("compiler directory symlinks are unsupported")
            if path.is_dir(): continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root): raise ValueError("compiler input escapes its pinned distribution")
            name = label + "/" + path.relative_to(root).as_posix()
            item = (file_identity(resolved, name) if resolved.stat().st_size else
                    {"name": name, "digest": digest(b""), "size": 0})
            if path.is_symlink(): item["link"] = resolved.relative_to(root).as_posix()
            total += item["size"]
            if len(files) >= 32768 or total > 2 * 1024**3: raise ValueError("compiler closure exceeds its bound")
            files[name] = item
    return canonical(files)


class Compiler:
    def __init__(self, directory: Path, wasi_sdk: Path, *, gradle="gradle", sdk: Path | None = None,
                 platform: Path | None = None, config: dict | None = None, timeout=900):
        self.directory, self.wasi_sdk = directory.resolve(), wasi_sdk.resolve()
        self.sdk = sdk or ROOT / "sdk/java-guest"
        self.platform = platform or ROOT / "wit/platform"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.environment = build_environment(self.directory)
        # An explicit JDK may be needed by Gradle's Java toolchain discovery.
        if "JAVA_HOME" in os.environ: self.environment["JAVA_HOME"] = os.environ["JAVA_HOME"]
        self.environment["GRADLE_USER_HOME"] = str(self.directory / "gradle-home")
        self.deadline = time.monotonic() + timeout
        self.records = []
        self.retained_bytes = 0
        self.paths = {}
        self.materials = []
        config = config or tomllib.loads((ROOT / "tools/toolchain.toml").read_text())
        if (self.wasi_sdk / "VERSION").read_text().splitlines() != [
            "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
            raise ValueError("unreviewed WASI-SDK Java compiler")
        verify_version = source_module(self.sdk / "tools/feasibility.py").verify_version
        for name, selected, version in [
            ("java", "java", config["sdk"]["java"]), ("gradle", gradle, config["sdk"]["gradle"]),
            ("clang", str(self.wasi_sdk / "bin/clang"), "21.1.4-wasi-sdk"),
            ("wit-bindgen", "wit-bindgen", config["rust"]["dependencies"]["wit-bindgen"]),
            ("wasm-tools", "wasm-tools", config["contracts"]["wasm-tools"]),
        ]:
            located = shutil.which(selected, path=self.environment.get("PATH"))
            if not located: raise ValueError("missing Java tool: " + name)
            self.paths[name] = Path(located).resolve()
            if name == "java":
                jdk = self.paths[name].parent.parent
                selected = self.environment.get("JAVA_HOME")
                if selected is not None and Path(selected).resolve(strict=True) != jdk:
                    raise ValueError("JAVA_HOME and PATH must select the same pinned Java compiler")
                self.environment["JAVA_HOME"] = str(jdk)
            self.materials.append(file_identity(self.paths[name], name))
            log = self.run(name + "-version", name, "-version" if name == "java" else "--version")
            verify_version(name + "-version", log, version)
        self.original_sdk = sdk_snapshot(self.sdk)
        self.tool_roots = {"wasi-sdk": self.wasi_sdk, "jdk": self.paths["java"].parent.parent,
                           "gradle": self.paths["gradle"].parent.parent}
        self.compiler_inputs = tool_inventory(self.tool_roots)
        from tools.java_guest.lock import verify
        self.binding_digest = verify(self.run, self.sdk, self.platform, self.directory / "sdk-reference")

    def run(self, stage: str, tool: str, *arguments, cwd: Path | None = None) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise ValueError("Java build deadline exceeded")
        path = self.paths.get(tool, Path(tool))
        started = time.monotonic()
        argv = [str(path), *map(str, arguments)]
        exit_code = None
        try:
            result = run_bounded_result(argv, cwd or self.directory, self.environment,
                                 timeout_seconds=min(remaining, 600), max_output_bytes=4 * 1024 * 1024)
            exit_code = result.returncode
            log = result.stdout + b"\n" + result.stderr
            self.retained_bytes += len(log)
            if self.retained_bytes > 16 * 1024 * 1024:
                raise ValueError("Java build diagnostic retention exceeded 16 MiB")
            (self.directory / (str(len(self.records)) + "-" + stage + ".log")).write_bytes(log)
            if result.returncode:
                raise ValueError("Java compiler stage failed: " + stage + "; see retained log")
            return log.decode("utf-8")
        finally:
            self.records.append({"stage": stage, "command": argv, "exitCode": exit_code,
                                 "seconds": round(time.monotonic() - started, 6)})

    def compile(self, sources: Path, wit: Path, world: str, destination: Path) -> tuple[Path, dict]:
        destination.mkdir(parents=True, exist_ok=False)
        staged = destination / "wit"
        copy_wit_tree(wit, staged)
        for package in dependencies(wit, self.platform): copy_wit_tree(package, staged / "deps" / package.name)
        bindings = generate(self.run, staged, world, destination / "bindings")
        second = generate(self.run, staged, world, destination / "bindings-check")
        if second != bindings: raise ValueError("nondeterministic Java WIT bindings")
        project = destination / "project"
        project.mkdir()
        for name in ("settings.gradle", "dependencies.lock.json", "gradle/verification-metadata.xml"):
            path = project / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_file(self.sdk / "feasibility" / name))
        # Build script is owned by the SDK; applications supply Java and WIT,
        # never arbitrary Gradle plugins or unrecorded repository dependencies.
        (project / "build.gradle").write_bytes(read_file(self.sdk / "compiler.gradle"))
        # Never let Gradle silently select or provision an unobserved JDK. This
        # generated private property file is part of this source-bound recipe.
        (project / "gradle.properties").write_text(
            "org.gradle.java.installations.auto-detect=false\n"
            "org.gradle.java.installations.auto-download=false\n"
            "org.gradle.java.installations.fromEnv=JAVA_HOME\n", encoding="utf-8")
        java_root = project / "src/main/java"
        shutil.copytree(self.sdk / "runtime/dev", java_root / "dev")
        for path in sorted(sources.rglob("*.java")):
            if path.is_symlink(): raise ValueError("Java sources cannot be symlinks")
            target = java_root / path.relative_to(sources)
            if target.exists(): raise ValueError("application overrides Java SDK source")
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(read_file(path))
        target = java_root / "dev/latent/generated/Bindings.java"
        target.parent.mkdir(parents=True); target.write_bytes(read_file(destination / "bindings/Bindings.java"))
        self.run("java-to-c", "gradle", "--no-daemon", "generateC", cwd=project)
        retain = source_module(self.sdk / "tools/dependencies.py").retain
        retained = retain(self.directory / "gradle-home/caches/modules-2/files-2.1", project, destination, False)
        generated = project / "build/teavm-c/c"
        adapt = source_module(self.sdk / "tools/teavm_platform.py").adapt
        adaptation = adapt(generated)
        core, component = destination / "core.wasm", destination / "component.wasm"
        self.run("c-to-wasm", "clang", "-target", "wasm32-wasip1", "-std=c11", "-O2",
                 "-DLSF_TEAVM_WASM=1", "-DTEAVM_CUSTOM_LOG=1", "-mllvm", "-wasm-enable-sjlj", "-lsetjmp",
                 "-mllvm", "-wasm-use-legacy-eh=false", "-mexec-model=reactor", "-Wl,--no-entry",
                 "-Wl,--export-memory", "-Wl,-z,stack-size=65536", "-Wl,--max-memory=67108864",
                 "-include", self.sdk / "runtime/native.h",
                 "-I", destination / "bindings", "-I", self.sdk / "runtime", "-iquote", generated,
                 generated / "all.c", destination / "bindings/bridge.c", self.sdk / "feasibility/platform.c",
                 destination / "bindings/probe.c", destination / "bindings/probe_component_type.o", "-o", core)
        adapter = destination / "closed-runtime.wasm"
        self.run("closed-runtime", "wasm-tools", "component", "embed", staged, self.sdk / "feasibility/closed-runtime.wat",
                 "--world", "runtime-support", "-o", adapter)
        self.run("component-new", "wasm-tools", "component", "new", core, "--adapt", "wasi_snapshot_preview1=" + str(adapter), "-o", component)
        self.run("component-validate", "wasm-tools", "validate", component)
        surface = self.run("component-surface", "wasm-tools", "component", "wit", component)
        if "import wasi:" in surface: raise ValueError("ambient WASI survived the closed Java runtime")
        expected = wit_surface(json.loads(self.run("expected-wit", "wasm-tools", "component", "wit", staged, "--json")), world)
        actual = wit_surface(json.loads(self.run("compiled-wit", "wasm-tools", "component", "wit", component, "--json")))
        if actual != expected: raise ValueError("compiled Java component changed authoritative WIT semantics")
        return component, {"bindings": bindings, "dependencies": retained, "platform": adaptation,
                           "semanticSurfaceDigest": digest(canonical(actual))}

    def check_unchanged(self):
        if self.original_sdk != sdk_snapshot(self.sdk): raise ValueError("Java SDK changed during build")
        if self.compiler_inputs != tool_inventory(self.tool_roots): raise ValueError("Java compiler distribution changed during build")
        for item in self.materials:
            if file_identity(self.paths[item["name"]], item["name"]) != item: raise ValueError("Java compiler changed during build")
