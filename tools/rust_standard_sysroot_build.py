"""Build an owned clock-only std sysroot from the authenticated upstream closure.

This explicit infrastructure build never changes an installed compiler, selects
an application runtime, or establishes thread/default-executor qualification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_standard_clock_profile as clock
from tools import rust_standard_sysroot_source as source
from tools.build_observation import build_environment, file_identity
from tools.captured_compiler_isolation import distribution
from tools.dev_workflow.common import encode, require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, decode_json, digest, fresh, inventory, read_file, write_json

ROOT = source.ROOT
PROFILE = 'lsf-rust-std-clock-built-source-v1'
FLAGS = '-Cpanic=abort -Cembed-bitcode=yes -Zforce-unstable-if-unmarked'
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
RECIPE = ('tools/rust_standard_sysroot_build.py', *source.RECIPE,
          'tools/rust_capsule_build.py', 'tools/build_observation.py',
          'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py',
          'tools/captured_compiler_isolation.py')


def emitted_libraries(data: bytes, target: Path) -> dict[str, dict]:
    """Select this successful Cargo graph, never glob a cache containing older builds."""
    require(len(data) <= 4 * 1024 * 1024, 'rust-sysroot-artifact-document-bound')
    target = checked_path(target)
    result = {}; crates = set(); successful = False
    lines = data.splitlines()
    require(len(lines) <= 8192, 'rust-sysroot-artifact-record-bound')
    for raw in lines:
        item = decode_json(raw)
        require(isinstance(item, dict), 'rust-sysroot-artifact-record')
        require(not successful, 'rust-sysroot-artifact-after-terminal')
        if item.get('reason') == 'build-finished':
            require(not successful and item.get('success') is True, 'rust-sysroot-build-not-successful')
            successful = True
        if item.get('reason') != 'compiler-artifact': continue
        require(isinstance(item.get('filenames'), list) and len(item['filenames']) <= 16,
                'rust-sysroot-artifact-filename-bound')
        for name in item['filenames']:
            require(isinstance(name, str) and len(name) <= 4096, 'rust-sysroot-artifact-filename')
            path = Path(name)
            if path.suffix != '.rlib': continue
            require(path.is_absolute() and path.is_relative_to(target) and '..' not in path.parts,
                    'rust-sysroot-artifact-outside-target')
            relative = path.relative_to(target)
            if not relative.parts or relative.parts[0] != clock.TARGET: continue
            require(re.fullmatch(r'lib[A-Za-z0-9_-]{1,200}\.rlib', path.name) is not None,
                    'rust-sysroot-artifact-library-name')
            crate = item.get('target', {}).get('name')
            package = item.get('package_id')
            require(isinstance(crate, str) and isinstance(package, str) and len(package) <= 4096,
                    'rust-sysroot-artifact-package')
            require(crate not in crates and path.name not in result and len(result) < 64,
                    'rust-sysroot-artifact-ambiguous-library')
            path = checked_path(path)
            require(path.is_relative_to(target), 'rust-sysroot-artifact-outside-target')
            value = read_file(path, MAX_ARTIFACT_BYTES)
            result[path.name] = {'source': path, 'bytes': value, 'crate': crate, 'package': package}
            crates.add(crate)
    require(successful and {'std', 'core', 'alloc', 'panic_abort', 'compiler_builtins'} <= crates,
            'rust-sysroot-artifact-incomplete-graph')
    require(sum(len(r['bytes']) for r in result.values()) <= 128 * 1024 * 1024,
            'rust-sysroot-artifact-total-bound')
    return result


def build(archive: Path, output: Path, rust_bin: Path):
    archive, rust_bin = checked_path(archive), checked_path(rust_bin)
    original, modes = source.library(archive)
    inputs = {n: read_file(ROOT / n) for n in dict.fromkeys(RECIPE)}
    selected = dict(original)
    selected.update(clock.overlay({n: original[n] for n in clock.ORIGINALS},
                                  inputs['sdk/rust-standard-runtime/clock.rs']))
    output = fresh(output)
    try:
        with tempfile.TemporaryDirectory(prefix='lsf-rust-clock-std-') as directory:
            work = Path(directory)
            library, target = work / 'library', work / 'target'
            for name, raw in selected.items():
                path = library / name; path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream: stream.write(raw)
                path.chmod(modes.get(name, 0o644))
            tools = {name: checked_path(rust_bin / name) for name in ('cargo', 'rustc')}
            environment = build_environment(work)
            environment.update(HOME=str(work / 'home'), CARGO_HOME=str(work / 'cargo-home'),
                CARGO_NET_OFFLINE='true', RUSTUP_AUTO_INSTALL='0', RUSTC=str(tools['rustc']),
                CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0', RUSTC_BOOTSTRAP='1',
                RUSTFLAGS=FLAGS)
            commands = Commands(library, output, environment, deadline_seconds=600, command_seconds=180)
            version = commands.run('compiler-version', tools['rustc'], '--version', '--verbose').decode()
            require(f'release: {clock.RUST}\n' in version and f'commit-hash: {clock.RUST_COMMIT}\n' in version,
                    'rust-sysroot-build-compiler-pin')
            compiler = distribution(rust_bin.parent)
            argv = ['build', '--locked', '--offline', '--package', 'std', '--target', clock.TARGET,
                    '--release', '--features', 'compiler-builtins-mem', '--message-format=json']
            raw = commands.run('sysroot-build', tools['cargo'], *argv)
            artifacts = emitted_libraries(raw, target)
            destination = output / 'sysroot/lib/rustlib' / clock.TARGET / 'lib'
            destination.mkdir(parents=True)
            for name, record in artifacts.items():
                with (destination / name).open('xb') as stream: stream.write(record['bytes'])
            require({n: read_file(ROOT / n) for n in inputs} == inputs, 'rust-sysroot-build-recipe-mutated')
            require(source.library(archive) == (original, modes), 'rust-sysroot-build-source-mutated')
            require(distribution(rust_bin.parent) == compiler, 'rust-sysroot-build-compiler-mutated')
            require({n: read_file(library / n, source.MAX_FILE_BYTES) for n in selected} == selected,
                    'rust-sysroot-build-selected-source-mutated')
            value = {'schemaVersion': 'latent.rust.std-built-source.v1', 'profile': PROFILE,
                'target': clock.TARGET, 'rust': clock.RUST, 'rustCommit': clock.RUST_COMMIT,
                'archiveDigest': 'sha256:' + clock.SOURCE_ARCHIVE_SHA256,
                'originalInputsDigest': digest(inventory(original)), 'selectedInputsDigest': digest(inventory(selected)),
                'recipeDigest': digest(inventory(inputs)), 'compilerDistributionDigest': digest(encode(compiler)),
                'tools': {n: file_identity(p, n) for n, p in tools.items()},
                'command': argv, 'rustFlags': FLAGS, 'commands': commands.records,
                'libraries': {n: {'digest': digest(r['bytes']), 'size': len(r['bytes']),
                                  'crate': r['crate'], 'package': r['package']}
                              for n, r in artifacts.items()},
                'networkResolution': 'disabled; official archive contains the locked vendor closure',
                'credentials': 'not-inherited', 'filesystemIsolation': 'not-performed',
                'installedCompilerChanged': False, 'automaticBuilderSelection': False,
                'qualification': 'built-source-only', 'standardThreadApiImplemented': False,
                'remainingGates': ['isolated tool trust and immutable distribution provisioning',
                    'ordinary signed guest clock qualification and default builder integration',
                    'logical thread/TLS/sync/timer/default-reactor/checkpoint and native retirement qualification']}
            value['identity'] = digest(encode(value))
            write_json(output / 'std-sysroot-build.json', value)
            return value
    except Exception:
        write_json(output / 'BUILD-FAILED.json', {'profile': PROFILE, 'status': 'failed',
            'successfulSysrootClaimed': False, 'logs': 'retained if the compiler was invoked'})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build(args.source_archive, args.output, args.rust_bin)
        print(json.dumps({'profile': value['profile'], 'identity': value['identity'],
                          'libraries': len(value['libraries']), 'qualification': value['qualification']}))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Rust std infrastructure build failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
