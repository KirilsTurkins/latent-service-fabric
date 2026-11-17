"""Prepare a captured C profile's CMake link-probe inputs without running CMake."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from tools import c_capsule_project, guest_runtime_receipts
from tools.build_observation import build_environment, file_identity
from tools.c_application_dependencies import wasm_object
from tools.captured_compiler_isolation import Isolation
from tools.c_dependency_authoring import build_inputs
from tools.c_guest import standard_facilities
from tools.c_guest.compiler import Compiler
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, decode_json, digest, fresh, inventory, read_file, write_json


def resolver_interface(observed: dict) -> bool:
    # LLVM may emit local helpers and constant data for the captured resolver.
    # Keep its external API and every allowed internal definition finite.
    exported = observed['strongSymbols']
    legacy = ['freeaddrinfo', 'getaddrinfo']
    current = ['freeaddrinfo', 'gai_strerror', 'getaddrinfo', 'getnameinfo']
    if exported not in (legacy, current):
        return False
    locals_allowed = {'numeric_canonical_name'}
    if exported == current:
        locals_allowed.update({'.L.str', '.Lswitch.table.gai_strerror'})
        locals_allowed.update(f'.L.str.{index}' for index in range(1, 12))
    defined = set(observed['definedSymbols'])
    return set(exported) <= defined <= set(exported) | locals_allowed


def safe_path(path: Path) -> Path:
    def unsafe(value: str) -> bool:
        return (any(ord(char) < 32 or ord(char) == 127 or char in ';\"\'$`' for char in value)
                or (os.name != 'nt' and '\\' in value))
    if unsafe(str(path)):
        raise ValueError('c-feature-probe-path')
    result = checked_path(path)
    if unsafe(str(result)):
        raise ValueError('c-feature-probe-path')
    return result


def recipe_identity() -> str:
    from tools.c_capsule_build import RECIPE
    return digest(inventory({name: read_file(ROOT / name) for name in RECIPE}))


SOCKET_SOURCE = standard_facilities.SDK_SOURCE_PREFIX + 'standard-streams.c'
SOCKET_HEADER = 'vendor/lsf/sdk/c-guest/include/lsf/standard-streams.h'
SOCKET_WIT = 'vendor/lsf/wit/platform/network/package.wit'
SOCKET_DECLARATION = (b'#ifndef LSF_SOCKET_FEATURE_PROBE_H\n#define LSF_SOCKET_FEATURE_PROBE_H\n'
                      b'#include <sys/socket.h>\n'
                      b'extern int socket(int, int, int) __asm__("__lsf_c_net_socket");\n#endif\n')
SOCKET_REFERENCE = (b'#include <netinet/in.h>\n#include <lsf/standard-streams.h>\n'
                    b'#ifndef socket\n#error captured socket mapping is missing\n#endif\n'
                    b'int lsf_socket_mapping(void) { return socket(AF_INET, SOCK_STREAM, 0); }\n'
                    b'#undef socket\n#include "socket-probe.h"\n'
                    b'int main(void) { return socket(AF_INET, SOCK_STREAM, 0) + lsf_socket_mapping(); }\n')


def socket_sources(files: dict[str, bytes]) -> dict[str, dict[str, str]]:
    return {name: {'path': path, 'digest': digest(files[path])} for name, path in (
        ('source', SOCKET_SOURCE), ('header', SOCKET_HEADER), ('wit', SOCKET_WIT))}


def prepare_socket(work: Path, workspace: Path, compiler: Compiler, output: Path,
                   files: dict[str, bytes], profile: str) -> dict:
    """Bind a link-only check to the actual selected source and captured WIT."""
    bindings = workspace / 'socket-bindings'
    bindings.mkdir()
    compiler.run('wit-bindgen', 'c', str(work / 'vendor/lsf/wit/platform/network'),
                 '--world', 'contract-probe', '--rename-world', 'probe', '--async=-all',
                 '--out-dir', str(bindings))
    if {path.name for path in bindings.iterdir()} != {'probe.c', 'probe.h', 'probe_component_type.o'}:
        raise ValueError('c-feature-probe-unexpected-socket-bindings')
    generated = read_file(bindings / 'probe.h', 256 * 1024)
    declaration = workspace / 'socket-probe.h'
    declaration.write_bytes(SOCKET_DECLARATION)
    reference = workspace / 'socket-reference.c'
    reference.write_bytes(SOCKET_REFERENCE)
    mapping = workspace / 'socket-mapping.c'
    mapping.write_bytes(b'#include <lsf/standard-streams.h>\n')
    source = work / SOCKET_SOURCE
    sdk = work / 'vendor/lsf/sdk/c-guest'
    flags = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
             '-D_POSIX_C_SOURCE=200809L', '-D_DEFAULT_SOURCE', '-DLSF_C_STREAM_NETWORK=1',
             '-matomics', '-mbulk-memory', '-pthread', '-fno-lto', '-I', str(bindings),
             '-I', str(sdk / 'include'), '-I', str(workspace)]
    if profile == standard_facilities.STREAM_STDIO_PROFILE:
        flags.append('-DLSF_C_STREAM_STDIO=1')
    for family in ('wasm-wasi-musl', 'generic-musl'):
        flags.extend(['-isystem', str(compiler.paths['zig'].parent / 'lib/libc/include' / family)])
    macros = compiler.run('zig', *flags, '-E', '-dM', str(mapping))
    if re.findall(r'^#define socket\s+(\S+)\s*$', macros, re.MULTILINE) != ['__lsf_c_net_socket']:
        raise ValueError('c-feature-probe-socket-mapping-invalid')
    observed = list(compiler.isolation.receipt.get('preprocessorInputs', []))
    for index, item in enumerate((source, reference, mapping)):
        depfile = workspace / f'socket-inputs-{index}.d'
        compiler.run('zig', *flags, '-M', '-MT', 'lsf-inputs', '-MF', str(depfile), str(item))
        observed.extend(compiler.isolation.observe_inputs(depfile))
    compiler.isolation.receipt['preprocessorInputs'] = sorted(
        {item['path']: item for item in observed}.values(), key=lambda item: item['path'])
    linked = workspace / 'socket-reference.wasm'
    compiler.run('zig', *flags, str(source), str(reference), '-o', str(linked))
    compiler.run('wasm-tools', 'validate', str(linked))
    (output / 'socket-bindings').mkdir()
    (output / 'socket-bindings/probe.h').write_bytes(generated)
    (output / 'socket-probe.h').write_bytes(SOCKET_DECLARATION)
    return {'sources': socket_sources(files), 'binding': {'digest': digest(generated), 'size': len(generated)},
            'declaration': {'digest': digest(SOCKET_DECLARATION), 'size': len(SOCKET_DECLARATION)},
            'generator': compiler.materials['wit-bindgen'], 'link': 'actual-sdk-source'}


def prepare(project_path: Path, output: Path, *, installed: dict[str, Path] | None = None) -> Path:
    safe_path(ROOT)
    project_path, output = safe_path(project_path), safe_path(output)
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / 'target' not in output.parents):
        raise ValueError('c-feature-probe-output-owner')
    files, dependency_root = build_inputs(project_path)
    project, _lock, pins = c_capsule_project.validate(files)
    profile = standard_facilities.selected_profile(project, guest_runtime_receipts.captured_graph(files))
    source_name = standard_facilities.SDK_SOURCE_PREFIX + standard_facilities.RESOLVER_SOURCE
    selected = profile in standard_facilities.STREAM_PROFILES and source_name in files
    socket_selected = profile in standard_facilities.STREAM_PROFILES
    output = fresh(output)
    recipe = recipe_identity()
    receipt = {'formatVersion': 2, 'profile': profile, 'sourceSnapshotDigest': digest(inventory(files)),
               'recipeDigest': recipe,
               'sdkLockDigest': digest(files['sdk-lock.json']), 'target': 'wasm32-wasi',
               'numericResolver': 'captured' if selected else 'not-selected',
               'source': {'path': source_name, 'digest': digest(files[source_name])} if selected else None,
               'object': None, 'socketProbe': None, 'compiler': None, 'compilerInputsDigest': None, 'authority': 'none',
               'configureExecuted': False, 'componentBuilt': False}
    with tempfile.TemporaryDirectory(prefix='lsf-c-features-') as owned:
        workspace = Path(owned)
        work = workspace / 'project'
        for name, data in files.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        commands = Commands(work, output, build_environment(workspace), deadline_seconds=180, command_seconds=90)
        compiler = Compiler(workspace / 'compiler', 180, sdk=work / 'vendor/lsf/sdk/c-guest',
                            platform=None, config=pins, commands=commands, installed=installed)
        compiler.enable_captured_isolation(workspace)
        if selected:
            source = work / source_name
            obj, depfile, wat = workspace / 'numeric-resolver.o', workspace / 'inputs.d', workspace / 'numeric-resolver.wat'
            flags = ('cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-D_POSIX_C_SOURCE=200809L', '-D_DEFAULT_SOURCE')
            compiler.run('zig', *flags, '-M', '-MT', 'lsf-inputs', '-MF', str(depfile), str(source))
            compiler.isolation.receipt['preprocessorInputs'] = compiler.isolation.observe_inputs(depfile)
            compiler.run('zig', *flags, '-c', str(source), '-o', str(obj))
            compiler.run('wasm-tools', 'validate', str(obj))
            compiler.run('wasm-tools', 'print', str(obj), '-o', str(wat))
            body = read_file(obj, 1024 * 1024)
            observed = wasm_object(body, include_all_symbols=True)
            imports = re.findall(r'\(import "([^"\n]+)" "([^"\n]+)" ', read_file(wat, 4 * 1024 * 1024).decode())
            allowed = {('env', '__linear_memory'), ('env', '__stack_pointer'), ('env', 'malloc'), ('env', 'free')}
            if (not resolver_interface(observed)
                    or set(imports) != allowed or len(imports) != len(allowed)):
                raise ValueError('c-feature-probe-unexpected-object-interface')
            (output / 'numeric-resolver.o').write_bytes(body)
            receipt['object'] = {'digest': digest(body), 'size': len(body), 'imports': sorted(map(list, allowed))}
        if socket_selected:
            receipt['socketProbe'] = prepare_socket(work, workspace, compiler, output, files, profile)
        compiler.check_unchanged()
        if build_inputs(project_path) != (files, dependency_root) or recipe_identity() != recipe:
            raise ValueError('c-feature-probe-project-changed')
        write_json(output / 'compiler-inputs.json', compiler.isolation.receipt)
        receipt['compiler'] = compiler.materials['zig']
        receipt['compilerInputsDigest'] = digest(read_file(output / 'compiler-inputs.json', 8 * 1024 * 1024))
    write_json(output / 'feature-probes.json', receipt)
    return output


def verify(project_path: Path, kit: Path, expected: str, zig: Path) -> str:
    safe_path(ROOT)
    project_path, kit, zig = safe_path(project_path), safe_path(kit), safe_path(zig)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected or ''):
        raise ValueError('c-feature-probe-expect-digest')
    raw = read_file(kit / 'feature-probes.json', 65536)
    if digest(raw) != expected:
        raise ValueError('c-feature-probe-receipt-changed')
    receipt = decode_json(raw)
    if not isinstance(receipt, dict) or set(receipt) != {
            'formatVersion', 'profile', 'sourceSnapshotDigest', 'recipeDigest', 'sdkLockDigest', 'target', 'numericResolver',
            'source', 'object', 'socketProbe', 'compiler', 'compilerInputsDigest', 'authority', 'configureExecuted',
            'componentBuilt'}:
        raise ValueError('c-feature-probe-receipt-invalid')
    files, _root = build_inputs(project_path)
    project, _lock, _pins = c_capsule_project.validate(files)
    profile = standard_facilities.selected_profile(project, guest_runtime_receipts.captured_graph(files))
    source_name = standard_facilities.SDK_SOURCE_PREFIX + standard_facilities.RESOLVER_SOURCE
    selected = profile in standard_facilities.STREAM_PROFILES and source_name in files
    socket_selected = profile in standard_facilities.STREAM_PROFILES
    expected_source = {'path': source_name, 'digest': digest(files[source_name])} if selected else None
    if (receipt['formatVersion'] != 2 or receipt['profile'] != profile
            or receipt['sourceSnapshotDigest'] != digest(inventory(files)) or receipt['recipeDigest'] != recipe_identity()
            or receipt['sdkLockDigest'] != digest(files['sdk-lock.json'])
            or receipt['target'] != 'wasm32-wasi' or receipt['source'] != expected_source
            or receipt['numericResolver'] != ('captured' if selected else 'not-selected')
            or receipt['authority'] != 'none' or receipt['configureExecuted'] is not False
            or receipt['componentBuilt'] is not False):
        raise ValueError('c-feature-probe-captured-input-changed')
    entries = list(kit.iterdir())
    expected_names = {'feature-probes.json', 'compiler-inputs.json', 'logs'}
    if selected:
        expected_names.add('numeric-resolver.o')
    if socket_selected:
        expected_names.update(('socket-bindings', 'socket-probe.h'))
    if ({entry.name for entry in entries} != expected_names or any(entry.is_symlink() for entry in entries)
            or not (kit / 'logs').is_dir()):
        raise ValueError('c-feature-probe-unexpected-input')
    obj = receipt['object']
    if selected:
        if not isinstance(obj, dict) or set(obj) != {'digest', 'size', 'imports'}:
            raise ValueError('c-feature-probe-object-invalid')
        body = read_file(kit / 'numeric-resolver.o', 1024 * 1024)
        allowed = sorted(map(list, {('env', '__linear_memory'), ('env', '__stack_pointer'),
                                    ('env', 'malloc'), ('env', 'free')}))
        if obj['digest'] != digest(body) or obj['size'] != len(body) or obj['imports'] != allowed:
            raise ValueError('c-feature-probe-object-changed')
        observed = wasm_object(body, include_all_symbols=True)
        if not resolver_interface(observed):
            raise ValueError('c-feature-probe-unexpected-object-interface')
    elif obj is not None:
        raise ValueError('c-feature-probe-unexpected-object')
    socket = receipt['socketProbe']
    if socket_selected:
        if (not isinstance(socket, dict) or set(socket) != {'sources', 'binding', 'declaration', 'generator', 'link'}
                or socket['sources'] != socket_sources(files) or socket['link'] != 'actual-sdk-source'):
            raise ValueError('c-feature-probe-socket-invalid')
        bindings = kit / 'socket-bindings'
        if bindings.is_symlink() or not bindings.is_dir() or {item.name for item in bindings.iterdir()} != {'probe.h'}:
            raise ValueError('c-feature-probe-socket-bindings-invalid')
        generated = read_file(bindings / 'probe.h', 256 * 1024)
        declaration = read_file(kit / 'socket-probe.h', 4096)
        if (socket['binding'] != {'digest': digest(generated), 'size': len(generated)}
                or declaration != SOCKET_DECLARATION
                or socket['declaration'] != {'digest': digest(declaration), 'size': len(declaration)}):
            raise ValueError('c-feature-probe-socket-bindings-changed')
    elif socket is not None:
        raise ValueError('c-feature-probe-unexpected-socket')
    inputs = read_file(kit / 'compiler-inputs.json', 8 * 1024 * 1024)
    if digest(inputs) != receipt['compilerInputsDigest']:
        raise ValueError('c-feature-probe-compiler-inputs-changed')
    evidence = decode_json(inputs)
    if (receipt['compiler'] != evidence['tools']['zig'] or
            (socket_selected and socket['generator'] != evidence['tools']['wit-bindgen']) or
            file_identity(zig, 'zig') != receipt['compiler'] or
            Isolation.observe_distribution(zig.parent) != evidence['distributions']['zig-compiler-and-sysroot']):
        raise ValueError('c-feature-probe-compiler-changed')
    return obj['digest'] if obj else 'not-selected'
