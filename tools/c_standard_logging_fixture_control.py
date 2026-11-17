"""Execute the current signed C logging fixture against the real stdio adapter.

This source control uses finite log/libc doubles; it is not a signed node or
real-provider qualification and does not invoke the pinned libc errno getter.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, file_identity
from tools.c_standard_logging_probe import LIBRARY
from tools.dev_workflow.common import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCES = (
    'sdk/c-guest/src/standard-stdio.c', 'tools/c_standard_logging_probe.py',
    'tools/tests/fixtures/c-standard-logging-mode-control.c',
    'tools/tests/fixtures/c-standard-logging-mode-control.cjs',
    'tools/tests/fixtures/c-stream-source-errno.h', 'wit/platform/log/package.wit',
    'tools/c_standard_logging_fixture_control.py',
)


def run(output: Path, zig: Path, wit: Path, node: Path) -> dict:
    output = fresh(output)
    inputs = {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
    tools = {name: file_identity(path, name) for name, path in
             (('zig', zig), ('wit-bindgen', wit), ('node', node))}
    environment = build_environment(output)
    environment.update(ZIG_GLOBAL_CACHE_DIR=str(output / 'zig-global'),
                       ZIG_LOCAL_CACHE_DIR=str(output / 'zig-local'))
    commands = Commands(ROOT, output, environment, deadline_seconds=120, command_seconds=60)
    result = {'status': 'failed', 'source': inputs, 'tools': tools, 'realProvider': False,
              'signedComponent': False, 'libcErrnoGetterTested': False}
    try:
        require(commands.run('zig-version', zig, 'version').strip() == b'0.16.0',
                'c-logging-fixture-zig-version')
        require(commands.run('wit-version', wit, '--version').strip() == b'wit-bindgen-cli 0.62.0',
                'c-logging-fixture-wit-version')
        world = output / 'wit'; dependency = world / 'deps/log'
        dependency.mkdir(parents=True)
        (world / 'world.wit').write_text(
            'package tests:control@1.0.0; world service { import latent:log/log@0.1.0; }\n', encoding='utf-8')
        (dependency / 'package.wit').write_bytes((ROOT / SOURCES[5]).read_bytes())
        bindings = output / 'bindings'; bindings.mkdir()
        commands.run('bindings', wit, 'c', world, '--world', 'service', '--rename-world', 'probe',
                     '--async=-all', '--out-dir', bindings)
        (output / 'log_probe.c').write_text(LIBRARY, encoding='utf-8')
        (output / 'log_probe.h').write_text('int standard_log_probe(unsigned mode);\n', encoding='utf-8')
        arguments = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-fno-builtin', '-nostdlib', '-Wl,--no-entry', '-Wl,--export-memory',
                     '-Wl,--export=__wasm_call_ctors']
        for family in ('wasm-wasi-musl', 'generic-musl'):
            arguments += ['-isystem', zig.parent / 'lib/libc/include' / family]
        arguments += ['-I', bindings, '-I', output, '-include', ROOT / SOURCES[4], ROOT / SOURCES[0],
                      output / 'log_probe.c', ROOT / SOURCES[2], '-o', output / 'control.wasm']
        commands.run('compile', zig, *arguments)
        observed = commands.run('execute', node, ROOT / SOURCES[3], output / 'control.wasm')
        require(observed == b'PASS signed logging short-write fixture\n', 'c-logging-fixture-exact-outcome')
        require(inputs == {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
                and tools == {name: file_identity(path, name) for name, path in
                              (('zig', zig), ('wit-bindgen', wit), ('node', node))},
                'c-logging-fixture-input-changed')
        result.update(status='passed', commands=commands.records, cases=['signed-short-write-mode'])
        write_json(output / 'control.json', result)
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
