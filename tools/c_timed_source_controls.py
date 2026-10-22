"""Bounded real-C broadcast interleaving with explicit serialized host doubles."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.c_guest import threading
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools.build_observation import build_environment, file_identity
from tools.dev_workflow.common import require

SOURCES = ('tools/c_timed_source_controls.py', 'tools/tests/fixtures/c-timed-broadcast-source.c',
    'tools/tests/fixtures/c-timed-broadcast-source.cjs', 'sdk/c-guest/runtime/thread-abi.h',
    'sdk/c-guest/runtime/synchronization.c', 'tools/c_guest/threading.py',
    'tools/build_observation.py', 'tools/rust_capsule_build.py')


def run(output, zig, node):
    output = fresh(output)
    inputs = {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
    tools = {name: file_identity(path, name) for name, path in (('zig', zig), ('node', node))}
    record = {'status': 'failed', 'source': inputs, 'tools': tools,
        'actualGuestExecuted': False, 'signedQualification': False,
        'canonicalAndBrokerPorts': 'explicit-serialized-doubles', 'originalLedgerExecuted': False}
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=120, command_seconds=60)
    try:
        require(commands.run('zig-version', zig, 'version').strip() == b'0.16.0', 'c-timed-source-zig-version')
        # Authenticate the same original public ABI and nine time inputs.
        headers = {**threading.libc_inputs(zig), **threading.clock_libc_inputs(zig)}
        record['publicHeaders'] = {name: file_identity(path, name, 32768) for name, path in headers.items()}
        args = ['cc', '-std=c17', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
            '-matomics', '-mbulk-memory', '-pthread', '-nostdlib', '-fno-builtin', '-Wl,--no-entry',
            '-Wl,--export-memory', '-I', ROOT / 'sdk/c-guest/runtime']
        for family in ('wasm-wasi-musl', 'generic-musl'):
            args += ['-isystem', zig.parent / 'lib/libc/include' / family]
        args += ['-D' + define for define in threading.linked_defines((), timed_clock=True)]
        args += [ROOT / SOURCES[1], '-o', output / 'broadcast.wasm']
        commands.run('compile-real-source-control', zig, *args)
        result = commands.run('serialized-interleaving', node, ROOT / SOURCES[2], output / 'broadcast.wasm')
        require(result == b'PASS timed-broadcast-expiry-reclaim-new-wave\n', 'c-timed-source-exact-outcome')
        require(inputs == {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
            and tools == {name: file_identity(path, name) for name, path in (('zig', zig), ('node', node))},
            'c-timed-source-final-identity')
        record.update(status='passed', commands=commands.records,
            cases=['timed-broadcast-expiry-reclaim-new-wave'])
        write_json(output / 'source-controls.json', record)
        return record
    except BaseException:
        record['commands'] = commands.records
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': run(args.output, args.zig, args.node)['status']}))
