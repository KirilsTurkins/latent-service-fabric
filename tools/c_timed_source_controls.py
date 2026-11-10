"""Bounded real-C timed-wait controls with explicit serialized host doubles."""
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
    'tools/build_observation.py', 'tools/rust_capsule_build.py',
    'tools/tests/fixtures/c-timed-deadline-source.c',
    'tools/tests/fixtures/c-timed-deadline-source.cjs', 'sdk/c-guest/runtime/threads.c')

DEADLINE_CASES = ('mutex_fast', 'mutex_expired', 'mutex_invalid', 'condition_expired',
    'condition_invalid', 'future_relative', 'future_overflow', 'clock_failure',
    'c11_expired', 'duration_boundaries', 'mutex_next_refused', 'condition_next_refused',
    'sleep_next_refused', 'c11_next_refused', 'c11_condition_next_refused',
    'mutex_notification_during_refusal', 'condition_notification_during_refusal',
    'poll_clock_zero', 'poll_clock_elapsed', 'poll_clock_refusals', 'poll_clock_invalid',
    'poll_clock_max', 'poll_clock_aliases',
    'terminal_cancel', 'terminal_deadline', 'terminal_cancel_after_notification',
    'refusal_cancel_before_wake', 'refusal_notification_cancel_before_wake',
    'poll_terminal_cancel', 'poll_terminal_deadline')


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
        headers = {**threading.libc_inputs(zig), **threading.clock_libc_inputs(zig),
                   **threading.poll_libc_inputs(zig)}
        record['publicHeaders'] = {name: file_identity(path, name, threading.POLL_LIBC_MAX_BYTES)
                                   for name, path in headers.items()}
        args = ['cc', '-std=c17', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
            '-matomics', '-mbulk-memory', '-pthread', '-nostdlib', '-fno-builtin', '-Wl,--no-entry',
            '-Wl,--export-memory', '-I', ROOT / 'sdk/c-guest/runtime']
        for family in ('wasm-wasi-musl', 'generic-musl'):
            args += ['-isystem', zig.parent / 'lib/libc/include' / family]
        args += ['-D' + define for define in threading.linked_defines((), timed_clock=True)]
        # The override belongs only to the timed cooperative profile. Check
        # the actual threads translation unit with the compiler-owned defines.
        for timed in (False, True):
            selection = ['cc', '-std=c17', '-target', 'wasm32-wasi', '-E', '-P', '-pthread',
                '-I', ROOT / 'sdk/c-guest/runtime']
            selection += ['-D' + define for define in threading.linked_defines((), timed_clock=timed)]
            observed = commands.run('preprocess-poll-' + ('timed' if timed else 'untimed'),
                                    zig, *selection, ROOT / 'sdk/c-guest/runtime/threads.c')
            symbol = b'int32_t __imported_wasi_snapshot_preview1_poll_oneoff('
            require(observed.count(symbol) == (1 if timed else 0), 'c-timed-poll-profile-selection')
        commands.run('compile-real-source-control', zig, *args, ROOT / SOURCES[1], '-o', output / 'broadcast.wasm')
        result = commands.run('serialized-interleaving', node, ROOT / SOURCES[2], output / 'broadcast.wasm')
        require(result == b'PASS timed-broadcast-expiry-reclaim-new-wave\n', 'c-timed-source-exact-outcome')
        commands.run('compile-deadline-source-control', zig, *args, ROOT / SOURCES[8], '-o', output / 'deadline.wasm')
        result = commands.run('serialized-deadline-controls', node, ROOT / SOURCES[9], output / 'deadline.wasm')
        expected = ''.join('PASS ' + name + '\n' for name in DEADLINE_CASES).encode()
        require(result == expected, 'c-timed-deadline-source-exact-outcome')
        # Compile the same real synchronization source with the pinned libc
        # selected, then call its unchanged select(0, ...) through the bridge.
        libc_args = [value for value in args if value != '-nostdlib']
        libc_args += ['-mexec-model=reactor', '-DLSF_C_TEST_LIBC_SELECT=1']
        commands.run('compile-libc-select-control', zig, *libc_args, ROOT / SOURCES[8], '-o', output / 'libc.wasm')
        result = commands.run('libc-select-control', node, ROOT / SOURCES[9], output / 'libc.wasm', '--libc')
        require(result == b'PASS poll_clock_via_libc\n', 'c-timed-libc-select-exact-outcome')
        require(inputs == {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
            and tools == {name: file_identity(path, name) for name, path in (('zig', zig), ('node', node))},
            'c-timed-source-final-identity')
        record.update(status='passed', commands=commands.records,
            cases=['timed-broadcast-expiry-reclaim-new-wave', *DEADLINE_CASES, 'poll_clock_via_libc'])
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
