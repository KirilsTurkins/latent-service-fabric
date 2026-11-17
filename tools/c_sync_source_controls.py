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
    'libc/include/generic-musl/semaphore.h': {'bytes': 809, 'sha256': '75b08ab57e6dc8d1fd6745404375d3caef99dec66f4bcbd423c77a9078c52912'},
}
SOURCES = ('tools/c_sync_source_controls.py', FIXTURE + 'c', FIXTURE + 'cjs',
    'tools/tests/fixtures/c-once-jspi.c', 'tools/tests/fixtures/c-once-jspi.cjs',
    'tools/tests/fixtures/c-root-drain-jspi.c', 'tools/tests/fixtures/c-root-drain-jspi.cjs',
    'tools/tests/fixtures/c-gnu-join-reference.c', 'tools/tests/fixtures/c-gnu-join-reference.cjs',
    'sdk/c-guest/runtime/threads.c', 'sdk/c-guest/runtime/synchronization.c',
    'sdk/c-guest/runtime/thread-abi.h', 'tools/qualify_c_context_lowering.py',
    'crates/latent-component-threading/src/c_lifecycle.rs', 'crates/latent-component-threading/src/c_root.rs',
    'crates/vendor/wasmtime/src/runtime/component/concurrent.rs',
    'crates/vendor/wasmtime/src/runtime/vm/component/libcalls.rs',
    'tools/build_observation.py', 'tools/build_process.py',
    'tools/build_process_windows.py', 'tools/build_process_linux.py',
    'tools/build_process_signals.py', 'tools/dev_workflow/common.py')


# These inputs bind the original weak GNU-join stubs and the deadline type used
# by the reference. This does not claim a complete Zig distribution manifest.
GNU_JOIN_INPUTS = {
    'libc/wasi/thread-stub/pthread_join.c': {'bytes': 818, 'sha256': 'c1c27373ba29ceb21496a6368ac1a94a6e0914bde5f0600d9f5c9ff1c3165f83'},
    'libc/include/wasm-wasi-musl/time.h': {'bytes': 5791, 'sha256': '2ea91196e2b6268feabec85041a9bda6381800b470451a6bcff9445510c93546'},
    'libc/include/wasm-wasi-musl/__header_time.h': {'bytes': 817, 'sha256': '03fe8f66a5ffa0b448a96e9a0f19bde5e8cd5923c024d4e927b16f6d8d9c14c9'},
    'libc/include/wasm-wasi-musl/__struct_timespec.h': {'bytes': 205, 'sha256': 'b19b09edfe60735c5dd38da0416e722409473ec94885e465aab7c4fd98202840'},
    'libc/include/wasm-wasi-musl/__typedef_time_t.h': {'bytes': 179, 'sha256': 'b1ad083733361f8b5077ff9dc3412bd7d7a5f455fdd1eef5fb66d188fada1e98'},
}


def public_abi(headers):
    """Extract only exact pinned memory32 declarations for explicit test ports."""
    types, pthread, c11, errors, api, semaphore = (headers[name].decode() for name in HEADERS)
    parts = ['/* Exact pinned public declarations; all host operations are doubles. */\n']
    def one(expression, text):
        matches = re.findall(expression, text, re.M)
        require(len(matches) == 1, 'c-sync-one-pinned-public-declaration')
        return matches[0]
    for name in ('EINVAL', 'EAGAIN', 'ENOTSUP', 'EPERM', 'EBUSY', 'EDEADLK', 'ESRCH', 'EOVERFLOW'):
        wasi = one(r'^#define ' + name + r' (__WASI_ERRNO_\w+)$', errors)
        parts.extend([one(r'^#define ' + wasi + r' .*$', api) + '\n',
            '#define ' + name + ' ' + wasi + '\n'])
    for name in ('pthread_mutex_t', 'pthread_cond_t', 'pthread_mutexattr_t', 'pthread_rwlock_t', 'pthread_rwlockattr_t',
            'pthread_condattr_t', 'mtx_t', 'cnd_t'):
        parts.append(one(r'^typedef struct .* ' + name + r';$', types) + '\n')
    parts.append(one(r'^typedef int pthread_once_t;$', types) + '\n')
    parts.append(one(r'^typedef int once_flag;$', c11) + '\n')
    parts.append('#define _SEMAPHORE_H\n' + one(r'^(typedef struct \{\s*volatile int __val\[4\*sizeof\(long\)/sizeof\(int\)\];\s*\} sem_t;)$', semaphore) + '\n')
    parts.append(one(r'^#define PTHREAD_ONCE_INIT 0$', pthread) + '\n')
    parts.append(one(r'^#define ONCE_FLAG_INIT 0$', c11) + '\n')
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
        'source': before, 'tools': tools, 'commands': [], 'cases': 19,
        'canonicalAndBrokerPorts': 'explicit-serialized-and-jspi-doubles',
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
        gnu_join_inputs = {name: identity(lib / name, 1024 * 1024) for name in GNU_JOIN_INPUTS}
        require(gnu_join_inputs == GNU_JOIN_INPUTS, 'c-sync-pinned-gnu-join-inputs')
        report['gnuJoinInputs'] = gnu_join_inputs
        abi = output / 'c-sync-reference-abi.h'
        abi.write_bytes(public_abi(headers))
        original = (ROOT / 'sdk/c-guest/runtime/threads.c').read_text()
        creation = original[original.index('static void discard_unstarted('):
            original.index('/* Retain the complete original creation ABI')]
        creation_body = output / 'c-create-reference-body.h'
        creation_body.write_bytes(creation.encode())
        find = original[original.index('static struct lsf_c_thread *find('):
            original.index('static int ensure_root_owners(')]
        join = original[original.index('static int join_claim('):original.index('int pthread_join(')]
        body = output / 'c-join-reference-body.h'
        body.write_bytes((find + join).encode())
        lifecycle = original[original.index('__attribute__((export_name("__lsf_c_thread_body")))'):
            original.index('#if defined(LSF_C_LINKED_LIBC)')]
        drain_body = output / 'c-root-drain-reference-body.h'
        drain_body.write_bytes((find + join + lifecycle).encode())
        extension = original.find('int pthread_tryjoin_np(')
        detach = original.index('int pthread_detach(')
        require(extension < detach, 'c-sync-gnu-join-body-order')
        gnu_join_body = output / 'c-gnu-join-reference-body.h'
        gnu_join_body.write_bytes(original[extension:detach].encode() if extension >= 0 else b'')
        flags = ['cc', '-target', 'wasm32-wasi', '-std=c17', '-O2', '-Wall', '-Wextra', '-Werror']
        runtime = ROOT / 'sdk/c-guest/runtime'
        wasi = [part for family in ('wasm-wasi-musl', 'generic-musl') for part in
            ('-isystem', str(lib / 'libc/include' / family))]
        rwlock_symbols = ('pthread_rwlock_init', 'pthread_rwlock_destroy', 'pthread_rwlock_rdlock',
            'pthread_rwlock_tryrdlock', 'pthread_rwlock_wrlock', 'pthread_rwlock_trywrlock',
            'pthread_rwlock_unlock', 'pthread_rwlock_timedrdlock', 'pthread_rwlock_timedwrlock')
        rwlock_flags = ('-DLSF_C_RWLOCKS=1', *('-D' + name + '=__lsf_c_' + name for name in rwlock_symbols))
        semaphore_symbols = ('sem_init', 'sem_destroy', 'sem_getvalue', 'sem_trywait',
                             'sem_wait', 'sem_post', 'sem_timedwait')
        semaphore_flags = ('-DLSF_C_SEMAPHORES=1', *('-D' + name + '=__lsf_c_' + name for name in semaphore_symbols))
        # Compile the full actual production TU against original WASI headers.
        command([zig, *flags, '-matomics', '-mbulk-memory', '-pthread', *wasi,
            '-c', runtime / 'threads.c', '-o', output / 'threads.o'])
        command([zig, *flags, '-matomics', '-mbulk-memory', '-pthread', *wasi, *rwlock_flags, *semaphore_flags,
            '-c', runtime / 'threads.c', '-o', output / 'threads-rwlock.o'])
        command([zig, *flags, '-matomics', '-mbulk-memory', '-pthread', *wasi, *semaphore_flags,
            '-DLSF_C_SEMAPHORE_CLIENT=1', '-c', ROOT / 'tools/tests/fixtures/c-root-drain-jspi.c',
            '-o', output / 'semaphore-client.o'])
        stdout = command([node, '--max-old-space-size=64', ROOT / 'tools/tests/fixtures/c-root-drain-jspi.cjs',
            output / 'semaphore-client.o', 'semaphore-imports'])
        require(stdout == b'PASS captured semaphore caller: seven private SDK imports\n',
            'c-thread-semaphore-private-caller-imports')
        # Execute identical source bodies with explicit serialized ports, not
        # canonical Wasmtime intrinsics or the activation broker.
        command([zig, *flags, '-fno-builtin', '-fno-stack-protector', '-nostdlib',
            '-Wl,--no-entry', '-Wl,--export=lsf_test_entry', '-Wl,-z,stack-size=65536',
            '-Wl,--max-memory=4194304', '-I', output, '-I', runtime,
            ROOT / (FIXTURE + 'c'), '-o', output / 'reference.wasm'])
        stdout = command([node, '--max-old-space-size=64', ROOT / (FIXTURE + 'cjs'), output / 'reference.wasm'])
        require(stdout == b'PASS:19 serialized production-source cases; no engine/ledger qualification\n',
            'c-sync-exact-source-control-result')
        exports = ('__stack_pointer', 'setup', 'set_scenario', 'root_pointer', 'first_pointer',
            'second_pointer', 'start_root', 'start_first', 'start_second', 'read_flag',
            'read_init', 'read_finished', 'read_live', 'read_admitted', 'read_settled',
            'read_parked', 'read_woken')
        command([zig, *flags, '-fno-builtin', '-fno-stack-protector', '-nostdlib',
            '-Wl,--no-entry', '-Wl,--import-memory', '-Wl,--initial-memory=4194304',
            '-Wl,--max-memory=4194304', '-Wl,-z,stack-size=65536',
            *('-Wl,--export=' + name for name in exports), '-I', output, '-I', runtime,
            ROOT / 'tools/tests/fixtures/c-once-jspi.c', '-o', output / 'once-jspi.wasm'])
        stdout = command([node, '--max-old-space-size=64', '--experimental-wasm-jspi',
            ROOT / 'tools/tests/fixtures/c-once-jspi.cjs', output / 'once-jspi.wasm'])
        require(stdout == b'actual once source: one initializer, two suspended mixed-API waiters, two settled Wait doubles; recursion and initializer traps retained; JSPI test ports only\n',
            'c-once-jspi-source-control-result')
        drain_exports = ('__stack_pointer', 'setup', 'root_pointer', 'first_pointer', 'second_pointer',
            'start_root', 'start_first', 'start_second', 'read_live', 'read_peak', 'read_admitted',
            'read_settled', 'read_released', 'read_freed', 'read_parked', 'read_woken', 'read_tls',
            'read_first_phase', 'read_second_phase', 'read_second_claimed', 'read_second_joined',
            'read_root_observer', 'rw_setup', 'rw_set_shared', 'rw_set_reader_limit', 'rw_refuse_wait',
            'rw_pause_admission', 'rw_init_default', 'rw_destroy', 'rw_read', 'rw_write', 'rw_tryread',
            'rw_trywrite', 'rw_unlock', 'rw_timedread', 'rw_timedwrite', 'rw_errno', 'rw_busy',
            'rw_again', 'rw_notsup', 'rw_perm', 'rw_deadlock',
            'ss_setup', 'ss_shared', 'ss_invalid', 'ss_destroy', 'ss_getvalue', 'ss_wait', 'ss_trywait',
            'ss_post', 'ss_timedwait', 'ss_pause_admission', 'ss_refuse_wait', 'ss_errno',
            'ss_eagain', 'ss_ebusy', 'ss_einval', 'ss_overflow', 'ss_notsup', 'ss_intmax')
        command([zig, *flags, '-fno-builtin', '-fno-stack-protector', '-nostdlib',
            *rwlock_flags, *semaphore_flags,
            '-Wl,--no-entry', '-Wl,--import-memory', '-Wl,--initial-memory=4194304',
            '-Wl,--max-memory=4194304', '-Wl,-z,stack-size=65536',
            *('-Wl,--export=' + name for name in drain_exports), '-I', output, '-I', runtime,
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.c', '-o', output / 'root-drain-jspi.wasm'])
        stdout = command([node, '--max-old-space-size=64', '--experimental-wasm-jspi',
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.cjs', output / 'root-drain-jspi.wasm'])
        require(stdout == b'PASS root drain: existing and later joins, admission and park races, cancellation custody; JSPI test ports only\n',
            'c-root-drain-jspi-source-control-result')
        report['rootDrainScenarios'] = 5
        stdout = command([node, '--max-old-space-size=64', '--experimental-wasm-jspi',
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.cjs', output / 'root-drain-jspi.wasm', 'rwlock'])
        require(stdout == b'PASS rwlock source: readers, writers, wakeups, refusals and cancellation; JSPI test ports only\n',
            'c-thread-rwlock-jspi-source-control-result')
        report['rwlockScenarios'] = 8
        stdout = command([node, '--max-old-space-size=64', '--experimental-wasm-jspi',
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.cjs', output / 'root-drain-jspi.wasm', 'semaphore'])
        require(stdout == b'PASS semaphore source: permits, wait ownership, races, refusal and cancellation; JSPI test ports only\n',
            'c-thread-semaphore-jspi-source-control-result')
        report['semaphoreScenarios'] = 9
        create_exports = ('__stack_pointer', 'setup_create', 'caller_pointer', 'start_create',
            'close_create_root', 'create_count', 'create_list_count', 'create_live',
            'create_settled', 'create_admissions', 'create_allocations', 'create_frees',
            'create_eagain', 'create_enomem')
        command([zig, *flags, '-fno-builtin', '-fno-stack-protector', '-nostdlib',
            '-DLSF_C_CREATE_CONTROL=1', *wasi, '-Wl,--no-entry', '-Wl,--import-memory',
            '-Wl,--initial-memory=4194304', '-Wl,--max-memory=4194304', '-Wl,-z,stack-size=65536',
            *('-Wl,--export=' + name for name in create_exports), '-I', output, '-I', runtime,
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.c', '-o', output / 'create-jspi.wasm'])
        stdout = command([node, '--max-old-space-size=64', '--experimental-wasm-jspi',
            ROOT / 'tools/tests/fixtures/c-root-drain-jspi.cjs', output / 'create-jspi.wasm', 'create'])
        require(stdout == b'PASS create source: concurrent capacity, closing, paid cleanup and refusal paths; JSPI test ports only\n',
            'c-thread-create-jspi-source-control-result')
        report['createAdmissionScenarios'] = 19
        libc = lib / 'libc'
        wasi_musl, musl = libc / 'wasi/libc-top-half/musl', libc / 'musl'
        private = (wasi_musl / 'src/internal', musl / 'src/internal', wasi_musl / 'src/include',
            musl / 'src/include', wasi_musl / 'arch/wasm32', musl / 'arch/generic',
            libc / 'wasi/libc-top-half/headers/private', libc / 'wasi/libc-bottom-half/cloudlibc/src')
        # Compile the original weak-stub translation unit, with the same libc
        # warning policy, rather than replacing it with a fabricated double.
        command([zig, 'cc', '-target', 'wasm32-wasi', '-std=gnu17', '-D_GNU_SOURCE', '-O2', '-w',
            '-matomics', '-mbulk-memory', '-pthread', '-fno-lto',
            *(part for path in private for part in ('-I', path)),
            '-c', lib / 'libc/wasi/thread-stub/pthread_join.c', '-o', output / 'pinned-pthread-join.o'])
        command([zig, *flags, '-matomics', '-mbulk-memory', '-pthread', '-fno-lto', '-nostdlib',
            '-Wl,--no-entry', '-Wl,--export-memory', *wasi, '-I', output,
            ROOT / 'tools/tests/fixtures/c-gnu-join-reference.c', output / 'pinned-pthread-join.o',
            '-o', output / 'gnu-join-reference.wasm'])
        stdout = command([node, '--max-old-space-size=64',
            ROOT / 'tools/tests/fixtures/c-gnu-join-reference.cjs', output / 'gnu-join-reference.wasm'])
        require(stdout == b'PASS pinned libc GNU joins: explicit refusal, unchanged outputs\n',
            'c-sync-pinned-gnu-join-result')
        report['gnuJoinCases'] = 2
        report['outputs'] = {name: identity(output / name, 1024 * 1024) for name in
            ('threads.o', 'threads-rwlock.o', 'semaphore-client.o', 'reference.wasm', 'once-jspi.wasm', 'root-drain-jspi.wasm', 'create-jspi.wasm',
             'pinned-pthread-join.o', 'gnu-join-reference.wasm',
             abi.name, body.name, drain_body.name, creation_body.name, gnu_join_body.name)}
        require(header_ids == {name: identity(lib / name, 1024 * 1024) for name in HEADERS},
            'c-sync-header-input-changed')
        require(gnu_join_inputs == {name: identity(lib / name, 1024 * 1024) for name in GNU_JOIN_INPUTS},
            'c-sync-gnu-join-input-changed')
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
