"""Bounded serialized C source controls; never a canonical runtime qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dev_workflow.common import require
from tools.qualify_c_context_lowering import identity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'tools/tests/fixtures/c-sync-reference.'
HEADERS = {
    'libc/include/wasm-wasi-musl/bits/alltypes.h': {'bytes': 12741, 'sha256': '64fc420ff336e0b2e67f5b0ed78d108aa419d5d1ad093acb1e25b38a6d9eb038'},
    'libc/include/wasm-wasi-musl/pthread.h': {'bytes': 11218, 'sha256': '21b1fd90de05919d0718109f16fa1408a0750dcf65f63cc661c506f07e8e1ca1'},
    'libc/include/generic-musl/threads.h': {'bytes': 1794, 'sha256': '402b75ff71dd5051ebf8744fe7e09a9e43740b9798e6c02701929c852972a2fc'},
    'libc/include/wasm-wasi-musl/__errno_values.h': {'bytes': 2975, 'sha256': '87dedbaff433fe74c68e17437c0192081401c9cf8f6430fde3449948c9b78598'},
    'libc/include/wasm-wasi-musl/wasi/api.h': {'bytes': 56969, 'sha256': '8cf2859277ea2fc984780a00048686955805fd8a00c7be1d8f916105becf0174'},
}
SOURCES = ('tools/c_sync_source_controls.py', FIXTURE + 'c', FIXTURE + 'cjs',
    'sdk/c-guest/runtime/threads.c', 'sdk/c-guest/runtime/synchronization.c',
    'sdk/c-guest/runtime/thread-abi.h', 'tools/qualify_c_context_lowering.py',
    'crates/latent-component-threading/src/c_lifecycle.rs',
    'crates/vendor/wasmtime/src/runtime/component/concurrent.rs',
    'crates/vendor/wasmtime/src/runtime/vm/component/libcalls.rs',
    'tools/build_observation.py', 'tools/build_process.py',
    'tools/build_process_windows.py', 'tools/build_process_linux.py',
    'tools/build_process_signals.py', 'tools/dev_workflow/common.py')


def public_abi(headers):
    """Extract only exact pinned memory32 declarations for explicit test ports."""
    types, pthread, c11, errors, api = (headers[name].decode() for name in HEADERS)
    parts = ['/* Exact pinned public declarations; all host operations are doubles. */\n']
    def one(expression, text):
        matches = re.findall(expression, text, re.M)
        require(len(matches) == 1, 'c-sync-one-pinned-public-declaration')
        return matches[0]
    for name in ('EINVAL', 'EAGAIN', 'ENOTSUP', 'EPERM', 'EBUSY', 'EDEADLK', 'ESRCH'):
        wasi = one(r'^#define ' + name + r' (__WASI_ERRNO_\w+)$', errors)
        parts.extend([one(r'^#define ' + wasi + r' .*$', api) + '\n',
            '#define ' + name + ' ' + wasi + '\n'])
    for name in ('pthread_mutex_t', 'pthread_cond_t', 'pthread_mutexattr_t',
            'pthread_condattr_t', 'mtx_t', 'cnd_t'):
        parts.append(one(r'^typedef struct .* ' + name + r';$', types) + '\n')
    # C, not C++, selects the original opaque pointer pthread_t declaration.
    parts.append(one(r'^typedef struct __pthread \* pthread_t;$', types) + '\n')
    for name in ('PTHREAD_MUTEX_NORMAL', 'PTHREAD_MUTEX_RECURSIVE', 'PTHREAD_MUTEX_ERRORCHECK'):
        parts.append(one(r'^#define ' + name + r' \d+$', pthread) + '\n')
    for name in ('thrd_success', 'mtx_plain'):
        parts.append(one(r'enum \{\s*' + name + r'[^}]+\};', c11) + '\n')
    return ''.join(parts).encode()


def run(output, zig, node):
    require(not output.exists() and not output.is_symlink(), 'c-sync-fresh-control-output')
    output.mkdir(parents=True, mode=0o700)
    before = {name: identity(ROOT / name, 1024 * 1024) for name in SOURCES}
    tools = {name: identity(path) for name, path in (('zig', zig), ('node', node))}
    report = {'schemaVersion': 'latent.c.serialized-sync-source-controls.v1', 'status': 'failed',
        'source': before, 'tools': tools, 'commands': [], 'cases': 13,
        'canonicalAndBrokerPorts': 'explicit-serialized-doubles',
        'actualGuestExecuted': False, 'actualCanonicalWaitExecuted': False,
        'actualOriginalLedgerExecuted': False, 'signedQualification': False}
    environment = build_environment(output)
    environment.update(ZIG_GLOBAL_CACHE_DIR=str(output / 'zig-global'),
        ZIG_LOCAL_CACHE_DIR=str(output / 'zig-local'))
    deadline, used = time.monotonic() + 120, 0
    def command(argv):
        nonlocal used
        remaining = deadline - time.monotonic()
        require(remaining > 0 and used < 1024 * 1024, 'c-sync-command-bound')
        argv = [str(value) for value in argv]
        result = run_bounded_result(argv, ROOT, environment, min(60, remaining), 1024 * 1024 - used)
        used += len(result.stdout) + len(result.stderr)
        ordinal = len(report['commands'])
        for stream in ('stdout', 'stderr'):
            (output / f'{ordinal:02}.{stream}.txt').write_bytes(getattr(result, stream))
        report['commands'].append({'argv': argv, 'exitCode': result.returncode})
        require(result.returncode == 0, 'c-sync-source-command-failed')
        return result.stdout
    try:
        require(command([zig, 'version']).strip() == b'0.16.0', 'c-sync-pinned-zig-version')
        directories = re.findall(r'^\s*\.lib_dir = ("(?:[^"\\]|\\.)*"),$',
            command([zig, 'env']).decode(), re.M)
        require(len(directories) == 1, 'c-sync-one-zig-lib-directory')
        lib = Path(json.loads(directories[0]))
        header_ids = {name: identity(lib / name, 1024 * 1024) for name in HEADERS}
        require(header_ids == HEADERS,
            'c-sync-pinned-public-header-preimage')
        headers = {}
        for name in HEADERS:
            with (lib / name).open('rb') as stream:
                headers[name] = stream.read(1024 * 1024 + 1)
            require(len(headers[name]) == header_ids[name]['bytes'], 'c-sync-public-header-read-bound')
        report['publicAbiInputs'] = header_ids
        abi = output / 'c-sync-reference-abi.h'
        abi.write_bytes(public_abi(headers))
        original = (ROOT / 'sdk/c-guest/runtime/threads.c').read_text()
        find = original[original.index('static struct lsf_c_thread *find('):
            original.index('static int ensure_root_owners(')]
        join = original[original.index('static int join_claim('):original.index('int pthread_join(')]
        body = output / 'c-join-reference-body.h'
        body.write_bytes((find + join).encode())
        flags = ['cc', '-target', 'wasm32-wasi', '-std=c17', '-O2', '-Wall', '-Wextra', '-Werror']
        runtime = ROOT / 'sdk/c-guest/runtime'
        wasi = [part for family in ('wasm-wasi-musl', 'generic-musl') for part in
            ('-isystem', str(lib / 'libc/include' / family))]
        # Compile the full actual production TU against original WASI headers.
        command([zig, *flags, '-matomics', '-mbulk-memory', '-pthread', *wasi,
            '-c', runtime / 'threads.c', '-o', output / 'threads.o'])
        # Execute identical source bodies with explicit serialized ports, not
        # canonical Wasmtime intrinsics or the activation broker.
        command([zig, *flags, '-fno-builtin', '-fno-stack-protector', '-nostdlib',
            '-Wl,--no-entry', '-Wl,--export=lsf_test_entry', '-Wl,-z,stack-size=65536',
            '-Wl,--max-memory=4194304', '-I', output, '-I', runtime,
            ROOT / (FIXTURE + 'c'), '-o', output / 'reference.wasm'])
        stdout = command([node, '--max-old-space-size=64', ROOT / (FIXTURE + 'cjs'), output / 'reference.wasm'])
        require(stdout == b'PASS:13 serialized production-source cases; no engine/ledger qualification\n',
            'c-sync-exact-source-control-result')
        report['outputs'] = {name: identity(output / name, 1024 * 1024) for name in
            ('threads.o', 'reference.wasm', abi.name, body.name)}
        require(header_ids == {name: identity(lib / name, 1024 * 1024) for name in HEADERS},
            'c-sync-header-input-changed')
        require(before == {name: identity(ROOT / name, 1024 * 1024) for name in SOURCES},
            'c-sync-source-input-changed')
        require(tools == {name: identity(path) for name, path in (('zig', zig), ('node', node))},
            'c-sync-tool-input-changed')
        report['status'] = 'passed'
        return report
    finally:
        (output / 'source-controls.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.zig.resolve(strict=True), args.node.resolve(strict=True))
