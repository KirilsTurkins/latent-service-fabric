"""Run the real C adapter against explicit finite stream-provider doubles."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, file_identity
from tools.c_guest import standard_facilities
from tools.dev_workflow.common import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCES = (
    'sdk/c-guest/src/standard-streams.c', 'sdk/c-guest/include/lsf/standard-streams.h',
    'wit/platform/network/package.wit', 'tools/tests/fixtures/c-stream-source-errno.h',
    'tools/tests/fixtures/c-stream-descriptor-source.c', 'tools/tests/fixtures/c-stream-descriptor-source.cjs',
    'tools/c_stream_source_controls.py', 'sdk/c-guest/src/trap.c', 'tools/c_guest/standard_facilities.py',
    'tools/tests/fixtures/c-stream-abort-link.c', 'tools/tests/fixtures/c-stream-abort-link.cjs',
)


def run(output: Path, zig: Path, wit: Path, node: Path) -> dict:
    output = fresh(output)
    inputs = {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
    tools = {name: file_identity(path, name) for name, path in (('zig', zig), ('wit-bindgen', wit), ('node', node))}
    environment = build_environment(output)
    environment.update(ZIG_GLOBAL_CACHE_DIR=str(output / 'zig-global'), ZIG_LOCAL_CACHE_DIR=str(output / 'zig-local'))
    commands = Commands(ROOT, output, environment, deadline_seconds=120, command_seconds=60)
    result = {'status': 'failed', 'source': inputs, 'tools': tools, 'realProvider': False,
              'signedComponent': False, 'libcErrnoGetterTested': False}
    try:
        require(commands.run('zig-version', zig, 'version').strip() == b'0.16.0', 'c-stream-source-zig-version')
        require(commands.run('wit-version', wit, '--version').strip() == b'wit-bindgen-cli 0.62.0',
                'c-stream-source-wit-version')
        generated = output / 'bindings'
        generated.mkdir()
        commands.run('bindings', wit, 'c', ROOT / 'wit/platform/network', '--world', 'contract-probe',
                     '--rename-world', 'probe', '--async=-all', '--out-dir', generated)
        args = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-D_POSIX_C_SOURCE=200809L',
                '-Wall', '-Wextra', '-Werror', '-fno-builtin', '-nostdlib', '-Wl,--no-entry',
                '-Wl,--export-memory']
        for family in ('wasm-wasi-musl', 'generic-musl'):
            args += ['-isystem', zig.parent / 'lib/libc/include' / family]
        args += ['-I', generated, '-I', ROOT / 'sdk/c-guest/include', '-include', ROOT / SOURCES[3],
                 ROOT / SOURCES[0], ROOT / SOURCES[4], '-o', output / 'controls.wasm']
        commands.run('compile', zig, *args)
        observed = commands.run('controls', node, ROOT / SOURCES[5], output / 'controls.wasm')
        require(observed == b'PASS descriptor_controls\nPASS readiness_controls\n', 'c-stream-source-exact-outcome')
        link_args = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-mexec-model=reactor', '-Wl,--no-entry', '-Wl,--export-memory', '-matomics',
                     '-mbulk-memory', '-pthread', '-fno-lto', '-D_DEFAULT_SOURCE',
                     *('-D' + value for value in standard_facilities.compiler_defines(
                         standard_facilities.STREAM_PROFILE, ())), ROOT / SOURCES[9], ROOT / SOURCES[7],
                     '-o', output / 'abort-link.wasm']
        commands.run('libc-abort-link', zig, *link_args)
        aborts = commands.run('libc-abort-controls', node, ROOT / SOURCES[10], output / 'abort-link.wasm')
        require(aborts == b'PASS libc-entropy\nPASS application_abort\nPASS original_libc_abort\n',
                'c-stream-source-abort-exact-outcome')
        require(inputs == {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
                and tools == {name: file_identity(path, name) for name, path in (('zig', zig), ('wit-bindgen', wit), ('node', node))},
                'c-stream-source-input-changed')
        result.update(status='passed', commands=commands.records,
                      cases=['descriptor_controls', 'readiness_controls', 'libc-entropy',
                             'application_abort', 'original_libc_abort'])
        write_json(output / 'source-controls.json', result)
        return result
    except BaseException:
        result['commands'] = commands.records
        write_json(output / 'FAILED.json', result)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--zig', required=True, type=Path)
    parser.add_argument('--wit-bindgen', required=True, type=Path)
    parser.add_argument('--node', required=True, type=Path)
    options = parser.parse_args()
    print(run(options.output, options.zig, options.wit_bindgen, options.node)['status'])
