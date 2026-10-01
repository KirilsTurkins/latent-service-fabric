"""Finite NativeAOT compiler inputs, SDK child tools and namespace execution."""
from __future__ import annotations
from pathlib import Path
import os
import shutil
import sys
import sysconfig

from tools.application_dependency_store import DependencyError, regular_path, read_bytes
from tools.build_snapshot import digest
from tools.captured_compiler_isolation import Isolation


class DotnetIsolation(Isolation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.argument_files = {}

    @staticmethod
    def observe_distribution(root: Path):
        from tools.dotnet_guest.compiler import tree_identity
        # The existing maintained .NET observer permits only internal symlinks
        # and binds their logical targets under 65,536 entries / four GiB.
        return tree_identity({'compiler': root})['files']

    def wrap(self, tool: Path, arguments: list[str], cwd: Path, environment: dict[str, str]) -> list[str]:
        command = super().wrap(tool, arguments, cwd, environment)
        index = command.index('--chdir')
        additions = ['--ro-bind', str(self.tools['shell']), '/bin/sh']
        for source, destination in getattr(self, 'namespace_identity_files', {}).items():
            additions += ['--ro-bind', str(source), destination]
        for name in ('dotnet', 'python', 'shell', 'wasm-tools', 'wit-bindgen'):
            additions += ['--setenv', 'LSF_CAPTURED_' + name.upper().replace('-', '_'), str(self.tools[name])]
        fixed = {'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_NOLOGO': '1', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1',
                 'DOTNET_ROLL_FORWARD': 'Disable', 'DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE': 'true',
                 'DOTNET_CLI_USE_MSBUILD_SERVER': '0', 'MSBUILDDISABLENODEREUSE': '1',
                 'DOTNET_EnableDiagnostics': '0', 'DOTNET_EnableDiagnostics_IPC': '0',
                 'DOTNET_NUGET_SIGNATURE_VERIFICATION': 'true', 'NUGET_CERT_REVOCATION_MODE': 'offline',
                 'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT': '1', 'DOTNET_GENERATE_ASPNET_CERTIFICATE': 'false'}
        for key, expected in fixed.items():
            if environment.get(key, expected) != expected:
                raise DependencyError('captured-dotnet-compiler-policy-invalid:' + key)
            additions += ['--setenv', key, expected]
        for key in ('DOTNET_ROOT', 'DOTNET_HOST_PATH', 'DOTNET_CLI_HOME', 'NUGET_PACKAGES', 'NUGET_HTTP_CACHE_PATH',
                    'NUGET_PLUGINS_CACHE_PATH', 'LSF_WIT_BINDGEN', 'LSF_WASM_TOOLS', 'LSF_CAPTURED_BINDING', 'PYTHONHOME'):
            if key in environment:
                additions += ['--setenv', key, environment[key]]
        command = command[:index] + additions + command[index:]
        if len(command) <= 256:
            return command
        # The full .NET/Python loader closure can exceed the process helper's
        # fixed argv count. Bubblewrap accepts NUL-separated options via an
        # inherited descriptor; a fixed captured shell only opens that file.
        if len(command) > 4096 or any('\0' in value or len(value) > 32768 for value in command):
            raise DependencyError('dotnet-namespace-argument-limit')
        root = self.workspace / 'namespace-arguments'
        root.mkdir(exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise DependencyError('dotnet-namespace-argument-directory-invalid')
        path = root / (str(len(self.argument_files)) + '.bin')
        index = command.index('--chdir')
        command[index:index] = ['--ro-bind', str(path), str(path)]
        if len(command) > 4096:
            raise DependencyError('dotnet-namespace-argument-limit')
        separator = command.index('--')
        encoded = b'\0'.join(value.encode() for value in command[1:separator]) + b'\0'
        if len(encoded) > 1024 * 1024 or len(self.argument_files) >= 128:
            raise DependencyError('dotnet-namespace-argument-limit')
        with path.open('xb') as stream:
            stream.write(encoded)
        path.chmod(0o600)
        self.argument_files[path] = {'digest': digest(encoded), 'size': len(encoded)}
        wrapped = [str(self.tools['shell']), '-c', 'exec 3<"$1"; shift; exec "$@"',
                   'sdk-owned-namespace-arguments', str(path), command[0], '--args', '3', '--', *command[separator + 1:]]
        if len(wrapped) > 256:
            raise DependencyError('dotnet-namespace-command-argument-limit')
        return wrapped

    def check_unchanged(self):
        super().check_unchanged()
        for path, identity in self.argument_files.items():
            content = read_bytes(path, 1024 * 1024)
            if {'digest': digest(content), 'size': len(content)} != identity:
                raise DependencyError('dotnet-namespace-arguments-mutated')

    def executed_arguments(self):
        return {path.name: identity for path, identity in self.argument_files.items()}


def stage_http_errors(sdk: Path, tools: Path, destination: Path) -> Path:
    """Carry the SDK-owned BCL transformer and exact framework into the namespace."""
    from tools.dotnet_guest import http_errors
    from tools.rust_capsule_project import snapshot

    http_errors.verify_installed(sdk, tools)
    sources = {name: snapshot(tools / name) for name in ('http-errors', 'http-errors-source')}
    originals = http_errors.source_paths(tools)
    for original in originals:
        http_errors.require_digest(original, http_errors.SOURCE_DIGEST, 'http-error-framework')
    destination.mkdir()
    for name, files in sources.items():
        for relative, body in files.items():
            path = destination / name / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as output:
                output.write(body)
    for original, copied in zip(originals, http_errors.source_paths(destination)):
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, copied)
        http_errors.require_digest(copied, http_errors.SOURCE_DIGEST, 'http-error-framework')
        http_errors.require_digest(original, http_errors.SOURCE_DIGEST, 'http-error-framework')
    for name, files in sources.items():
        if snapshot(tools / name) != files or snapshot(destination / name) != files:
            raise DependencyError('http-error-namespace-input-mutated')
    http_errors.verify_installed(sdk, destination)
    return destination


def stage_adapters(runtimes: dict[str, Path], destination: Path) -> dict[str, Path]:
    """Capture the finite SDK adapter family inside the compiler namespace."""
    from tools.dotnet_guest.runtime import ADAPTERS
    if set(runtimes) != set(ADAPTERS):
        raise DependencyError('dotnet-runtime-adapters-not-captured')
    before = {name: read_bytes(path, 64 * 1024 * 1024) for name, path in runtimes.items()}
    destination.mkdir()
    result = {}
    for name, source in runtimes.items():
        path = destination / ADAPTERS[name][1]
        shutil.copyfile(source, path)
        if (read_bytes(source, 64 * 1024 * 1024) != before[name]
                or read_bytes(path, 64 * 1024 * 1024) != before[name]):
            raise DependencyError('dotnet-runtime-adapter-input-mutated')
        result[name] = path
    return result


def stage(compiler, workspace: Path) -> DotnetIsolation:
    """Build a compiler distribution containing only selected SDK inputs."""
    root = workspace / 'captured-dotnet-tools'
    root.mkdir()
    dotnet_root = root / 'dotnet'
    dotnet_root.mkdir()
    selected = {}
    locations = {'dotnet-sdk': 'sdk/10.0.100', 'dotnet-runtime': 'shared/Microsoft.NETCore.App/10.0.0',
                 'dotnet-ref': 'packs/Microsoft.NETCore.App.Ref/10.0.0',
                 'dotnet-ref-aspnet': 'packs/Microsoft.AspNetCore.App.Ref/10.0.0', 'dotnet-hostfxr': 'host/fxr'}
    for name, relative in locations.items():
        source = compiler.roots[name]
        destination = dotnet_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=True)
        selected[name] = destination
    shutil.copyfile(compiler.dotnet, dotnet_root / 'dotnet')
    (dotnet_root / 'dotnet').chmod(0o700)
    selected['dotnet-host'] = dotnet_root
    packages = root / 'sdk-packages'
    packages.mkdir()
    for name, source in compiler.roots.items():
        if not name.startswith('nuget/'):
            continue
        destination = packages / name.removeprefix('nuget/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=True)
    selected['sdk-nuget-packages'] = packages
    selected['wasi-sdk'] = compiler.wasi_sdk
    adapter = root / 'runtime-adapters'
    compiler.runtimes = stage_adapters(compiler.runtimes, adapter)
    compiler.runtime = compiler.runtimes['closed']
    selected['runtime-adapters'] = adapter
    composer = root / 'component-composer'
    shutil.copytree(compiler.roots['component-composer'], composer)
    selected['component-composer'] = composer
    if 'http-errors' in compiler.roots:
        compiler.http_error_tools = stage_http_errors(compiler.sdk, compiler.tools, root / 'http-error-support')
        selected['http-error-support'] = compiler.http_error_tools
    python_root = root / 'python'
    python_bin = python_root / 'bin/python'
    python_bin.parent.mkdir(parents=True)
    shutil.copyfile(Path(sys.executable).resolve(strict=True), python_bin)
    python_bin.chmod(0o700)
    stdlib = Path(sysconfig.get_path('stdlib')).resolve(strict=True)
    shutil.copytree(stdlib, python_root / 'lib' / ('python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor)),
                    ignore=shutil.ignore_patterns('site-packages', 'dist-packages', '__pycache__'), symlinks=True)
    if sysconfig.get_config_var('Py_ENABLE_SHARED'):
        library = Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')
        actual = library.resolve(strict=True)
        shutil.copyfile(actual, python_root / 'lib' / actual.name)
        if actual.name != library.name:
            shutil.copyfile(actual, python_root / 'lib' / library.name)
    selected['compiler-python-stdlib'] = python_root
    helpers = root / 'bin'
    helpers.mkdir()
    shell = Path(shutil.which('sh') or 'missing-sh').resolve(strict=True)
    tools = {'dotnet': dotnet_root / 'dotnet', 'python': python_bin, 'shell': shell,
             'wasm-tools': compiler.wasm, 'wit-bindgen': compiler.bindgen}
    # SDK processes may start these helpers by name. The owned wrappers are
    # immutable recipe inputs and call only explicitly captured executables.
    for name, executable in list(tools.items()):
        path = helpers / name
        path.write_text('#!/bin/sh\nexec "$LSF_CAPTURED_' + name.upper().replace('-', '_') + '" "$@"\n', encoding='utf-8')
        path.chmod(0o700)
        tools['wrapper/' + name] = path
    shell_alias = helpers / 'sh'
    shell_alias.write_text('#!/bin/sh\nexec "$LSF_CAPTURED_SHELL" "$@"\n', encoding='utf-8')
    shell_alias.chmod(0o700)
    tools['wrapper/sh'] = shell_alias
    selected['sdk-child-wrappers'] = helpers
    identity = root / 'namespace-identity'
    identity.mkdir()
    uid, gid = os.getuid(), os.getgid()
    for name, content in {
            'passwd': f'lsf-compiler:x:{uid}:{gid}:SDK-owned compiler identity:/home:/bin/sh\n',
            'group': f'lsf-compiler:x:{gid}:\n',
            'nsswitch.conf': 'passwd: files\ngroup: files\nhosts: files\n'}.items():
        (identity / name).write_text(content, encoding='ascii')
    selected['namespace-identity'] = identity
    compiler.dotnet = tools['dotnet']
    compiler.python = python_bin
    compiler.package_cache = workspace / 'nuget-packages'
    shutil.copytree(packages, compiler.package_cache, symlinks=True)
    compiler.wac = composer / 'wac'
    compiler.wac = compiler.wac.resolve(strict=True)
    tools['component-composer'] = compiler.wac
    # Capture every selected native executable/shared module that a managed
    # compiler or LLVM process can load. ldd then binds its exact system files.
    optional_diagnostics = []
    for name, directory in selected.items():
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                resolved = path.resolve(strict=True)
                with resolved.open('rb') as stream:
                    if stream.read(4) != b'\x7fELF':
                        continue
                if name in {'dotnet-runtime', 'dotnet-host'} and path.name == 'libcoreclrtraceptprovider.so':
                    # The fixed host profile disables diagnostics. The SDK's
                    # optional LTTng 2.12 provider cannot use Ubuntu 24's 2.13
                    # ABI; its bytes remain hashed, and that ABI is not enabled.
                    optional_diagnostics.append({'distribution': name, 'path': path.relative_to(directory).as_posix()})
                    continue
                tools.setdefault('native/' + name + '/' + path.relative_to(directory).as_posix(), resolved)
    isolation = DotnetIsolation(workspace, tools, selected)
    isolation.namespace_identity_files = {identity / name: '/etc/' + name for name in ('passwd', 'group', 'nsswitch.conf')}
    isolation.enable_children(helpers)
    isolation.receipt['distributionObserver'] = {'profile': 'dotnet-compiler-internal-links-v1', 'maximumEntries': 65536, 'maximumBytes': 4 * 1024**3}
    isolation.receipt['compilerAliases'] = {'/bin/sh': isolation.tool_before['shell']}
    isolation.receipt['compilerHostGlobalization'] = 'invariant'
    isolation.receipt['compilerNamespaceUser'] = {'name': 'lsf-compiler', 'uid': uid, 'gid': gid,
        'home': '/home', 'source': 'sdk-owned-synthetic-identity'}
    isolation.receipt['compilerHostDiagnostics'] = {'enabled': False, 'optionalProviders': optional_diagnostics}
    isolation.receipt['compilerPythonProfile'] = 'sdk-bindings-stdlib-without-site-packages-v1'
    isolation.receipt['compilerPatches'] = compiler.compiler_patches
    isolation.receipt['offlineNuGetSignaturePolicy'] = {'verification': 'enabled', 'revocation': 'offline',
        'currentness': 'no-online-certificate-revocation-proof'}
    isolation.receipt['namespaceArgumentTransport'] = {'profile': 'sdk-shell-bubblewrap-args-fd-v1',
        'maximumArguments': 4096, 'maximumBytes': 1024 * 1024, 'maximumCommands': 128,
        'shell': isolation.tool_before['shell']}
    compiler.commands.environment.update(DOTNET_ROOT=str(dotnet_root), DOTNET_HOST_PATH=str(compiler.dotnet),
        DOTNET_CLI_HOME=str(workspace / 'compiler-home'), NUGET_PACKAGES=str(compiler.package_cache),
        NUGET_HTTP_CACHE_PATH=str(workspace / 'nuget-http-cache'), NUGET_PLUGINS_CACHE_PATH=str(workspace / 'nuget-plugin-cache'),
        DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1', PYTHONHOME=str(python_root))
    return isolation
