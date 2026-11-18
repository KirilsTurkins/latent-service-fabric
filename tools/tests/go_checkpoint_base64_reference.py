"""Pinned Go reference and core-Wasm encoder progress; no signed guest claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.go_guest import checkpoints, runtime

ROOT = Path(__file__).resolve().parents[2]
GO_SHA256 = 'de0ae3e082ce7599eae4fb69fa2ef1e43b8f31ffd3fce62cdf81930aa9005050'
NODE_SHA256 = 'bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12'
RECORD = re.compile(rb'sibling=(true|false) bytes=33554432 yields=([0-9]+)\n\Z')
SEMANTICS = re.compile(rb'semantics=ok yields=([0-9]+)\n\Z')


def run(command, env, cwd, timeout=300):
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError('base64-reference-command:' + str(command[0]) + ':' +
                         result.stderr[-4096:].decode('utf-8', errors='replace'))
    return result.stdout


def semantics_yields(raw, expected_yield):
    match = SEMANTICS.fullmatch(raw)
    if not match or (int(match[1]) > 0) != expected_yield:
        raise ValueError('base64-reference-semantics:' + repr(raw))
    return int(match[1])


def reference(go, node):
    go, node = Path(go).resolve(strict=True), Path(node).resolve(strict=True)
    if hashlib.sha256(go.read_bytes()).hexdigest() != GO_SHA256:
        raise ValueError('base64-reference-go-drift')
    if hashlib.sha256(node.read_bytes()).hexdigest() != NODE_SHA256:
        raise ValueError('base64-reference-node-drift')
    env = dict(os.environ, GOENV='off', GOWORK='off', GOTOOLCHAIN='local', GOFLAGS='',
               CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off', GOMAXPROCS='1', GOGC='off')
    for name in ('GOROOT', 'GOOS', 'GOARCH'):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix='go-checkpoint-base64-') as temporary:
        root = Path(temporary)
        env['GOCACHE'] = os.environ.get('GOCACHE', str(root/'cache'))
        if run([str(go), 'version'], env, root).strip() != b'go version go1.27.4 linux/amd64':
            raise ValueError('base64-reference-go-version')
        if run([str(node), '--version'], env, root).strip() != b'v24.19.0':
            raise ValueError('base64-reference-node-version')
        goroot = Path(run([str(go), 'env', 'GOROOT'], env, root).decode().strip())
        original = goroot/'src'/checkpoints.STANDARD_BASE64
        if hashlib.sha256(original.read_bytes()).hexdigest() != checkpoints.STANDARD_BASE64_SHA256:
            raise ValueError('base64-reference-standard-source-drift')

        parser_source = root/'checkpoint-parser.go'
        parser_source.write_bytes((ROOT/'sdk/go-guest/runtime/checkpoint_transform.go.in').read_bytes())
        parser = root/'checkpoint-parser'
        run([str(go), 'build', '-p=1', '-o', str(parser), str(parser_source)], env, root)
        generated = root/'module'; generated.mkdir()
        output = root/'selection'; output.mkdir()
        def selected(_label, _tool, request, destination):
            return run([str(parser), str(request), str(destination)], env, root).decode()
        discovery = dict(env, GOOS='wasip1', GOARCH='wasm')
        package = json.loads(run([str(go), 'list', '-json', 'encoding/base64'], discovery, root))
        replacements, rows = checkpoints.transform(SimpleNamespace(run=selected, goroot=goroot),
                                                    generated, [package], set(), output)
        expected_site = {'line': 154, 'column': 21, 'suspendable': True, 'stride': 256}
        if (set(replacements) != {str(original)} or len(rows) != 1 or rows[0]['sites'] != [expected_site]):
            raise ValueError('base64-reference-selection')

        names = [name for name in runtime.UPSTREAM_PREIMAGES if name.startswith('runtime/lock_') or name in {
            'runtime/proc.go', 'runtime/os_wasm.go', 'runtime/debug.go'}]
        sources = runtime.checked_sources(goroot, {name: runtime.UPSTREAM_PREIMAGES[name] for name in names})
        runtime.install_scheduler(sources)
        if any(hashlib.sha256(text.encode()).hexdigest() != runtime.PREIMAGES[name]
               for name, text in sources.items()):
            raise ValueError('base64-reference-scheduler-drift')
        (root/'scheduler').mkdir()
        base = {}
        for name, text in sources.items():
            target = root/'scheduler'/name.replace('/', '_')
            target.write_text(text, encoding='utf-8', newline='\n')
            base[str(goroot/'src'/name)] = str(target)
        proc = Path(base[str(goroot/'src/runtime/proc.go')])
        proc.write_bytes(proc.read_bytes() + b'\nvar lsfActivationActive bool\n'
                         b'//go:linkname lsfBase64ControlEnable\n'
                         b'func lsfBase64ControlEnable(){ lsfActivationActive=true }\n' +
                         (ROOT/'sdk/go-guest/runtime/checkpoint_bridge.go.in').read_bytes())
        (generated/'go.mod').write_text('module example.invalid/base64checkpoint\n\ngo 1.27.4\n')
        (generated/'main.go').write_bytes((ROOT/'tools/tests/fixtures/go-checkpoint-base64/main.go.txt').read_bytes())
        (generated/'dispatch').mkdir()
        dispatch = generated/'dispatch/dispatch.go'
        dispatch.write_text('package dispatch\nfunc Enable() {}\nfunc Count() uint64 { return 0 }\n')
        native = root/'native'
        run([str(go), 'build', '-p=1', '-o', str(native), '.'], env, generated)
        semantics_yields(run([str(native), 'semantics'], env, root), False)
        native_output = run([str(native), 'sibling'], env, root)
        match = RECORD.fullmatch(native_output)
        if not match or int(match[2]) != 0:
            raise ValueError('base64-reference-native-progress:' + repr(native_output))
        native_sibling = match[1] == b'true'

        dispatch.write_bytes(b'''package dispatch
import ("runtime"; "sync/atomic"; _ "unsafe")
type unit struct{}
type taskState struct { yielding *lsfYieldWait; yieldTail *lsfYieldWait }
var state = &taskState{}
var yielded atomic.Uint64
//go:linkname Enable runtime.lsfBase64ControlEnable
func Enable()
''' + (ROOT/'sdk/go-guest/runtime/checkpoint_async.go.in').read_bytes() + b'''
func Count() uint64 { return yielded.Load() }
func init() { go func() {
    for {
        current := lsfTakeYields()
        if current == nil { runtime.Gosched(); continue }
        for current != nil { next := current.next; current.next = nil; yielded.Add(1); current.channel <- unit{}; current = next }
    }
}() }
''')
        runner = root/'wasi.mjs'
        runner.write_text('''import {readFile} from 'node:fs/promises';
import {WASI} from 'node:wasi';
const wasi=new WASI({version:'preview1',args:['base64',...process.argv.slice(3)],env:{GOGC:'off'}});
const {instance}=await WebAssembly.instantiate(await readFile(process.argv[2]),{wasi_snapshot_preview1:wasi.wasiImport});
wasi.start(instance);
''')
        wasm_env = dict(env, GOOS='wasip1', GOARCH='wasm')
        outcomes, binaries = {}, {}
        for name, additions in [('baseline', {}), ('selected', replacements)]:
            overlay = root/(name+'-overlay.json')
            overlay.write_text(json.dumps({'Replace': {**base, **additions}}))
            wasm = root/(name+'.wasm')
            run([str(go), 'build', '-p=1', '-overlay', str(overlay), '-o', str(wasm), '.'], wasm_env, generated)
            binaries[name] = wasm
            semantics = run([str(node), '--no-warnings', str(runner), str(wasm), 'semantics'], env, root)
            outcomes[name] = {'semanticYields': semantics_yields(semantics, name == 'selected')}
            for mode in ('sibling', 'alone'):
                raw = run([str(node), '--no-warnings', str(runner), str(wasm), mode], env, root)
                match = RECORD.fullmatch(raw)
                if (not match or (match[1] == b'true') != (name == 'selected' and mode == 'sibling')
                        or int(match[2]) != (32 if name == 'selected' else 0)):
                    raise ValueError('base64-reference-progress:' + name + ':' + mode + ':' + repr(raw))
                outcomes[name][mode] = {'siblingBeforeReturn': match[1] == b'true',
                                        'checkpointYields': int(match[2])}

        elapsed = {name: [] for name in binaries}
        cpu = {name: [] for name in binaries}
        for index in range(4):
            for name in (('baseline', 'selected') if index % 2 == 0 else ('selected', 'baseline')):
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter_ns()
                raw = run([str(node), '--no-warnings', str(runner), str(binaries[name]), 'alone'], env, root)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                match = RECORD.fullmatch(raw)
                if not match or match[1] != b'false':
                    raise ValueError('base64-reference-cost-output')
                elapsed[name].append((time.perf_counter_ns()-start)/1_000_000)
                cpu[name].append(1000*((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime)))
        cost = {name: {'elapsedMedianMs': round(statistics.median(elapsed[name]), 2),
                       'childCpuMedianMs': round(statistics.median(cpu[name]), 2)} for name in binaries}
        return {'scope': 'pinned-core-wasm-with-test-activation-and-queue-pump',
                'nativeGoReference': {'siblingBeforeReturn': native_sibling}, 'signedGuestExecuted': False,
                'source': checkpoints.STANDARD_BASE64_SHA256, 'sites': rows[0]['sites'],
                'outcomes': outcomes, 'noSiblingCost': cost, 'costIncludesProcessStartup': True}


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--go', required=True)
    cli.add_argument('--node', required=True)
    args = cli.parse_args()
    print(json.dumps(reference(args.go, args.node), sort_keys=True))
