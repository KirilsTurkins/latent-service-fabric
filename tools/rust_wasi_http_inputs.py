"""Build and recheck the explicit standard-WASI adapter, without granting it."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import re
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_wasi_http_profile as profile
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.dotnet_guest import composer
from tools.dotnet_guest.internal_io import core_modules
from tools.rust_capsule_project import (
    ROOT, canonical, checked_path, decode_json, digest, fresh, inventory,
    read_file, read_json, snapshot, write_json,
)
from tools.rust_standard_clock_profile import RUST, RUST_COMMIT, TARGET

SCHEMA = 'latent.rust.wasi-http.prepared-adapter.v1'
EXAMPLE = 'rust-wasi-http-runtime'
RECEIPT = 'INSTALL-COMPLETE.json'
ADAPTER = 'rust-wasi-http-runtime.wasm'
MAX_BINARY = 64 * 1024 * 1024
MAX_SOURCE = 4 * 1024 * 1024
# The pinned CLI can report its exact upstream build suffix, as the hosted
# installation does. A matching version prefix with another suffix is refused.
WASM_REPORTS = (b'wasm-tools 1.254.0', b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20)')
FILES = (ADAPTER, 'raw-runtime.wasm', 'reference.wit.json', 'adapter.wit.json')
SHARED = tuple('sdk/dotnet-guest/runtime/http/' + name + '.rs'
    for name in ('owner', 'pump', 'quota', 'timer'))
RECIPE = (
    'tools/rust_wasi_http_inputs.py', 'tools/rust_wasi_http_profile.py',
    'tools/dotnet_guest/internal_io.py',
    'tools/dotnet_guest/composer.py', 'sdk/dotnet-guest/component-composer.json',
    'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'tools/toolchain.toml',
    'tools/toolchain-smoke/Cargo.toml',
    'tools/toolchain-smoke/examples/rust_wasi_http_runtime.rs',
    '.cargo/config.toml', '.cargo/managed-guest.toml',
    'tools/rust_standard_clock_profile.py',
)

CONSUMER_RECIPE = ('tools/rust_wasi_http_root.py', 'tools/rust_wasi_http_io.py',
    'tools/rust_wasi_http_compose.py')


def require(condition, reason):
    if not condition:
        raise ValueError('rust-http-' + reason)


def source_files(root=ROOT) -> dict[str, bytes]:
    """Actual adapter producer/validator closure and original shared ownership.

    Consumer-only forwarding/projection/composition sources are bound separately
    by consumer_files; changes there cannot relabel an existing adapter build.
    """
    from tools.rust_capsule_build import RECIPE as build_helpers
    root = checked_path(root)
    profile.validate_assets(root)
    files = {'sdk/wasi-http-runtime/' + name: body
        for name, body in snapshot(root / 'sdk/wasi-http-runtime').items()}
    require(1 <= len(files) <= 128, 'runtime-source-file-bound')
    for name in dict.fromkeys((*RECIPE, *SHARED, *build_helpers)):
        files[name] = read_file(root / name, MAX_SOURCE)
    require(len(files) <= 256 and sum(map(len, files.values())) <= MAX_SOURCE,
        'runtime-recipe-bound')
    manifest = tomllib.loads(files['tools/toolchain-smoke/Cargo.toml'].decode())
    examples = [row for row in manifest.get('example', []) if row.get('name') == EXAMPLE]
    require(examples == [{'name': EXAMPLE, 'path': 'examples/rust_wasi_http_runtime.rs',
        'crate-type': ['cdylib'], 'test': False, 'bench': False, 'doc': False}],
        'exact-runtime-cargo-example')
    return files


def consumer_files(root=ROOT) -> dict[str, bytes]:
    """Complete explicit guest recipe, retaining separate producer provenance."""
    files = source_files(root)
    for name in CONSUMER_RECIPE:
        files[name] = read_file(checked_path(root) / name, MAX_SOURCE)
    require(len(files) <= 256 and sum(map(len, files.values())) <= MAX_SOURCE,
        'consumer-recipe-bound')
    return files


def _identity(path, name, maximum=MAX_BINARY):
    return file_identity(checked_path(path), name, maximum)


def _shape_identity(value, name):
    return (isinstance(value, dict) and set(value) == {'name', 'digest', 'size'}
        and value['name'] == name and isinstance(value['digest'], str)
        and re.fullmatch(r'sha256:[0-9a-f]{64}', value['digest']) is not None
        and type(value['size']) is int and 0 < value['size'] <= 256 * 1024 * 1024)


def _bounded_record(value):
    required = {'schemaVersion', 'profile', 'target', 'rust', 'rustCommit', 'wasmTools',
        'sourceDigest', 'sourceRows', 'tools', 'files', 'composerSelection',
        'graphValidation', 'cores', 'commands', 'qualification', 'authority',
        'signedQualification', 'publisherAuthentication', 'hermetic', 'identity'}
    require(isinstance(value, dict) and set(value) == required, 'prepared-receipt-fields')
    require(value['schemaVersion'] == SCHEMA and value['profile'] == profile.PROFILE
        and value['target'] == TARGET and value['rust'] == RUST
        and value['rustCommit'] == RUST_COMMIT and value['wasmTools'] == '1.254.0'
        and value['qualification'] == 'compiled-adapter-only'
        and value['authority'] == 'none'
        and value['signedQualification'] is False
        and value['publisherAuthentication'] is False and value['hermetic'] is False,
        'prepared-profile')
    require(value['identity'] == digest(canonical({k: v for k, v in value.items()
        if k != 'identity'})), 'prepared-receipt-identity')
    require(isinstance(value['tools'], dict)
        and set(value['tools']) == {'rustc', 'cargo', 'wasm-tools', 'component-composer'}
        and all(_shape_identity(row, name) for name, row in value['tools'].items()),
        'prepared-tool-record')
    require(isinstance(value['files'], dict) and set(value['files']) == set(FILES)
        and all(_shape_identity(row, name) and row['size'] <= MAX_BINARY
            for name, row in value['files'].items()), 'prepared-file-record')
    require(isinstance(value['cores'], list) and 1 <= len(value['cores']) <= 8
        and all(isinstance(row, dict) and set(row) == {'digest', 'size'}
            and type(row['size']) is int and 0 < row['size'] <= MAX_BINARY
            and isinstance(row['digest'], str)
            and re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest'])
            for row in value['cores']), 'prepared-core-record')
    expected_stages = ('runtime-rustc-version', 'runtime-cargo-version',
        'runtime-wasm-tools-version', 'component-composer-version',
        'standard-http-runtime-compile', 'standard-http-runtime-component',
        'standard-http-runtime-validate', 'standard-http-reference-wit',
        'standard-http-adapter-wit')
    require(isinstance(value['commands'], list)
        and all(isinstance(row, dict) for row in value['commands'])
        and tuple(row.get('stage') for row in value['commands']) == expected_stages
        and all(set(row) == {'stage', 'exitCode', 'seconds'} and row['exitCode'] == 0
            and type(row['exitCode']) is int and type(row['seconds']) in (int, float)
            and 0 <= row['seconds'] <= 900 for row in value['commands']),
        'prepared-command-receipt')


class Prepared:
    def __init__(self, directory: Path, rustc: Path, wasm_tools: Path):
        self.path = checked_path(directory)
        require(self.path.is_dir() and not (self.path / 'INSTALL-FAILED.json').exists()
            and not (self.path / 'INSTALL-FAILED.json').is_symlink(),
            'prepared-directory')
        self.rustc, self.wasm_tools = checked_path(rustc), checked_path(wasm_tools)
        self.raw = read_file(self.path / RECEIPT, 1024 * 1024)
        value = decode_json(self.raw)
        _bounded_record(value)
        source = inventory(source_files())
        require(read_file(self.path / 'source-inputs.json', MAX_SOURCE) == source
            and value['sourceDigest'] == digest(source)
            and type(value['sourceRows']) is int
            and value['sourceRows'] == len(decode_json(source)), 'prepared-source-drift')
        for name, path in (('rustc', self.rustc), ('wasm-tools', self.wasm_tools)):
            require(value['tools'][name] == _identity(path, name, 256 * 1024 * 1024),
                'prepared-tool-drift:' + name)
        self.composer = composer.observed(self.path, ROOT / 'sdk/dotnet-guest')
        require(value['composerSelection'] == composer.selection(ROOT / 'sdk/dotnet-guest')
            and value['tools']['component-composer'] == _identity(self.composer,
                'component-composer', composer.SIZE), 'prepared-composer-drift')
        for name, row in value['files'].items():
            require(row == _identity(self.path / name, name), 'prepared-file-drift:' + name)
        self.adapter = self.path / ADAPTER
        reference = read_json(self.path / 'reference.wit.json', 16 * 1024 * 1024)
        actual = read_json(self.path / 'adapter.wit.json', 16 * 1024 * 1024)
        require(value['graphValidation'] == profile.validate_adapter(reference, actual),
            'prepared-adapter-graph')
        cores = core_modules(read_file(self.adapter, MAX_BINARY))
        require(value['cores'] == [{'digest': digest(body), 'size': len(body)} for body in cores],
            'prepared-core-drift')
        profile.verify_compiled_core(read_file(self.path / 'raw-runtime.wasm', MAX_BINARY), cores)
        self.value = value

    def check(self):
        current = Prepared(self.path, self.rustc, self.wasm_tools)
        require(current.raw == self.raw, 'prepared-receipt-mutated')

    def material(self) -> bytes:
        self.check()
        return self.raw


def _versions(commands, tools):
    raw = commands.run('runtime-rustc-version', tools['rustc'], '--version', '--verbose')
    lines = raw.decode().splitlines()
    require(lines and re.fullmatch(r'rustc 1\.97\.1 \(' + RUST_COMMIT[:9]
        + r' [0-9]{4}-[0-9]{2}-[0-9]{2}\)', lines[0]), 'compiler-version-header')
    pairs = [line.split(': ', 1) for line in lines[1:] if ': ' in line]
    rows = dict(pairs)
    require(len(rows) == len(pairs), 'compiler-duplicate-version-field')
    require(rows.get('release') == RUST and rows.get('commit-hash') == RUST_COMMIT
        and rows.get('host') == 'x86_64-unknown-linux-gnu', 'compiler-version')
    cargo = commands.run('runtime-cargo-version', tools['cargo'], '--version').strip()
    require(re.fullmatch(rb'cargo 1\.97\.1(?: \([0-9a-f]{7,40} [0-9]{4}-[0-9]{2}-[0-9]{2}\))?', cargo),
        'cargo-version')
    wasm = commands.run('runtime-wasm-tools-version', tools['wasm-tools'], '--version').strip()
    require(wasm in WASM_REPORTS, 'wasm-tools-version')


def install(directory: Path):
    # Refuse before creating output, running tools, or fetching a composer.
    require(sys.platform == 'linux' and platform.machine() in {'x86_64', 'AMD64'},
        'installer-linux-x86-64-only')
    require(Path(directory).is_absolute(), 'installer-absolute-owned-output')
    from tools.rust_capsule_build import Commands
    directory = fresh(directory)
    environment = build_environment(directory)
    environment.update(CARGO_NET_OFFLINE='true', CARGO_INCREMENTAL='0',
        CARGO_PROFILE_RELEASE_DEBUG='0', RUSTUP_AUTO_INSTALL='0', RUSTUP_TOOLCHAIN=RUST)
    commands = Commands(ROOT, directory, environment, deadline_seconds=900, command_seconds=600)
    stage = 'source-capture'
    try:
        before = source_files()
        source = inventory(before)
        (directory / 'source-inputs.json').write_bytes(source)
        toolchain = tomllib.loads(before['tools/toolchain.toml'].decode())
        tools, _ = resolve_tools(toolchain, ROOT, environment)
        tools_before = {name: _identity(path, name, 256 * 1024 * 1024)
            for name, path in tools.items()}
        stage = 'tool-versions'
        _versions(commands, tools)
        environment['RUSTC'] = str(tools['rustc'])
        stage = 'composer-install'
        wac = composer.install(directory, ROOT / 'sdk/dotnet-guest', commands)
        tools_before['component-composer'] = _identity(wac, 'component-composer', composer.SIZE)
        target = directory / 'target'
        stage = 'runtime-compile'
        commands.run('standard-http-runtime-compile', tools['cargo'], 'build', '--quiet',
            '--locked', '--offline', '--manifest-path', ROOT / 'tools/toolchain-smoke/Cargo.toml',
            '-p', 'latent-toolchain-smoke', '--example', EXAMPLE,
            '--target', TARGET, '--release', '--target-dir', target)
        raw = read_file(target / TARGET / 'release/examples' / (EXAMPLE.replace('-', '_') + '.wasm'), MAX_BINARY)
        require(raw.startswith(b'\0asm\x01\0\0\0'), 'compiled-core-header')
        (directory / 'raw-runtime.wasm').write_bytes(raw)
        stage = 'componentization'
        commands.run('standard-http-runtime-component', tools['wasm-tools'], 'component', 'new',
            directory / 'raw-runtime.wasm', '-o', directory / ADAPTER)
        commands.run('standard-http-runtime-validate', tools['wasm-tools'], 'validate',
            '--features', 'all', directory / ADAPTER)
        reference = commands.run('standard-http-reference-wit', tools['wasm-tools'], 'component',
            'wit', ROOT / 'sdk/wasi-http-runtime/wit', '--json')
        actual = commands.run('standard-http-adapter-wit', tools['wasm-tools'], 'component',
            'wit', directory / ADAPTER, '--json')
        (directory / 'reference.wit.json').write_bytes(reference)
        (directory / 'adapter.wit.json').write_bytes(actual)
        stage = 'final-verification'
        graph = profile.validate_adapter(decode_json(reference), decode_json(actual))
        cores = core_modules(read_file(directory / ADAPTER, MAX_BINARY))
        profile.verify_compiled_core(raw, cores)
        require(before == source_files(), 'runtime-source-changed')
        require(all(row == _identity(tools[name] if name in tools else wac, name,
            256 * 1024 * 1024) for name, row in tools_before.items()), 'runtime-tools-changed')
        require(time.monotonic() < commands.deadline, 'installer-original-deadline')
        record = {'schemaVersion': SCHEMA, 'profile': profile.PROFILE, 'target': TARGET,
            'rust': RUST, 'rustCommit': RUST_COMMIT, 'wasmTools': '1.254.0',
            'sourceDigest': digest(source), 'sourceRows': len(decode_json(source)),
            'tools': tools_before, 'files': {name: _identity(directory / name, name) for name in FILES},
            'composerSelection': composer.selection(ROOT / 'sdk/dotnet-guest'),
            'graphValidation': graph, 'cores': [{'digest': digest(body), 'size': len(body)} for body in cores],
            'commands': commands.records, 'qualification': 'compiled-adapter-only',
            'authority': 'none', 'signedQualification': False, 'publisherAuthentication': False,
            'hermetic': False}
        record['identity'] = digest(canonical(record))
        write_json(directory / RECEIPT, record)
        Prepared(directory, tools['rustc'], tools['wasm-tools']).check()
        require(time.monotonic() < commands.deadline, 'installer-original-deadline')
        return directory
    except BaseException as error:
        try:
            write_json(directory / 'INSTALL-FAILED.json', {'schemaVersion': SCHEMA,
                'status': 'failed', 'stage': stage, 'reasonType': type(error).__name__,
                'commands': commands.records, 'signedQualification': False})
        except OSError:
            pass  # Keep the original failure if diagnostic storage is unavailable.
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    install(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
