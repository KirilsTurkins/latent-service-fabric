"""Pinned core-Wasm text-iterator controls; no signed guest or host imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.go_guest import checkpoints, runtime

ROOT = Path(__file__).resolve().parents[2]
GO_SHA256 = 'de0ae3e082ce7599eae4fb69fa2ef1e43b8f31ffd3fce62cdf81930aa9005050'
NODE_SHA256 = 'bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12'
RECORD = re.compile(rb'kind=(strings|bytes) sibling=(true|false) count=1 yields=([0-9]+)\n\Z')


def run(command, environment, cwd, timeout=180):
    result = subprocess.run(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError('text-iterator-reference-command-failed:' + str(command[0]) + ':'
                         + result.stderr[-4096:].decode('utf-8', errors='replace'))
    return result.stdout


def reference(go, node):
    go, node = Path(go).resolve(strict=True), Path(node).resolve(strict=True)
    if hashlib.sha256(go.read_bytes()).hexdigest() != GO_SHA256:
        raise ValueError('text-iterator-reference-go-drift')
    if hashlib.sha256(node.read_bytes()).hexdigest() != NODE_SHA256:
        raise ValueError('text-iterator-reference-node-drift')
    env = dict(os.environ, GOENV='off', GOWORK='off', GOTOOLCHAIN='local', GOFLAGS='',
               CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off', GOMAXPROCS='1', GOGC='off')
    for name in ('GOROOT', 'GOOS', 'GOARCH'):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix='go-checkpoint-text-') as temporary:
        root = Path(temporary)
        env['GOCACHE'] = str(root/'cache')
        if run([str(go), 'version'], env, root).strip() != b'go version go1.27.4 linux/amd64':
            raise ValueError('text-iterator-reference-go-version')
        if run([str(node), '--version'], env, root).strip() != b'v24.19.0':
            raise ValueError('text-iterator-reference-node-version')
        goroot = Path(run([str(go), 'env', 'GOROOT'], env, root).decode().strip())
        standard = {'strings': (checkpoints.STANDARD_STRING_ITERATOR, checkpoints.STANDARD_STRING_ITERATOR_SHA256),
                    'bytes': (checkpoints.STANDARD_BYTES_ITERATOR, checkpoints.STANDARD_BYTES_ITERATOR_SHA256),
                    'maps': (checkpoints.STANDARD_MAP_ITERATOR, checkpoints.STANDARD_MAP_ITERATOR_SHA256),
                    'slices': (checkpoints.STANDARD_ITERATOR, checkpoints.STANDARD_ITERATOR_SHA256)}
        originals = {name: goroot/'src'/path for name, (path, _) in standard.items()}
        if any(hashlib.sha256(originals[name].read_bytes()).hexdigest() != identity
               for name, (_, identity) in standard.items()):
            raise ValueError('text-iterator-reference-standard-source-drift')
        parser_source = root/'checkpoint-parser.go'
        parser_source.write_bytes((ROOT/'sdk/go-guest/runtime/checkpoint_transform.go.in').read_bytes())
        parser = root/'checkpoint-parser'
        run([str(go), 'build', '-p=1', '-o', str(parser), str(parser_source)], env, root)
        generated, output = root/'module', root/'selection'
        generated.mkdir(); output.mkdir()
        def selected(_label, _tool, request, destination):
            return run([str(parser), str(request), str(destination)], env, root).decode()
        discovery = dict(env, GOOS='wasip1', GOARCH='wasm')
        packages = [json.loads(run([str(go), 'list', '-json', name], discovery, root)) for name in standard]
        replacements, records = checkpoints.transform(SimpleNamespace(run=selected, goroot=goroot),
                                                        generated, packages, set(), output)
        if (set(replacements) != {str(path) for path in originals.values()} or len(records) != len(standard)
                or {record['name'] for record in records} != {
                    'go-compiler-checkpoints/standard/'+path for path, _ in standard.values()}):
            raise ValueError('text-iterator-reference-selection')

        # Use the actual scheduler patch and bridge. This explicit activation
        # flag and queue pump are test doubles, with no host calls or settlement.
        names = [name for name in runtime.UPSTREAM_PREIMAGES
                 if name.startswith('runtime/lock_') or name in {
                     'runtime/proc.go', 'runtime/os_wasm.go', 'runtime/debug.go'}]
        sources = runtime.checked_sources(goroot, {name: runtime.UPSTREAM_PREIMAGES[name] for name in names})
        runtime.install_scheduler(sources)
        if any(hashlib.sha256(text.encode()).hexdigest() != runtime.PREIMAGES[name]
               for name, text in sources.items()):
            raise ValueError('text-iterator-reference-scheduler-drift')
        (root/'scheduler').mkdir()
        base = {}
        for name, text in sources.items():
            target = root/'scheduler'/name.replace('/', '_')
            target.write_text(text, encoding='utf-8', newline='\n')
            base[str(goroot/'src'/name)] = str(target)
        proc = Path(base[str(goroot/'src/runtime/proc.go')])
        bridge = (ROOT/'sdk/go-guest/runtime/checkpoint_bridge.go.in').read_bytes()
        dispatcher = (ROOT/'sdk/go-guest/runtime/checkpoint_async.go.in').read_bytes()
        proc.write_bytes(proc.read_bytes() + b'\nvar lsfActivationActive bool\n'
                         b'//go:linkname lsfTextControlEnable\n'
                         b'func lsfTextControlEnable(){ lsfActivationActive=true }\n' + bridge)
        (generated/'go.mod').write_text('module example.invalid/textiterator\n\ngo 1.27.4\n')
        (generated/'main.go').write_bytes((ROOT/'tools/tests/fixtures/go-checkpoint-text/main.go.txt').read_bytes())
        (generated/'dispatch').mkdir()
        (generated/'dispatch/dispatch.go').write_bytes(b'''package dispatch
import ("runtime"; "sync/atomic"; _ "unsafe")
type unit struct{}
type taskState struct { yielding *lsfYieldWait; yieldTail *lsfYieldWait }
var state = &taskState{}
var yielded atomic.Uint64
//go:linkname Enable runtime.lsfTextControlEnable
func Enable()
''' + dispatcher + b'''
func Count() uint64 { return yielded.Load() }
func init() { go func() {
    for {
        node := lsfTakeYields()
        if node == nil { runtime.Gosched(); continue }
        for node != nil {
            next := node.next; node.next = nil
            yielded.Add(1); node.channel <- unit{}; node = next
        }
    }
}() }
''')
        runner = root/'wasi.mjs'
        runner.write_text('''import {readFile} from 'node:fs/promises';
import {WASI} from 'node:wasi';
const wasi = new WASI({version:'preview1',args:['text',...process.argv.slice(3)],env:{GOGC:'off'}});
const {instance} = await WebAssembly.instantiate(await readFile(process.argv[2]),{wasi_snapshot_preview1:wasi.wasiImport});
wasi.start(instance);
''')
        env.update(GOOS='wasip1', GOARCH='wasm')
        profiles = [('baseline', {}),
                    ('strings-only', {str(originals['strings']): replacements[str(originals['strings'])]}),
                    ('bytes-only', {str(originals['bytes']): replacements[str(originals['bytes'])]}),
                    ('text-together', {str(originals[name]): replacements[str(originals[name])]
                                       for name in ('strings', 'bytes')}),
                    ('all-iterators', replacements)]
        outcomes = {}
        for label, additions in profiles:
            overlay = root/(label+'-overlay.json')
            overlay.write_text(json.dumps({'Replace': {**base, **additions}}))
            wasm = root/(label+'.wasm')
            run([str(go), 'build', '-p=1', '-overlay', str(overlay), '-o', str(wasm), '.'], env, generated, 300)
            if run([str(node), '--no-warnings', str(runner), str(wasm), 'semantics'], env, root, 30) != b'semantics=ok\n':
                raise ValueError('text-iterator-reference-semantics')
            outcomes[label] = {}
            for kind in ('strings', 'bytes'):
                enabled = str(originals[kind]) in additions
                for mode in ('sibling', 'alone'):
                    raw = run([str(node), '--no-warnings', str(runner), str(wasm), kind, mode], env, root, 30)
                    match = RECORD.fullmatch(raw)
                    if not match or match[1].decode() != kind:
                        raise ValueError('text-iterator-reference-output')
                    sibling, yields = match[2] == b'true', int(match[3])
                    if (sibling != (enabled and mode == 'sibling') or
                            (not enabled and yields != 0) or (enabled and not 1000 <= yields <= 3000)):
                        raise ValueError('text-iterator-reference-progress-or-cost')
                    outcomes[label][kind+'-'+mode] = {'siblingBeforeReturn': sibling, 'checkpointYields': yields}
        return {'scope': 'pinned-core-wasm-with-test-activation-and-queue-pump', 'signedGuestExecuted': False,
                'standardSources': {name: identity for name, (_, identity) in standard.items()},
                'checkpointSites': {row['name']: len(row['sites']) for row in records}, 'outcomes': outcomes}


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--go', required=True)
    cli.add_argument('--node', required=True)
    args = cli.parse_args()
    print(json.dumps(reference(args.go, args.node), sort_keys=True))
