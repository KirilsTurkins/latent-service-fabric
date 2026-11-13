"""Compile selected C headers through the captured compiler, without an LSF node."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.captured_compiler_isolation import Isolation
from tools.c_guest import closed_headers, threading
from tools.c_guest.compiler import Compiler
from tools.dev_workflow.common import require
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCES = ('tools/c_closed_headers_controls.py', 'tools/tests/fixtures/c-closed-headers-control.cjs',
    'tools/c_guest/closed_headers.py', 'tools/c_guest/compiler.py', 'tools/c_guest/threading.py',
    'tools/captured_compiler_isolation.py', 'tools/c_application_dependencies.py',
    'sdk/c-guest/runtime/closed-signal-guard.c')


def public_graph():
    return {'worlds': [{'exports': {'interface-0': {'interface': {'id': 0}}}}],
            'interfaces': [{'name': 'api', 'package': 0, 'types': {}, 'functions': {
                'greet': {'name': 'greet', 'kind': 'async-freestanding',
                          'params': [{'name': 'name', 'type': 'string'}], 'result': 0}}}],
            'packages': [{'name': 'examples:ordinary@1.0.0'}],
            'types': [{'kind': {'result': {'ok': 'string', 'err': 'string'}}}]}


class LinkObserved(Exception):
    pass


def run(output: Path, zig: Path, node: Path, wasm_tools: Path):
    output = fresh(output)
    zig, node, wasm_tools = (path.resolve(strict=True) for path in (zig, node, wasm_tools))
    identities = {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
    tools = {name: file_identity(path, name) for name, path in (('zig', zig), ('node', node), ('wasm-tools', wasm_tools))}
    record = {'status': 'failed', 'sources': identities, 'tools': tools,
        'signedQualification': False, 'lsfNodeExecuted': False, 'actualComponentBuilt': False,
        'standaloneWasmExecuted': False,
        'substitutions': ['minimal generated bindings', 'empty thread runtime', 'no transformer'], 'cases': []}
    try:
        workspace = output / 'workspace'; workspace.mkdir()
        environment = build_environment(workspace)
        environment.update(ZIG_GLOBAL_CACHE_DIR=str(workspace / 'zig-global'),
                           ZIG_LOCAL_CACHE_DIR=str(workspace / 'zig-local'))
        version = run_bounded_result([str(zig), 'version'], workspace, environment, 20, 4096)
        require(version.returncode == 0 and version.stdout.strip() == b'0.16.0', 'c-closed-headers-zig-version')
        isolation = Isolation(workspace, {'zig': zig}, {'zig-compiler-and-sysroot': zig.parent})
        cases = ('unused', 'signal', 'setjmp', 'sentinel')
        for case in cases:
            project = workspace / ('captured-' + case); project.mkdir()
            sdk = project / 'sdk'; runtime = sdk / 'runtime'; runtime.mkdir(parents=True)
            (runtime / 'closed-signal-guard.c').write_bytes((ROOT / SOURCES[-1]).read_bytes())
            for name in ('threads.c', 'tls-keys.c', 'template-copy.c'):
                (runtime / name).write_text('/* controlled runtime input */\n')
            colliding = project / 'include'; (colliding / 'bits').mkdir(parents=True)
            (colliding / 'setjmp.h').write_text('typedef int jmp_buf[1];\n#define setjmp(b) ((void)(b),0)\n')
            (colliding / 'features.h').write_text('#error captured header cannot replace pinned declarations\n')
            for name in ('signal.h', 'setjmp.h'):
                (colliding / 'bits' / name).write_text('#error captured bits cannot replace pinned declarations\n')
            main = project / 'main.c'
            rescue = 'void __lsf_c_unsupported_signal_operation(void) {}\n' if case == 'sentinel' else ''
            main.write_text(rescue + 'int dependency(void);\n'
                '__attribute__((export_name("probe"))) int probe(void) { return dependency(); }\n')
            dependency = project / 'dependency.c'
            variants = {
                'unused': '#include <signal.h>\n#include <setjmp.h>\n'
                    '#if defined(_WASI_EMULATED_SIGNAL) || defined(__wasm_exception_handling__)\n'
                    '#error implementation macro escaped its declaration header\n#endif\n'
                    'int dependency(void) { return 7; }\n',
                'signal': '#include <signal.h>\nint dependency(void) { return signal(SIGPIPE,SIG_IGN)==SIG_ERR ? -1:0; }\n',
                'setjmp': '#include <setjmp.h>\nstatic jmp_buf state;\nint dependency(void) { return setjmp(state); }\n',
                'sentinel': '#include <signal.h>\nint dependency(void) { return signal(SIGPIPE,SIG_IGN)==SIG_ERR ? -1:0; }\n',
            }
            dependency.write_text(variants[case])
            isolation.protect_inputs(project)
            compiler = Compiler.__new__(Compiler)
            compiler.paths = {'zig': zig, 'c-threading-transformer': project / 'not-executed'}
            compiler.sdk, compiler.platform = sdk, None
            compiler.commands, compiler.isolation = None, isolation
            compiler.environment, compiler.deadline = environment, time.monotonic() + 120
            compiler.materials, compiler.closed_header_boundary, compiler.closed_header_stage = {}, None, None
            compiler.threading_time_alias = None
            original_run = compiler.run
            observed = {}
            def intercepted(tool, *arguments):
                if tool == 'wasm-tools':
                    require(arguments[:2] == ('component', 'wit'), 'c-closed-headers-control-graph')
                    return json.dumps(public_graph())
                if tool == 'zig' and '-Wl,--export-memory' in arguments:
                    compiler.closed_header_boundary.check_unchanged()
                    compiler.closed_header_stage.check_unchanged()
                    wrapped = isolation.wrap(zig, list(map(str, arguments)), workspace, environment)
                    result = run_bounded_result(wrapped, workspace, environment, 60, 16384)
                    observed.update(returncode=result.returncode, stderr=result.stderr.decode('utf-8', 'replace'),
                                    command=arguments, outerArguments=len(wrapped))
                    raise LinkObserved()
                return original_run(tool, *arguments)
            compiler.run = intercepted
            def generated(run_tool, _wit, _world, destination, _platform, *, sync_core_abi=False):
                require(sync_core_abi, 'c-closed-headers-control-threaded')
                destination.mkdir(); (destination / 'wit').mkdir()
                (destination / 'probe.c').write_text('int generated_probe;\n')
                empty = destination / 'component-type.c'; empty.write_text('int generated_component_type;\n')
                run_tool('zig', 'cc', '-target', 'wasm32-wasi', '-matomics', '-mbulk-memory', '-pthread',
                         '-c', str(empty), '-o', str(destination / 'probe_component_type.o'))
                return destination, {}
            try:
                with patch('tools.c_guest.compiler.generate', generated), patch.object(threading, 'EXPORTS', ()):
                    compiler.compile([main, dependency], project / 'wit', 'service', workspace / ('build-' + case),
                        trap=False, include_directories=(colliding,), dependency_sources=(dependency,),
                        threading_profile=threading.PROFILE, header_profile=closed_headers.PROFILE)
            except LinkObserved:
                pass
            else:
                raise ValueError('c-closed-headers-control-link-not-observed')
            command = observed.pop('command')
            guard = str(compiler.closed_header_stage.directory / 'guard.o')
            require(command.index(guard) < command.index(str(main)) < command.index(str(workspace / ('build-' + case) / 'dependency-0000.o')),
                    'c-closed-headers-guard-link-order')
            require(command.index(str(compiler.closed_header_stage.directory)) < command.index(str(colliding)),
                    'c-closed-headers-include-order')
            require(not any('allow-undefined' in arg or 'allow-multiple-definition' in arg for arg in command),
                    'c-closed-headers-linker-policy')
            if case in ('unused', 'sentinel'):
                require(observed['returncode'] == 0, 'c-closed-headers-positive-link')
                expected = 'return' if case == 'unused' else 'trap'
                core = workspace / ('build-' + case) / 'core.wasm'
                validated = run_bounded_result([str(wasm_tools), 'validate', '--features=-exceptions', str(core)],
                                               workspace, environment, 20, 4096)
                require(validated.returncode == 0, 'c-closed-headers-no-exceptions')
                result = run_bounded_result([str(node), str(ROOT / SOURCES[1]), str(core), expected],
                                            workspace, environment, 20, 4096)
                require(result.returncode == 0 and result.stdout == ('PASS closed-headers-' + expected + '\n').encode(),
                        'c-closed-headers-positive-runtime')
                observed['execution'] = expected
                record['standaloneWasmExecuted'] = True
            else:
                expected = '__lsf_c_unsupported_signal_operation' if case == 'signal' else 'undefined symbol: setjmp'
                require(observed['returncode'] != 0 and expected in observed['stderr'], 'c-closed-headers-negative-link')
                observed['rejection'] = expected
            inputs = isolation.receipt['preprocessorInputs']
            require(not any(row['path'].startswith(str(colliding)) for row in inputs), 'c-closed-headers-colliding-input')
            compiler.closed_header_boundary.check_unchanged(); compiler.closed_header_stage.check_unchanged()
            record['cases'].append({'case': case, 'linkExit': observed['returncode'],
                'execution': observed.get('execution'), 'rejection': observed.get('rejection'),
                'outerArguments': observed['outerArguments'], 'observedInputs': len(inputs),
                'guardObject': compiler.closed_header_stage.guard_object})
        # The selected compiler flags do not expose LLVM's alternate jump or
        # exception builtins. These checks stop at compilation, before linking.
        special = workspace / 'captured-builtin-refusals'; special.mkdir()
        special_cases = {
            'default-signal': ('#include <signal.h>\n', 'wasm lacks signal support', False),
            'default-setjmp': ('#include <setjmp.h>\n', 'Setjmp/longjmp support requires', False),
            'builtin-setjmp': ('static void *b[5]; int probe(void) { return __builtin_setjmp(b); }\n',
                               '__builtin_setjmp is not supported', True),
            'builtin-longjmp': ('static void *b[5]; void probe(void) { __builtin_longjmp(b,1); }\n',
                                '__builtin_longjmp is not supported', True),
            'builtin-throw': ('int probe(void) { __builtin_wasm_throw(0,0); return 7; }\n',
                              'needs target feature exception-handling', True),
            'upstream-override': ('#define __wasilibc_unmodified_upstream 1\n#include <signal.h>\n',
                                  'signal emulation is outside this closed header selection', True),
        }
        for name, (source, _expected, _overlay) in special_cases.items():
            (special / (name + '.c')).write_text(source)
        isolation.protect_inputs(special)
        for name, (_source, expected, overlay) in special_cases.items():
            flags = ['cc', '-std=c11', '-target', 'wasm32-wasi', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-matomics', '-mbulk-memory', '-pthread', '-fno-lto']
            if overlay:
                flags.extend(['-I', str(compiler.closed_header_stage.directory)])
            flags.extend(['-c', str(special / (name + '.c')), '-o', str(workspace / (name + '.o'))])
            command = isolation.wrap(zig, flags, workspace, environment)
            result = run_bounded_result(command, workspace, environment, 30, 8192)
            require(result.returncode != 0 and expected in result.stderr.decode('utf-8', 'replace'),
                    'c-closed-headers-builtin-refusal')
            record['cases'].append({'case': name, 'compileExit': result.returncode, 'rejection': expected})
        isolation.check_unchanged()
        require(identities == {name: file_identity(ROOT / name, name, 1024 * 1024) for name in SOURCES}
                and tools == {name: file_identity(path, name) for name, path in (('zig', zig), ('node', node), ('wasm-tools', wasm_tools))},
                'c-closed-headers-control-final-identity')
        record['status'] = 'passed'
        write_json(output / 'closed-headers-controls.json', record)
        return record
    except BaseException:
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zig', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--wasm-tools', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': run(args.output, args.zig, args.node, args.wasm_tools)['status']}))