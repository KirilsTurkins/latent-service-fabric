"""One selected C link and real ABI/encoder controls; never a thread runtime pass."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.c_guest.bindings import generate
from tools.dev_workflow.common import require
from tools.qualify_c_context_lowering import header_identity, identity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'sdk/c-guest/runtime-fixtures/canonical-abi/'
WORLD = 'examples:threading/service@1.0.0'
EXPORT = 'examples:threading/api@1.0.0#greet'
LIBC_ERRNO_SOURCES = {
    'libc/include/wasm-wasi-musl/errno.h': '844d1aa7a14734acde284e3109db63e29511540f6c9ccfefe46e455fd5b3ab40',
    'libc/include/wasm-wasi-musl/__errno.h': 'b9ce417c2b172bf982d8ef0236adfe442f54e7d0d344e75104cbcede88a9d7e2',
    'libc/wasi/libc-bottom-half/cloudlibc/src/libc/errno/errno.c': 'eeecab4885f9dba3df77a2c81c1960f1f84779a2b16f0b2aceb1d83af1d47aa3',
    'libc/wasi/libc-bottom-half/sources/__errno_location.c': 'fb6d59a8ca5b99dc0799db259a7b35e7403818469f6cbf6a6ec1178fec98f702',
}
SOURCES = (
    'tools/qualify_c_canonical_abi.py', 'tools/qualify_c_context_lowering.py',
    'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_windows.py',
    'tools/build_process_signals.py',
    'tools/build_observation.py', 'tools/build_snapshot.py', 'tools/c_guest/bindings.py',
    'tools/stage_runtime_wit.py', 'tools/dev_workflow/common.py',
    'tools/install_guest_bindgen.py', 'tools/toolchain.toml',
    FIXTURE+'probe.c', FIXTURE+'control.cjs', FIXTURE+'world.wit',
    'sdk/c-guest/runtime/threads.c', 'sdk/c-guest/runtime/synchronization.c',
    'sdk/c-guest/runtime/thread-abi.h',
    'sdk/c-guest/runtime/thread-abi.json', 'sdk/c-guest/runtime/tls-keys.c',
    'sdk/c-guest/src/trap.c', 'wit/platform/native-runtime/package.wit',
    'wit/platform/activation-runtime/package.wit',
    'crates/latent-component-threading/Cargo.toml', 'Cargo.toml', 'Cargo.lock',
    '.github/workflows/c-context-mechanism.yml',
)


def sources():
    rows = dict.fromkeys(SOURCES)
    for path in sorted((ROOT/'crates/latent-component-threading/src').rglob('*.rs')):
        require(not path.is_symlink() and len(rows) < 128, 'c-abi-source-closure-bound')
        rows[path.relative_to(ROOT).as_posix()] = None
    # The maintained dependency selector reads the available package inventory
    # before selecting the two declared packages. Bind that input too.
    for path in sorted((ROOT/'wit/platform').rglob('*.wit')):
        require(not path.is_symlink() and len(rows) < 256, 'c-abi-platform-wit-count')
        rows[path.relative_to(ROOT).as_posix()] = None
    return {name: identity(ROOT/name, 16*1024*1024) for name in sorted(rows)}


def public_contract(graph):
    require(isinstance(graph, dict) and set(graph) == {'worlds', 'interfaces', 'types', 'packages'},
            'c-abi-wit-graph-shape')
    require(isinstance(graph['worlds'], list) and len(graph['worlds']) == 1, 'c-abi-one-world')
    world = graph['worlds'][0]
    require(len(world['exports']) == 1, 'c-abi-one-original-interface')
    key, exported = next(iter(world['exports'].items()))
    index = exported.get('interface', {}).get('id')
    require(type(index) is int and 0 <= index < len(graph['interfaces']), 'c-abi-export-interface-index')
    require(key == 'interface-'+str(index), 'c-abi-export-interface-key')
    imported = set()
    for item in world['imports'].values():
        imported_index = item.get('interface', {}).get('id')
        require(type(imported_index) is int and 0 <= imported_index < len(graph['interfaces']),
                'c-abi-import-interface-index')
        imported_interface = graph['interfaces'][imported_index]
        package = graph['packages'][imported_interface['package']]['name']
        imported.add(package.replace('@','/'+imported_interface['name']+'@'))
    require(imported == {'latent:runtime/activation@0.1.0', 'latent:runtime-native/threads@0.1.0'},
            'c-abi-declared-runtime-only-imports')
    interface = graph['interfaces'][index]
    package = graph['packages'][interface['package']]['name']
    require(package == 'examples:threading@1.0.0' and interface['name'] == 'api'
            and interface['types'] == {} and set(interface['functions']) == {'greet'},
            'c-abi-original-export-identity')
    function = interface['functions']['greet']
    result = function['result']
    require(function['name'] == 'greet' and function['kind'] == 'freestanding'
            and function['params'] == [{'name':'name', 'type':'string'}]
            and type(result) is int and 0 <= result < len(graph['types'])
            and graph['types'][result]['kind'] == {'result':{'ok':'string', 'err':'string'}},
            'c-abi-original-sync-string-result')
    return {'interface':package.replace('@', '/api@'), 'name':'greet',
            'params':['string'], 'result':{'ok':'string', 'err':'string'}, 'async':False}


def tree(directory):
    rows, total = {}, 0
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'c-abi-generated-alias')
        if not path.is_file():
            continue
        require(len(rows) < 256, 'c-abi-generated-count')
        row = identity(path, 1024*1024)
        total += row['bytes']
        require(total <= 16*1024*1024, 'c-abi-generated-total')
        rows[path.relative_to(directory).as_posix()] = row
    return rows


def libc_errno_inputs(lib):
    rows = {name:identity(lib/name,8192) for name in LIBC_ERRNO_SOURCES}
    require(all(row['sha256'] == LIBC_ERRNO_SOURCES[name] for name,row in rows.items()),
            'c-abi-original-libc-errno-preimages')
    return rows


def execute(output, tools):
    require(sys.platform == 'linux' and not output.exists() and not output.is_symlink(),
            'c-abi-fresh-owned-linux-output')
    output.mkdir(parents=True, mode=0o700)
    (output/'temporary').mkdir(mode=0o700)
    before = sources()
    original_tools = {name:identity(path) for name,path in tools.items()}
    environment = build_environment(output/'temporary')
    environment.update(ZIG_GLOBAL_CACHE_DIR=str(output/'zig-global'),
                       ZIG_LOCAL_CACHE_DIR=str(output/'zig-local'))
    deadline, used, primary = time.monotonic()+360, 0, False
    generated_before, libc_before, lib = None, None, None
    report = {'schemaVersion':'latent.c.canonical-abi-source-control.v1', 'status':'failed',
              'source':before, 'tools':original_tools, 'commands':[], 'selectedCLinks':0,
              'actualGeneratedCAbiExecuted':False, 'actualComponentGraphAuthenticated':False,
              'canonicalChildCreated':False, 'nativeRuntimeExecuted':False,
              'pthreadProfileQualified':False, 'hermetic':False,
              'compilerImplicitInputsAttested':False}

    def command(args, stage, timeout=60):
        nonlocal used
        remaining = deadline-time.monotonic()
        require(remaining > 0 and used < 16*1024*1024 and len(report['commands']) < 24,
                'c-abi-command-envelope')
        ordinal = len(report['commands'])
        row = {'stage':stage, 'program':Path(args[0]).name}
        report['commands'].append(row)
        report['currentStage'] = stage
        started = time.monotonic()
        try:
            result = run_bounded_result([str(x) for x in args], ROOT, environment,
                                       min(remaining,timeout),16*1024*1024-used)
        except BaseException:
            report['failedStage'] = stage
            raise
        used += len(result.stdout)+len(result.stderr)
        # A returned bounded result positively follows owner.finish and both
        # streams' drain. No such fields are invented on timeout/overflow.
        row.update(exitCode=result.returncode, elapsedSeconds=time.monotonic()-started,
                   completed=True, descendantsCleaned=True)
        try:
            for stream in ('stdout','stderr'):
                (output/f'{ordinal:02}-{stage}.{stream}.txt').write_bytes(getattr(result,stream))
        except OSError:
            row['logRetentionRefused'] = True
            if result.returncode == 0:
                raise
        if result.returncode != 0:
            report['failedStage'] = stage
        require(result.returncode == 0, 'c-abi-command-failed:'+stage)
        return result.stdout

    def generated_run(tool, *args):
        return command([tools[tool],*args], 'bindings').decode('utf-8')

    try:
        require(command([tools['zig'],'version'],'zig-version').strip() == b'0.16.0', 'c-abi-zig-version')
        require(command([tools['wit-bindgen'],'--version'],'bindgen-version').strip() == b'wit-bindgen-cli 0.62.0', 'c-abi-bindgen-version')
        require(command([tools['wasm-tools'],'--version'],'wasm-version').strip().split()[:2] == [b'wasm-tools',b'1.254.0'], 'c-abi-wasm-version')
        require(command([tools['node'],'--version'],'node-version').strip() == b'v24.19.0', 'c-abi-node-version')
        generated, lock = generate(generated_run, ROOT/FIXTURE, WORLD, output/'generated', ROOT/'wit/platform')
        report['bindings'] = lock
        (output/'bindings.json').write_text(json.dumps(lock,indent=2)+'\n')
        generated_before = tree(output/'generated')
        graph = json.loads(command([tools['wasm-tools'],'component','wit','--json',output/'generated/wit'], 'source-wit'))
        expected_public = public_contract(graph)
        public_index = next(iter(graph['worlds'][0]['exports'].values()))['interface']['id']
        # Adverse projections are derived from the actual parsed source world.
        for name, mutation in [('unknown-export', lambda g: g['worlds'][0]['exports'].update(other={})),
                               ('async-export', lambda g: g['interfaces'][public_index]['functions']['greet'].update(kind='async-freestanding'))]:
            changed = copy.deepcopy(graph); mutation(changed)
            try:
                public_contract(changed)
            except ValueError:
                pass
            else:
                raise ValueError('c-abi-adverse-public-contract-not-refused:'+name)
        report['publicContractAdverseControls'] = 2
        directories = re.findall(r'^\s*\.lib_dir = ("(?:[^"\\]|\\.)*"),$',
                                 command([tools['zig'],'env'],'zig-env').decode('utf-8'), re.MULTILINE)
        require(len(directories) == 1, 'c-abi-zig-lib-directory')
        lib = Path(json.loads(directories[0]))
        libc_before = libc_errno_inputs(lib)
        report['originalLibcErrnoInputs'] = libc_before
        report['errnoOwner'] = 'original-linked-wasi-libc-tls'
        headers = [lib/'libc/include/wasm-wasi-musl', lib/'libc/include/generic-musl']
        report['explicitWasiHeaders'] = header_identity(headers)
        flags = [value for path in headers for value in ('-isystem',str(path))]
        exports = ('__stack_pointer','__tls_base','__data_end','__heap_base','__stack_low',
                   '__wasm_call_ctors','__indirect_function_table','__lsf_c_thread_body',
                   '__lsf_c_root_initialize','__lsf_c_root_finish')
        link = [tools['zig'],'cc','-target','wasm32-wasi','-std=c11','-O2','-g0',
                '-Wall','-Wextra','-Werror','-matomics','-mbulk-memory','-pthread',
                '-DLSF_C_LINKED_LIBC=1',
                '-mexec-model=reactor',*flags,'-I',generated,
                ROOT/(FIXTURE+'probe.c'), ROOT/'sdk/c-guest/runtime/threads.c',
                ROOT/'sdk/c-guest/runtime/tls-keys.c', ROOT/'sdk/c-guest/src/trap.c',
                generated/'probe.c', generated/'probe_component_type.o',
                '-Wl,--no-entry','-Wl,--export-memory',
                '-Wl,-z,stack-size=69632','-Wl,--max-memory=4194304',
                *['-Wl,--export='+name for name in exports],'-o',output/'original.wasm']
        report['selectedCLinks'] = 1
        command(link, 'selected-c-link', 180)
        original = identity(output/'original.wasm',8*1024*1024)
        report['originalCore'] = original
        command([tools['transformer'],'--canonical-abi', output/'original.wasm',
                 'sha256:'+original['sha256'],EXPORT,output/'selected'],'canonical-abi')
        command([tools['wasm-tools'],'component','new',output/'selected/core.wasm',
                 '-o',output/'component.wasm'],'normal-component-new')
        command([tools['wasm-tools'],'validate','--features','cm-threading,cm-async-stackful',
                 output/'component.wasm'],'validate-component')
        actual = json.loads(command([tools['wasm-tools'],'component','wit','--json',
                                     output/'component.wasm'],'final-wit'))
        require(public_contract(actual) == expected_public, 'c-abi-final-public-contract-changed')
        command([tools['transformer'],'--verify-canonical-component',output/'original.wasm',
                 output/'component.wasm',EXPORT,output/'component-proof.json'],'actual-component-proof')
        proof = json.loads((output/'component-proof.json').read_text())
        require(proof['actualComponentGraphAuthenticated'] is True
                and proof['canonicalCreationEnabled'] is False and proof['standardRuntimeQualified'] is False,
                'c-abi-proof-scope')
        report['actualComponentGraphAuthenticated'] = True
        control = json.loads(command([tools['node'],'--max-old-space-size=128',
            ROOT/(FIXTURE+'control.cjs'),output/'selected/core.wasm',output/'selected/receipt.json'],'actual-core-abi'))
        require(control['status'] == 'passed' and control['negativeControls'] == 6
                and control['actualGeneratedCAbiExecuted'] is True and control['canonicalChildCreated'] is False
                and control['nativeRuntimeExecuted'] is False and control['pthreadProfileQualified'] is False,
                'c-abi-real-core-control')
        report['actualGeneratedCAbiExecuted'] = True
        report['coreControl'] = control
        report['generatedInputsUnchanged'] = generated_before == tree(output/'generated')
        require(report['generatedInputsUnchanged'], 'c-abi-generated-inputs-changed')
        report['products'] = {name:identity(output/name,8*1024*1024) for name in
                              ('original.wasm','selected/core.wasm','selected/receipt.json',
                               'component.wasm','component-proof.json','bindings.json')}
        report['status'] = 'passed'
    except BaseException:
        primary = True
        raise
    finally:
        try:
            try:
                report['sourceUnchanged'] = before == sources()
                report['toolsUnchanged'] = original_tools == {name:identity(path) for name,path in tools.items()}
                report['generatedInputsUnchanged'] = (None if generated_before is None else
                                                      generated_before == tree(output/'generated'))
                report['libcErrnoInputsUnchanged'] = (None if libc_before is None else
                                                    libc_before == libc_errno_inputs(lib))
            except (OSError, ValueError):
                report['inputFenceObservationRefused'] = True
                report['status'] = 'failed'
            if (not report.get('sourceUnchanged') or not report.get('toolsUnchanged')
                    or report.get('generatedInputsUnchanged') is False
                    or report.get('libcErrnoInputsUnchanged') is False):
                report['status'] = 'failed'
            (output/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
            if not primary:
                require(report['status'] == 'passed', 'c-abi-final-input-fence')
        except BaseException:
            if not primary:
                raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for tool in ('zig','wit-bindgen','wasm-tools','transformer','node'):
        parser.add_argument('--'+tool, type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tools = {name:Path(getattr(args,name.replace('-','_'))).resolve(strict=True)
             for name in ('zig','wit-bindgen','wasm-tools','transformer','node')}
    result = execute(args.output.resolve(), tools)
    print(json.dumps({'status':result['status'],'selectedCLinks':1,
                      'canonicalChildCreated':False,'pthreadProfileQualified':False}))


if __name__ == '__main__':
    main()
