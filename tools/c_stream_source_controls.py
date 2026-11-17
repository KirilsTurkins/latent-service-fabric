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
    'sdk/c-guest/src/standard-stdio.c', 'tools/tests/fixtures/c-stream-stdio-source.c',
    'tools/tests/fixtures/c-stream-stdio-source.cjs',
    'sdk/c-guest/src/standard-resolver.c', 'tools/tests/fixtures/c-stream-resolver-source.c',
    'tools/tests/fixtures/c-stream-resolver-source.cjs',
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
        require(observed == b'PASS descriptor_controls\nPASS send_nosignal_controls\nPASS descriptor_flags_controls\nPASS readiness_controls\nPASS full_shutdown_refusal_controls\nPASS half_close_controls\nPASS vector_controls\n',
                'c-stream-source-exact-outcome')
        # The composed profile uses the same maintained C bodies and genuine
        # generated WIT types, with explicit finite log/network/libc doubles.
        # A failed log call models unavailable authority; it does not prove a
        # signed node's pre-admission policy or real provider behavior.
        combined_source = output / 'combined-wit-input'
        combined_source.mkdir()
        (combined_source / 'world.wit').write_text('package tests:control@1.0.0; world service {}\n')
        combined_wit = standard_facilities.stage(
            combined_source, 'service', output / 'combined-wit', ROOT / 'wit/platform',
            profile=standard_facilities.STREAM_STDIO_PROFILE)
        combined_bindings = output / 'combined-bindings'
        combined_bindings.mkdir()
        commands.run('combined-bindings', wit, 'c', combined_wit, '--world', 'service',
                     '--rename-world', 'probe', '--async=-all', '--out-dir', combined_bindings)
        combined_args = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-D_POSIX_C_SOURCE=200809L',
                         '-DLSF_C_STREAM_NETWORK=1', '-DLSF_C_STREAM_STDIO=1', '-Wall', '-Wextra', '-Werror',
                         '-fno-builtin', '-nostdlib', '-Wl,--no-entry', '-Wl,--export-memory']
        for family in ('wasm-wasi-musl', 'generic-musl'):
            combined_args += ['-isystem', zig.parent / 'lib/libc/include' / family]
        combined_args += ['-I', combined_bindings, '-I', ROOT / 'sdk/c-guest/include',
                          '-include', ROOT / SOURCES[3], '-include', ROOT / SOURCES[1],
                          ROOT / SOURCES[0], ROOT / SOURCES[11], ROOT / SOURCES[12],
                          '-o', output / 'combined-controls.wasm']
        commands.run('combined-compile', zig, *combined_args)
        combined = commands.run('combined-controls', node, ROOT / SOURCES[13], output / 'combined-controls.wasm')
        require(combined == b'PASS stdio_stream_controls\nPASS stdio_missing_log_authority\n',
                'c-stream-stdio-source-exact-outcome')
        resolver_args = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
                         '-mexec-model=reactor', '-Wl,--no-entry', '-Wl,--export-memory',
                         '-matomics', '-mbulk-memory', '-pthread', '-fno-lto']
        commands.run('resolver-compile', zig, *resolver_args, ROOT / SOURCES[14], ROOT / SOURCES[15],
                     '-o', output / 'resolver.wasm')
        resolver = commands.run('resolver-controls', node, ROOT / SOURCES[16], output / 'resolver.wasm')
        require(resolver == b'PASS numeric_resolver_controls\n', 'c-stream-resolver-exact-outcome')
        # Exercise allocation refusal using a finite allocator double, not the
        # separately unqualified pinned-libc errno getter.
        commands.run('resolver-allocation-compile', zig, *resolver_args, '-DLSF_C_RESOLVER_TEST_ALLOC=1',
                     '-Dmalloc=lsf_test_malloc', '-Dfree=lsf_test_free', ROOT / SOURCES[14], ROOT / SOURCES[15],
                     '-o', output / 'resolver-allocation.wasm')
        allocation = commands.run('resolver-allocation-controls', node, ROOT / SOURCES[16],
                                  output / 'resolver-allocation.wasm')
        require(allocation == b'PASS numeric_resolver_controls\nPASS numeric_resolver_allocation_refusal\n',
                'c-stream-resolver-allocation-exact-outcome')
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
                      cases=['descriptor_controls', 'send_nosignal_controls', 'descriptor_flags_controls', 'readiness_controls', 'full_shutdown_refusal_controls',
                             'half_close_controls', 'vector_controls', 'libc-entropy',
                             'application_abort', 'original_libc_abort',
                             'stdio_stream_controls', 'stdio_missing_log_authority',
                             'numeric_resolver_controls', 'numeric_resolver_allocation_refusal'])
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
