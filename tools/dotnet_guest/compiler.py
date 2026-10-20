"""Pinned C# NativeAOT build with exact WIT and closed, explicitly clocked WASI."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import re
import shlex
import shutil
import sys
import tempfile
from tools.build_observation import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.dotnet_guest.sdk import install as install_sdk
from tools.dotnet_guest import runtime, http_errors, task_wait
from tools.dotnet_guest.resources import install as install_resources
from tools.guest_compatibility_build import interface_names

SDK_VERSION = "10.0.100"
COMPONENT_VERSION = "0.8.0-preview00011"


COMPILE_SETUP_PHASES = frozenset({'source-projection', 'project-inputs', 'sdk-facades',
    'entropy-selection', 'managed-entropy-selection', 'dependency-configuration',
    'protected-inputs', 'offline-configuration', 'task-wait-selection',
    'http-error-selection', 'resource-installation', 'resource-protection', 'resource-verification'})
COMPILE_EXCEPTION_KINDS = frozenset({'FileExistsError', 'FileNotFoundError', 'PermissionError',
    'IsADirectoryError', 'NotADirectoryError', 'OSError', 'ValueError', 'TypeError', 'KeyError',
    'IndexError', 'AttributeError', 'NameError', 'RuntimeError', 'AssertionError', 'ImportError',
    'JSONDecodeError', 'DependencyError', 'BuildProcessError', 'other'})
COMPILE_COMMAND_STAGES = frozenset({'bindings', 'bindings-drift', 'canonical-wit',
    'closed-runtime-composition', 'declared-runtime-wit', 'locked-restore', 'native-aot',
    'native-runtime-wit', 'runtime-final-wit', 'surface', 'validate'})
COMPILE_COMMAND_BOUNDARIES = frozenset({'resolve-executable', 'containment-wrap', 'command-execution'})
COMPILE_COMMAND_REASONS = {
    'build-process': {'sources': ('tools/build_process.py', 'tools/build_process_linux.py'), 'codes': frozenset({
        'command-context-invalid', 'command-deadline', 'command-environment-invalid', 'command-exit',
        'command-failed', 'command-invalid', 'command-output-limit', 'command-output-limit-invalid',
        'command-timeout-invalid', 'process-main-thread-required', 'process-platform-unsupported',
        'python-version-unsupported', 'child-reaper-unsupported', 'process-cleanup', 'process-ownership'})},
    'compiler-isolation': {'sources': ('tools/captured_compiler_isolation.py',), 'codes': frozenset({
        'compiler-executable-not-captured', 'compiler-working-directory-outside-captured-workspace'})},
}


def compile_command_context(compiler):
    """The failed command boundary only; never argv, cwd, output or error text."""
    value = getattr(compiler, 'compile_command_failure', None)
    fields = {'schemaVersion', 'stage', 'boundary', 'exceptionKind'}
    if (type(value) is not dict or set(value) not in (fields, fields | {'reasonSource', 'reasonCode'})
            or value.get('schemaVersion') != 'latent.dotnet.compile-command-failure.v1'
            or type(value.get('stage')) is not str or value['stage'] not in COMPILE_COMMAND_STAGES
            or type(value.get('boundary')) is not str or value['boundary'] not in COMPILE_COMMAND_BOUNDARIES
            or type(value.get('exceptionKind')) is not str or value['exceptionKind'] not in COMPILE_EXCEPTION_KINDS):
        return None
    if 'reasonCode' in value:
        source = value['reasonSource']
        expected_kind = {'build-process': 'BuildProcessError', 'compiler-isolation': 'DependencyError'}
        if (type(source) is not str or source not in COMPILE_COMMAND_REASONS
                or value['exceptionKind'] != expected_kind[source]
                or type(value['reasonCode']) is not str or value['reasonCode'] not in COMPILE_COMMAND_REASONS[source]['codes']):
            return None
    return dict(value)


def _command_failure(stage, boundary, error):
    from tools.application_dependency_store import DependencyError
    from tools.build_process import BuildProcessError
    if type(stage) is not str or stage not in COMPILE_COMMAND_STAGES:
        return None
    value = {'schemaVersion': 'latent.dotnet.compile-command-failure.v1', 'stage': stage,
        'boundary': boundary, 'exceptionKind': _compile_exception_kind(error)}
    source = 'build-process' if type(error) is BuildProcessError else 'compiler-isolation' if type(error) is DependencyError else None
    reason = error.args[0] if source is not None and len(error.args) == 1 else None
    if source is not None and type(reason) is str and reason in COMPILE_COMMAND_REASONS[source]['codes']:
        value.update(reasonSource=source, reasonCode=reason)
    return value


def _compile_exception_kind(error):
    from tools.application_dependency_store import DependencyError
    from tools.build_process import BuildProcessError
    known = (FileExistsError, FileNotFoundError, PermissionError, IsADirectoryError,
        NotADirectoryError, OSError, ValueError, TypeError, KeyError, IndexError,
        AttributeError, NameError, RuntimeError, AssertionError, ImportError,
        json.JSONDecodeError, DependencyError, BuildProcessError)
    return type(error).__name__ if type(error) in known else 'other'


def compile_failure_context(compiler, error):
    """Closed setup position/type only; no exception text, path or arguments."""
    phase = getattr(compiler, 'compile_failure_phase', None)
    if type(phase) is not str or phase not in COMPILE_SETUP_PHASES:
        return None
    original_kind = getattr(compiler, 'compile_failure_kind', None)
    captured = type(original_kind) is str and original_kind in COMPILE_EXCEPTION_KINDS
    return {'schemaVersion': 'latent.dotnet.compile-setup-failure.v1',
        'phase': phase, 'exceptionKind': original_kind if captured else _compile_exception_kind(error),
        'exceptionBoundary': 'setup-call' if captured else 'build-handler'}


def verify_application_resources(selected: dict, project: Path) -> None:
    """Recipe setup must not substitute reviewed trimming/resource bytes."""
    from tools.application_dependency_store import DependencyError, read_bytes
    for kind in ('resources', 'trimmingDescriptors'):
        for row in selected[kind]:
            if not row['active']:
                continue
            try:
                raw = read_bytes(project / row['attributes']['Include'], row['size'])
            except (OSError, DependencyError):
                raise DependencyError('nuget-compiler-resource-preimage-mismatch') from None
            if len(raw) != row['size'] or digest(raw) != row['digest']:
                raise DependencyError('nuget-compiler-resource-preimage-mismatch')


def runtime_inputs(root: Path) -> bytes:
    files = {"sdk/dotnet-guest/runtime/" + name: value
             for name, value in snapshot(root / "sdk/dotnet-guest/runtime").items()}
    for name in ("Cargo.toml", "Cargo.lock", "tools/toolchain-smoke/Cargo.toml", *runtime.EXAMPLES):
        files[name] = read_file(root / name)
    return inventory(files)


def tree_identity(roots: dict[str, Path]) -> dict:
    rows, total = [], 0
    for prefix, root in sorted(roots.items()):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("compiler input root is not a regular directory:" + prefix)
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if resolved != root and root not in resolved.parents:
                    raise ValueError("compiler input symlink leaves the captured tool root")
                # The canonical target is also inventoried under this root;
                # preserve the logical link identity without following a cycle.
                target = resolved.relative_to(root).as_posix().encode()
                rows.append({"path": prefix + "/" + path.relative_to(root).as_posix(),
                             "digest": digest(target), "size": len(target), "kind": "symlink"})
                total += len(target)
                if len(rows) > 65536 or total > 4 * 1024**3:
                    raise ValueError("finite .NET compiler input closure exceeded")
                continue
            if path.is_dir():
                continue
            row = file_identity(path, "compiler-file", 512 * 1024 * 1024) if path.stat().st_size else {
                "digest": digest(read_file(path)), "size": 0}
            total += row["size"]
            rows.append({"path": prefix + "/" + path.relative_to(root).as_posix(), "digest": row["digest"], "size": row["size"]})
            if len(rows) > 65536 or total > 4 * 1024**3:
                raise ValueError("finite .NET compiler input closure exceeded")
    return {"files": rows, "bytes": total}


def packages(lock: dict, directory: Path, content_hash) -> dict[str, Path]:
    result = {}
    for target in lock["dependencies"].values():
        for name, value in target.items():
            identity = name.lower() + "/" + value["resolved"]
            path = directory / identity
            archive = path / (name.lower() + "." + value["resolved"] + ".nupkg")
            if not archive.is_file() or archive.is_symlink() or archive.stat().st_size > 512 * 1024 * 1024:
                raise ValueError("missing or oversized locked NuGet archive:" + identity)
            if content_hash(archive) != value["contentHash"]:
                raise ValueError("NuGet content hash differs from the exact dependency lock:" + identity)
            result["nuget/" + identity] = path
    return result


class Compiler:
    def __init__(self, tools: Path, commands, vendor: Path, *, offline: bool = False, captured: bool = False):
        if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
            raise ValueError("the pinned NativeAOT LLVM compiler is qualified only on Linux x86-64")
        self.tools, self.commands, self.vendor = tools.resolve(strict=True), commands, vendor
        self.http_error_tools = self.tools
        self.offline = offline or captured
        self.isolation, self.application_closure, self.executable_approval = None, None, None
        self.generated_materials, self.noncrypto_port = [], None
        self.python, self.package_cache = Path(sys.executable).resolve(strict=True), self.tools / 'packages'
        self.sdk = vendor / "sdk/dotnet-guest"
        self.dotnet = Path(shutil.which("dotnet", path=commands.environment["PATH"]) or "missing-dotnet").resolve(strict=True)
        self.wasm = Path(shutil.which("wasm-tools", path=commands.environment["PATH"]) or "missing-wasm-tools").resolve(strict=True)
        self.bindgen = Path(shutil.which("wit-bindgen", path=commands.environment["PATH"]) or "missing-wit-bindgen").resolve(strict=True)
        commands.environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
            DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_CLI_HOME=str(tools / "cli-home"), DOTNET_ROLL_FORWARD="Disable",
            NUGET_PACKAGES=str(tools / "packages"), LSF_WIT_BINDGEN=str(self.bindgen), LSF_WASM_TOOLS=str(self.wasm),
            DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", MSBUILDDISABLENODEREUSE="1",
            DOTNET_CLI_USE_MSBUILD_SERVER="0", DOTNET_EnableDiagnostics="0", DOTNET_EnableDiagnostics_IPC="0",
            LC_ALL="C.UTF-8", LANG="C.UTF-8")
        if commands.run("dotnet-version", self.dotnet, "--version").strip() != SDK_VERSION.encode():
            raise ValueError(".NET SDK 10.0.100 is required")
        if commands.run("wasm-tools-version", self.wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
            raise ValueError("unreviewed component validator")
        if commands.run("wit-bindgen-version", self.bindgen, "--version").strip() != b"wit-bindgen-cli 0.62.0":
            raise ValueError("unreviewed WIT generator")
        sdks = commands.run("dotnet-sdks", self.dotnet, "--list-sdks").decode()
        matches = re.findall(r"(?m)^10\.0\.100 \[(.+)\]$", sdks)
        if len(matches) != 1:
            raise ValueError("unique pinned .NET SDK location required")
        installation = Path(matches[0]).parent
        self.roots = {"dotnet-sdk": Path(matches[0]) / SDK_VERSION,
                      "dotnet-runtime": installation / "shared/Microsoft.NETCore.App/10.0.0",
                      "dotnet-ref": installation / "packs/Microsoft.NETCore.App.Ref/10.0.0",
                      "dotnet-ref-aspnet": installation / "packs/Microsoft.AspNetCore.App.Ref/10.0.0",
                      "dotnet-hostfxr": installation / "host/fxr"}
        self.roots["package-hash"] = tools / "package-hash"
        if snapshot(tools / "package-hash-source") != snapshot(self.sdk / "tools/package-hash"):
            raise ValueError("NuGet content-hash source differs from the captured SDK")
        http_error_tool = http_errors.verify_installed(self.sdk, tools)
        self.roots["http-errors"] = tools / "http-errors"
        self.roots["http-errors-source"] = tools / "http-errors-source"
        self.http_error_port = None
        self.task_wait_port = None
        self.roots.update(packages(json.loads(read_file(self.sdk / "probes/smoke/packages.lock.json")), tools / "packages",
            lambda archive: commands.run("nuget-content-hash", self.dotnet, tools / "package-hash/PackageHash.dll", archive).decode().strip()))
        self.wasi_sdk = Path(json.loads(read_file(tools / "wasi-sdk.json"))["path"]).resolve(strict=True)
        if read_file(self.wasi_sdk / "VERSION").decode().splitlines() != [
                "29.0", "wasi-libc: ac020b86fd44", "llvm: 222fc11f2b8f", "llvm-version: 21.1.4", "config: f992bcc08219"]:
            raise ValueError("WASI SDK compiler version drift")
        self.roots["wasi-sdk"] = self.wasi_sdk
        self.runtimes = {name: tools / filename for name, (_example, filename) in runtime.ADAPTERS.items()}
        if read_file(tools / "runtime-inputs.json") != runtime_inputs(vendor):
            raise ValueError("installed runtime source capture differs from the project SDK")
        from tools.dotnet_guest.composer import observed as observed_composer, selection as composer_selection
        bundled_composer = tools / "packages/bytecodealliance.componentize.dotnet.wasm.sdk" / COMPONENT_VERSION / "tools/linux-x64/wac"
        self.wac = observed_composer(tools, self.sdk)
        self.roots['component-composer'] = tools / 'component-composer'
        self.compiler_patches = [{
            'name': 'wac-imported-resource-alias-v1', 'profile': 'dotnet-native-aot-component-v1',
            'original': file_identity(bundled_composer, 'sdk-bundled-component-composer'),
            'selected': file_identity(self.wac, 'component-composer'), 'selection': composer_selection(self.sdk)}]
        if commands.run('component-composer-version', self.wac, '--version').strip() != b'wac-cli 0.10.1':
            raise ValueError('unreviewed component composer version')
        self.runtime = self.runtimes["closed"]
        self.materials = [file_identity(path, name) for name, path in (
            ("dotnet", self.dotnet), ("wasm-tools", self.wasm), ("wit-bindgen", self.bindgen),
            *((runtime.ADAPTERS[name][0].removeprefix("dotnet-"), path)
              for name, path in self.runtimes.items()), ('component-composer', self.wac))]
        self.materials.append(http_error_tool)
        self.before = tree_identity(self.roots)
        if captured:
            from tools.dotnet_compiler_isolation import stage
            self.isolation = stage(self, commands.root.parent)

    def run(self, name, executable, *arguments):
        self.compile_command_failure = None
        boundary = 'resolve-executable'
        try:
            executable = Path(executable).resolve(strict=True)
            if self.isolation is None:
                boundary = 'command-execution'
                return self.commands.run(name, executable, *arguments)
            boundary = 'containment-wrap'
            wrapped = self.isolation.wrap(executable, [str(value) for value in arguments],
                self.commands.root, self.commands.environment)
            boundary = 'command-execution'
            return self.commands.run(name, *wrapped)
        except BaseException as error:
            try:
                self.compile_command_failure = _command_failure(name, boundary, error)
            except Exception:
                pass  # Optional closed evidence must preserve the original failure.
            raise

    def native_aot(self, project: Path, output: Path, wrapper: Path):
        from tools.dotnet_guest.outputs import capture
        try:
            self.run("native-aot", self.dotnet, "build", project / "Capsule.csproj", "-c", "Release", "--no-restore",
                "-nodeReuse:false", "-p:UseSharedCompilation=false", "-p:WasiSdkRoot=" + str(self.wasi_sdk),
                "-p:WitBindgenExe=" + str(wrapper), '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false',
                *(['-p:EmitCompilerGeneratedFiles=true', '-p:CompilerGeneratedFilesOutputPath=' + str(output / 'generator-outputs')]
                  if self.application_closure else []))
        except BaseException:
            if self.executable_approval is not None:
                try:
                    capture(output / 'generator-outputs', self.commands.output, self.executable_approval,
                            compiler_command_succeeded=False)
                except Exception:
                    pass  # Keep the original compiler failure if diagnostic capture also fails.
            raise
        if self.executable_approval is not None:
            capture(output / 'generator-outputs', self.commands.output, self.executable_approval,
                    compiler_command_succeeded=True)

    def _setup(self, phase, operation, *args, **kwargs):
        self.compile_failure_phase = phase
        self.compile_failure_kind = None
        try:
            return operation(*args, **kwargs)
        except BaseException as error:
            # Keep only the closed category before outer process cleanup runs.
            self.compile_failure_kind = _compile_exception_kind(error)
            raise

    def compile(self, work: Path, world: str, output: Path):
        self.compile_command_failure = None
        self.compile_failure_phase = 'source-projection'
        self.compile_failure_kind = None
        if self.isolation is not None and not output.resolve().is_relative_to(self.isolation.workspace):
            raise ValueError('NativeAOT-output-outside-captured-build-workspace')
        output.mkdir()
        command, source = self.commands, work / "wit"
        declared = interface_names(json.loads(self.run("declared-runtime-wit", self.wasm,
            "component", "wit", source, "--json")), world)["imports"]
        runtime.select(declared, [])
        from tools.dotnet_guest import retirement
        binding_source, retirement_port = retirement.prepare(self, source, world, output/'retirement-port', declared)
        if retirement_port is not None:
            self.compiler_patches.append({'name':retirement.PROFILE, 'profile':retirement.PROFILE,
                'original':file_identity(output/'retirement-port/original.wit', 'original-retirement-wit', retirement.MAX_TEXT),
                'selected':file_identity(binding_source, 'private-retirement-wit', retirement.MAX_TEXT),
                'selection':retirement_port})
        generated = output / "generated"
        binding = work / "vendor/lsf/tools/dotnet_guest_bindings.py"
        self.run("bindings", self.python, "-I", "-B", binding, "c-sharp", binding_source, "--world", world,
            "--runtime", "native-aot", "--with-wit-results", "--out-dir", generated)
        self.run("bindings-drift", self.python, "-I", "-B", binding, "c-sharp", binding_source, "--world", world,
            "--runtime", "native-aot", "--with-wit-results", "--out-dir", generated, "--check")
        receipt = json.loads(read_file(generated / "bindings.json", 16 * 1024 * 1024))
        project = output / "project"
        project.mkdir()
        resource_inputs = set()
        if self.application_closure is not None:
            from tools.dotnet_application_dependencies import declarations, configure
            selected = declarations(snapshot(work, exclude=('dependencies', 'application-vendor')))
            resource_inputs = {row['attributes']['Include'] for key in ('resources', 'trimmingDescriptors') for row in selected[key] if row['active']}
        for name, data in snapshot(work / "src").items():
            if not name.endswith(".cs") and 'src/' + name not in resource_inputs:
                raise ValueError("unsupported C# application input; put sources in src/*.cs")
            path = project / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in sorted(resource_inputs):
            if name.startswith('src/'):
                continue
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_file(work / name))
        self.compile_failure_phase = 'project-inputs'
        for name, data in {
            "Capsule.csproj": read_file(work / "Capsule.csproj"),
            "global.json": read_file(self.sdk / "global.json"),
            "nuget.config": read_file(self.sdk / "nuget.config"),
            "packages.lock.json": read_file(work / 'packages.lock.json') if self.application_closure else read_file(self.sdk / "probes/smoke/packages.lock.json"),
            "component.wit": self.run("canonical-wit", self.wasm, "component", "wit", binding_source, "--no-docs"),
        }.items():
            (project / name).write_bytes(data)
        facades = self._setup('sdk-facades', install_sdk, self.sdk, generated, project / "lsf")
        from tools.dotnet_guest.entropy import prepare as prepare_entropy
        self.noncrypto_port = self._setup('entropy-selection', prepare_entropy, self, declared, project, output)
        self.managed_entropy_port = None
        if self.noncrypto_port is not None:
            from tools.dotnet_guest.managed_entropy import prepare as prepare_managed_entropy
            self.managed_entropy_port = self._setup('managed-entropy-selection', prepare_managed_entropy, self, project, output)
        if self.application_closure is not None:
            selected = self._setup('dependency-configuration', configure, self.application_closure, work, self.package_cache)
            self.cache_before = tree_identity({'nuget-packages': self.package_cache})
            write_json(command.output / 'nuget-build-inputs.json', selected)
            self._setup('protected-inputs', self.isolation.protect_inputs, self.package_cache, work, project / 'src', project / 'lsf', project / 'Capsule.csproj', project / 'component.wit')
            for name in resource_inputs:
                self._setup('protected-inputs', self.isolation.protect_inputs, project / name)
        if self.offline:
            self.compile_failure_phase = 'offline-configuration'
            # All locked packages must already be present. An empty source list
            # prohibits restore from silently reaching the network on a miss.
            (project / "nuget.config").write_text(
                '<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
        self.task_wait_port = None
        if self._setup('task-wait-selection', task_wait.selected, declared, receipt.get('asyncExportBridge')):
            self.task_wait_port = self._setup('task-wait-selection', task_wait.prepare, self.sdk, self.http_error_tools, self.package_cache, self.dotnet,
                declared, receipt.get('asyncExportBridge'), project, output, command.output, self.run,
                protect_inputs=self.isolation.protect_inputs if self.isolation else None)
        self.http_error_port = None
        if {runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION} <= set(declared):
            self.http_error_port = self._setup('http-error-selection', http_errors.prepare, self.sdk, self.http_error_tools, self.dotnet, declared, project,
                output, command.output, self.run,
                protect_inputs=self.isolation.protect_inputs if self.isolation else None,
                task_wait_port=self.task_wait_port)
        resources = self._setup('resource-installation', install_resources, snapshot(work, exclude=("dependencies", "application-vendor")), project)
        if self.isolation is not None and resources is not None:
            self._setup('resource-protection', self.isolation.protect_inputs, project / "Capsule.csproj")
            if resources.objects:
                self._setup('resource-protection', self.isolation.protect_inputs, project / "resources")
        if self.application_closure is not None:
            self._setup('resource-verification', verify_application_resources, selected, project)
        self.compile_failure_phase = None
        self.run("locked-restore", self.dotnet, "restore", project / "Capsule.csproj", "--configfile",
            project / "nuget.config", "--locked-mode", "--packages", self.package_cache, "--disable-parallel",
            "-p:NuGetAudit=false", '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
        if self.application_closure is not None:
            from tools.dotnet_application_dependencies import analyze
            project_declaration = declarations(snapshot(work, exclude=('dependencies', 'application-vendor')))
            actual_selection = analyze(json.loads(read_file(project / 'packages.lock.json')),
                json.loads(read_file(project / 'obj/project.assets.json', 16 * 1024 * 1024)),
                json.loads(read_file(self.sdk / 'probes/smoke/packages.lock.json')), project_declaration)
            expected = json.loads(read_file(work / 'nuget-resolved.lock.json', 16 * 1024 * 1024))
            expected_rows = [{key: value for key, value in row.items() if key not in {'originalDigest', 'originalSize'}} for row in expected['packages']]
            if actual_selection['packages'] != expected_rows:
                expected_by_id = {row['package'] + '/' + row['version']: row for row in expected_rows}
                actual_by_id = {row['package'] + '/' + row['version']: row for row in actual_selection['packages']}
                write_json(command.output / 'nuget-asset-selection-drift.json', {'formatVersion': 1,
                    'expectedDigest': digest(json.dumps(expected_rows, sort_keys=True).encode()),
                    'actualDigest': digest(json.dumps(actual_selection['packages'], sort_keys=True).encode()),
                    'differences': [{'id': identity, 'fields': {key: {'expected': expected_by_id.get(identity, {}).get(key),
                        'actual': actual_by_id.get(identity, {}).get(key)} for key in
                        set(expected_by_id.get(identity, {})) | set(actual_by_id.get(identity, {}))
                        if expected_by_id.get(identity, {}).get(key) != actual_by_id.get(identity, {}).get(key)}}
                        for identity in sorted(set(expected_by_id) | set(actual_by_id))
                        if expected_by_id.get(identity) != actual_by_id.get(identity)]})
                raise ValueError('offline-NuGet-native-asset-selection-differs-from-reviewed-capture')
        # The upstream SDK interpolates WitBindgenExe into a shell Exec task.
        # Give it one ASCII-only owned path. Actual Python/source paths remain
        # literal quoted arguments, including spaces, Unicode and metacharacters.
        # This finite wrapper is private and retired after the owned process.
        with tempfile.TemporaryDirectory(prefix="lsf-dotnet-bindgen-", dir=str(output) if self.isolation else "/tmp") as wrapper_root:
            wrapper = Path(wrapper_root) / "wit-bindgen"
            if self.isolation:
                self.commands.environment['LSF_CAPTURED_BINDING'] = str(binding)
                script = '#!/bin/sh\nexec "$LSF_CAPTURED_PYTHON" -I -B "$LSF_CAPTURED_BINDING" "$@"\n'
            else:
                script = "#!/bin/sh\nexec " + shlex.join([sys.executable, "-I", "-B", str(binding)]) + ' "$@"\n'
            if len(script.encode()) > 16384:
                raise ValueError("binding wrapper path limit exceeded")
            wrapper.write_text(script, encoding="utf-8")
            wrapper.chmod(0o700)
            if self.isolation:
                self.isolation.protect_inputs(wrapper)
            self.native_aot(project, output, wrapper)
            if self.isolation:
                if wrapper.read_text() != script:
                    raise ValueError('SDK-owned-binding-wrapper-mutated')
                self.isolation.read_only_inputs.remove(wrapper)
        if self.noncrypto_port:
            port = self.noncrypto_port.finish(project, command.output)
            self.compiler_patches = [*self.compiler_patches, {"name": port["profile"], "profile": port["profile"],
                "original": port["original"], "selected": port["derived"],
                "selection": {"requiredDeclaration": port["requiredDeclaration"],
                    "originalMember": port["originalMember"], "sourceDigest": port["sourceDigest"],
                    "targetsDigest": port["targetsDigest"], "nativeLinkBinding": port["nativeLinkBinding"],
                    "secureRandom": port["secureRandom"]}}]
            self.generated_materials.extend((port["derived"],
                file_identity(command.output / "noncrypto-entropy-port.json", "noncrypto-entropy-port")))
        if self.managed_entropy_port is not None:
            managed = self.managed_entropy_port.finish(project, command.output)
            self.compiler_patches.append({"name": managed["patch"], "profile": managed["profile"],
                "original": managed["frameworkInputs"][0], "selected": managed["derived"],
                "selection": {key: managed[key] for key in ("sourceCaptureDigest", "targetsDigest", "helper",
                    "replaced", "unchangedMethods", "nativeAotReferenceBinding", "namedAlgorithmFactorySupported")}})
            self.generated_materials.extend((managed["helper"], managed["derived"],
                file_identity(command.output / "managed-entropy-port.json", "standard-rng-managed-port")))
        actual = list((project / "obj").rglob("bindings.json"))
        if len(actual) != 1 or json.loads(read_file(actual[0], 16 * 1024 * 1024))["outputs"] != receipt["outputs"]:
            raise ValueError("actual NativeAOT binding inputs differ from independent drift generation")
        raw = project / "bin/Release/net10.0/wasi-wasm/publish/Capsule.wasm"
        # The build workspace is retired on failure. Retain bounded compiler
        # output before runtime selection or composition can reject its graph.
        (command.output / 'native-aot-raw.wasm').write_bytes(read_file(raw, 64 * 1024 * 1024))
        (command.output / 'native-aot-original.wasm').write_bytes(read_file(raw, 64 * 1024 * 1024))
        from tools.dotnet_guest.compatibility import MAX_GRAPH, inspect as inspect_runtime
        raw_wit = self.run("native-runtime-wit", self.wasm, "component", "wit", raw, "--json")
        if len(raw_wit) > MAX_GRAPH:
            raise ValueError('native-aot-raw-wit-byte-limit')
        (command.output / 'native-aot-raw.wit.json').write_bytes(raw_wit)
        (command.output / 'native-aot-original.wit.json').write_bytes(raw_wit)
        actual = interface_names(json.loads(raw_wit))["imports"]
        if retirement_port is not None:
            if retirement.IDENTITY not in actual or not retirement.private_import(json.loads(raw_wit)):
                raise ValueError('dotnet-retirement-compiled-import-missing-or-changed')
            actual = [name for name in actual if name != retirement.IDENTITY]
            self.generated_materials.append(file_identity(command.output/'retirement-port.json', 'dotnet-retirement-port'))
        http_error_port = None
        if self.http_error_port is not None:
            http_error_port = self.http_error_port.finish(project, command.output)
            self.compiler_patches = [*self.compiler_patches, {
                "name": http_error_port["patch"], "profile": "dotnet-wasi-http-errors-v1",
                "original": http_error_port["frameworkInputs"][0], "selected": http_error_port["derived"],
                "selection": {key: http_error_port[key] for key in (
                    "sourceCaptureDigest", "targetsDigest", "method", "categories", "cecilDigest",
                    "arbitraryPayloadDisclosure", "nativeAotReferenceBinding")},
            }]
            if "synchronousRead" in http_error_port:
                self.compiler_patches[-1]["selection"]["synchronousRead"] = http_error_port["synchronousRead"]
            self.generated_materials.extend((self.http_error_port.identity,
                file_identity(command.output / "http-error-port.json", "dotnet-http-error-port", http_errors.MAX_RECEIPT)))
        if self.task_wait_port is not None:
            port = self.task_wait_port.finish(project, command.output)
            self.compiler_patches.append({'name': task_wait.PROFILE, 'profile': task_wait.PROFILE,
                'original': port['frameworkInput'], 'selected': port['derived'],
                'selection': {key: port[key] for key in ('sourceCaptureDigest', 'targetsDigest', 'method',
                    'maximumNestedWaits', 'completion', 'exceptionPropagation', 'nestedTaskIdentity',
                    'originalWaitBodyDigest', 'originalLoopBodyDigest', 'originalDispatchBodyDigest',
                    'unchangedOriginalMethods', 'completeOriginalWaitRemainderPreserved', 'nativeAotReferenceBinding')}})
            self.generated_materials.extend((self.task_wait_port.identity,
                file_identity(command.output / 'task-wait-port.json', 'dotnet-task-wait-port', http_errors.MAX_RECEIPT)))
        profile = runtime.select(declared, actual)
        adapter = self.runtimes[profile]
        from tools.dotnet_guest.internal_io import PROFILE as IO_PROFILE, prepare as prepare_internal_io
        from tools.dotnet_guest import closed_io
        io_original = file_identity(raw, 'original-native-aot-component', 64 * 1024 * 1024)
        io_port, closed_port = None, None
        if profile in closed_io.PROFILES:
            original_adapter = file_identity(adapter, 'original-closed-runtime-adapter', 64 * 1024 * 1024)
            adapter, closed_port = closed_io.prepare(self, adapter, output/'closed-io-port', profile)
            self.compiler_patches.append({'name': closed_io.PROFILE, 'profile': closed_io.PROFILE,
                'original': original_adapter,
                'selected': file_identity(adapter, 'synchronous-closed-runtime-adapter', 64 * 1024 * 1024),
                'selection': closed_port})
            self.generated_materials.append(file_identity(command.output/'closed-io-port.json', 'dotnet-closed-io-port'))
        else:
            raw, io_port = prepare_internal_io(self, raw, adapter, output / 'internal-io-port', json.loads(raw_wit))
        if io_port is not None:
            self.compiler_patches.append({'name': IO_PROFILE, 'profile': IO_PROFILE,
                'original': io_original, 'selected': file_identity(raw, 'internal-io-component', 64 * 1024 * 1024),
                'selection': io_port})
            self.generated_materials.append(file_identity(command.output / 'internal-io-port.json', 'dotnet-internal-io-port'))
        additional = [(name, self.runtimes[name]) for name in runtime.additional(declared, actual)]
        selection = {"schemaVersion": "latent.dotnet.runtime.v1", "profile": profile,
            "declaredImports": declared, "emittedImports": actual,
            "rawComponent": file_identity(raw, "raw-native-aot-component", 64 * 1024 * 1024),
            "adapter": file_identity(adapter, runtime.ADAPTERS[profile][0].removeprefix("dotnet-"))}
        if additional:
            selection["additionalAdapters"] = [file_identity(path, runtime.ADAPTERS[name][0].removeprefix("dotnet-"))
                                               for name, path in additional]
        if io_port is not None:
            selection['internalIoPort'] = io_port
        if closed_port is not None:
            selection['closedIoPort'] = closed_port
        if retirement_port is not None:
            selection['retirementPort'] = retirement_port
        write_json(command.output / "runtime-profile.json", selection)
        component = output / "component.wasm"
        self.runtime = adapter
        coverage = inspect_runtime(self, raw, additional_adapters=additional,
                                   owned_retirement=retirement_port is not None)
        if additional:
            from tools.dotnet_guest.composer import compose_exact
            compose_exact(self, raw, component, coverage, additional_adapters=additional,
                          owned_retirement=retirement_port is not None)
        else:
            self.run("closed-runtime-composition", self.wac, "plug", raw, "--plug", adapter, "-o", component)
        self.run("validate", self.wasm, "validate", component)
        final_interfaces = interface_names(json.loads(self.run("runtime-final-wit", self.wasm,
            "component", "wit", component, "--json")))
        final = final_interfaces['imports']
        if retirement.IDENTITY in final_interfaces['exports']:
            raise ValueError('compiler-private-retirement-export-escaped-composition')
        if retirement_port is not None and retirement.IDENTITY in final:
            raise ValueError('compiler-private-retirement-import-escaped-composition')
        if not set(final) <= set(declared):
            raise ValueError("runtime adapter introduced undeclared authority:" +
                             ",".join(sorted(set(final) - set(declared))))
        surface = self.run("surface", self.wasm, "component", "wit", component).decode()
        if "import wasi:" in surface or "wasi_snapshot_preview1" in surface:
            raise ValueError("ambient WASI import survived the closed runtime composition")
        (output / "component.wit").write_text(surface, encoding="utf-8")
        generated_receipt = {"bindings": receipt, "capabilities": facades,
            "runtimeProfile": selection,
            "filesDigest": digest(json.dumps(receipt["outputs"], sort_keys=True).encode())}
        if http_error_port is not None:
            generated_receipt["httpErrorPort"] = http_error_port
        if resources is not None:
            resources.check_unchanged()
            generated_receipt["embeddedResourceInputs"] = resources.observation
        return component, generated_receipt

    def check_unchanged(self):
        if getattr(self, "managed_entropy_port", None) is not None:
            self.managed_entropy_port.recheck()
        if self.noncrypto_port:
            self.noncrypto_port.recheck()
        if self.http_error_port:
            self.http_error_port.recheck()
        if tree_identity(self.roots) != self.before:
            raise ValueError("observed .NET compiler inputs changed during build")
        after = [file_identity(path, name) for name, path in (
            ("dotnet", self.dotnet), ("wasm-tools", self.wasm), ("wit-bindgen", self.bindgen),
            *((runtime.ADAPTERS[name][0].removeprefix("dotnet-"), path)
              for name, path in self.runtimes.items()), ('component-composer', self.wac))]
        after.append(http_errors.verify_installed(self.sdk, self.tools))
        if after != self.materials:
            raise ValueError(".NET compiler or runtime adapter changed during build")
        if self.isolation:
            self.isolation.check_unchanged()
            if self.application_closure and tree_identity({'nuget-packages': self.package_cache}) != self.cache_before:
                raise ValueError('captured-NuGet-compiler-cache-mutated')
