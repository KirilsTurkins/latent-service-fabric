"""Execute a pinned C/core-Wasm mechanism control, never a pthread profile claim."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import run_bounded_result
from tools.dev_workflow.common import require

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = 'sdk/c-guest/runtime-fixtures/context-lowering/'
SOURCES = ('tools/qualify_c_context_lowering.py', FIXTURE+'probe.c', FIXTURE+'control.cjs',
    FIXTURE+'tls-keys.c', FIXTURE+'tls-keys.cjs', 'sdk/c-guest/runtime/tls-keys.c',
    'crates/latent-component-threading/src/c_context.rs',
    'crates/latent-component-threading/src/bin/c-context.rs',
    'crates/latent-component-threading/src/lib.rs',
    'crates/latent-component-threading/Cargo.toml', 'Cargo.toml', 'Cargo.lock')


def identity(path, maximum=256*1024*1024, allow_empty=False):
    require(path.is_file() and not path.is_symlink() and (0 if allow_empty else 1) <= path.stat().st_size <= maximum,
            'c-context-ordinary-input-bound')
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256':value, 'bytes':path.stat().st_size}


def header_identity(roots):
    rows = {}
    total = 0
    for root in roots:
        require(root.is_dir() and not root.is_symlink(), 'c-context-wasi-header-directory')
        for path in sorted(root.rglob('*')):
            require(not path.is_symlink(), 'c-context-wasi-header-alias')
            if not path.is_file():
                continue
            require(len(rows) < 4096, 'c-context-wasi-header-count')
            selected = identity(path,1024*1024,allow_empty=True)
            total += selected['bytes']
            require(total <= 16*1024*1024, 'c-context-wasi-header-bytes')
            rows[root.name+'/'+path.relative_to(root).as_posix()] = selected
    require(bool(rows), 'c-context-wasi-headers-empty')
    raw = json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
    return {'sha256':hashlib.sha256(raw).hexdigest(),'files':len(rows),'bytes':total,
            'scope':'explicit-wasm-wasi-musl-and-generic-musl-headers',
            'compilerImplicitInputsAttested':False}


def run(output, zig, transformer, node):
    require(not output.exists() and not output.is_symlink(), 'c-context-fresh-output')
    output.mkdir(parents=True, mode=0o700)
    original = {name:identity(ROOT/name, 16*1024*1024) for name in SOURCES}
    tools = {name:identity(path) for name,path in [('zig',zig),('transformer',transformer),('node',node)]}
    environment = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output/'zig-global'),
                       ZIG_LOCAL_CACHE_DIR=str(output/'zig-local'))
    deadline, used = time.monotonic()+180, 0
    report = {'schemaVersion':'latent.c.compiler-context-control.v1', 'status':'failed',
        'source':original, 'tools':tools, 'commands':[], 'actualCompiledCoreExecuted':False,
        'canonicalChildCreated':False, 'nativeRuntimeExecuted':False,
        'pthreadProfileQualified':False, 'bootstrapOrAdmissionQualified':False,
        'atomicMemoryModelQualified':False, 'hermetic':False}
    def command(args, expected=None):
        nonlocal used
        remaining = deadline-time.monotonic()
        require(remaining>0 and used<4*1024*1024, 'c-context-command-bound')
        result = run_bounded_result([str(x) for x in args], ROOT, environment,
                                   min(remaining,60), 4*1024*1024-used)
        used += len(result.stdout)+len(result.stderr)
        ordinal = len(report['commands'])
        for stream in ('stdout','stderr'):
            (output/f'{ordinal:02}.{stream}.txt').write_bytes(getattr(result,stream))
        report['commands'].append({'program':Path(args[0]).name,'exitCode':result.returncode})
        if expected is None:
            require(result.returncode==0, 'c-context-command-failed')
        else:
            require(result.returncode!=0 and result.stderr.strip()==expected,
                    'c-context-unselected-lowering-not-refused')
        return result.stdout
    try:
        require(command([zig,'version']).strip()==b'0.16.0', 'c-context-pinned-zig')
        require(command([zig,'cc','--version']).startswith(b'clang version 21.1.0'), 'c-context-pinned-clang')
        require(command([node,'--version']).strip()==b'v24.19.0', 'c-context-pinned-node')
        options = ['cc','-target','wasm32-wasi','-std=c11','-O2','-g0','-Wall','-Wextra','-Werror']
        selected = ['-matomics','-mbulk-memory','-pthread']
        link = ['-nostdlib','-Wl,--no-entry','-Wl,--export-memory',
            '-Wl,--export=__stack_pointer','-Wl,--export=__tls_base','-Wl,--export=__data_end',
            '-Wl,-z,stack-size=65536','-Wl,--max-memory=4194304']
        source = ROOT/(FIXTURE+'probe.c')
        for name, flags in [('selected',selected),('ordinary-static',[])]:
            selected_link = link if name=='selected' else [value for value in link if value!='-Wl,--export=__tls_base']
            command([zig,*options,*flags,source,*selected_link,'-o',output/(name+'.wasm')])
        # Zig's -S driver injects an unused -c argument; only that driver warning
        # is disabled for this observation. All C diagnostic errors stay fatal.
        command([zig,*options,*selected,'-S','-emit-llvm','-Wno-unused-command-line-argument',
                 source,'-o',output/'selected.ll'])
        for name in ('selected','ordinary-static'):
            preimage = identity(output/(name+'.wasm'))
            command([transformer,output/(name+'.wasm'),'sha256:'+preimage['sha256'],output/name],
                None if name=='selected' else b'C context source mechanism refused: c-context-tls-base-export-missing')
        actual = json.loads(command([node,'--max-old-space-size=128',ROOT/(FIXTURE+'control.cjs'),
            output/'selected.wasm',output/'selected/core.wasm',output/'selected/receipt.json']))
        require(actual['status']=='passed' and actual['originalControlRejected'] is True
            and actual['actualCompiledCoreExecuted'] is True and actual['callbackReentrancyControl'] is True
            and actual['negativeControls']==6 and len(actual['records'])==4
            and actual['canonicalChildCreated'] is False and actual['nativeRuntimeExecuted'] is False
            and actual['pthreadProfileQualified'] is False, 'c-context-control-result')
        report['actualCompiledCoreExecuted'] = True
        report['control'] = actual
        # Explicitly selected WASI-musl headers only; no libc implementation or
        # thread stubs are linked. These pinned headers are material inputs.
        zig_environment = command([zig,'env']).decode('utf8')
        directories = re.findall(r'^\s*\.lib_dir = ("(?:[^"\\]|\\.)*"),$',zig_environment,re.MULTILINE)
        require(len(directories)==1, 'c-context-pinned-zig-lib-directory')
        zig_lib = Path(json.loads(directories[0]))
        header_roots = [zig_lib/'libc/include/wasm-wasi-musl',
                        zig_lib/'libc/include/generic-musl']
        require(all(path.is_dir() and not path.is_symlink() for path in header_roots),
                'c-context-pinned-wasi-header-directories')
        headers = header_identity(header_roots)
        report['wasiHeaders'] = headers
        header_flags = [flag for path in header_roots for flag in ('-isystem',str(path))]
        key_sources = [ROOT/(FIXTURE+'tls-keys.c'), ROOT/'sdk/c-guest/runtime/tls-keys.c']
        command([zig,*options,*selected,*header_flags,*key_sources,*link,
                 '-o',output/'tls-keys.wasm'])
        preimage = identity(output/'tls-keys.wasm')
        command([transformer,output/'tls-keys.wasm','sha256:'+preimage['sha256'],output/'tls-keys'])
        tls_keys = json.loads(command([node,'--max-old-space-size=128',ROOT/(FIXTURE+'tls-keys.cjs'),
            output/'tls-keys/core.wasm',output/'tls-keys/receipt.json']))
        require(tls_keys == {'schemaVersion':'latent.c.tls-key-control.v1','status':'passed',
            'actualCompiledCoreExecuted':True,'contextErrnoIsolation':True,'staleKeyRefusal':True,
            'keyLimit':128,'destructorPassLimit':4,'cyclicPendingRetained':True,
            'clearBeforeDestructor':True,'reentryRefused':True,'canonicalChildCreated':False,
            'nativeRuntimeExecuted':False,'pthreadProfileQualified':False}, 'c-context-tls-key-control-result')
        report['tlsKeys'] = tls_keys
        require(header_identity(header_roots)==headers, 'c-context-wasi-headers-changed')
        require({name:identity(ROOT/name,16*1024*1024) for name in SOURCES}==original,
                'c-context-source-changed')
        require({name:identity(path) for name,path in [('zig',zig),('transformer',transformer),('node',node)]}==tools,
                'c-context-tool-changed')
        report['products'] = {name:identity(output/name) for name in
            ('selected.wasm','ordinary-static.wasm','selected.ll','selected/core.wasm','selected/receipt.json',
             'tls-keys.wasm','tls-keys/core.wasm','tls-keys/receipt.json')}
        report['status']='passed'
        return report
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8',newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output','zig','transformer','node'): parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    result = run(args.output.absolute(),args.zig.resolve(strict=True),
                 args.transformer.resolve(strict=True),args.node.resolve(strict=True))
    print(json.dumps({'status':result['status'],'actualCompiledCoreExecuted':True,'pthreadProfileQualified':False}))


if __name__ == '__main__': main()
