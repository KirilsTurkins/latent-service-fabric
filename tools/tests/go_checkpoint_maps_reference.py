"""Pinned core-Wasm iterator/checkpoint control; this is not a signed guest run."""
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
RECORD = re.compile(rb'sibling-before-return=(true|false) len=1000000 checkpoint-yields=([0-9]+)\n\Z')


def run(command, env, cwd, timeout=120):
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode != 0:
        raise ValueError('iterator-reference-command-failed:' + str(command[0]) + ':'
                         + result.stderr[-4096:].decode('utf-8', errors='replace'))
    return result.stdout


def reference(go, node):
    go, node = Path(go).resolve(strict=True), Path(node).resolve(strict=True)
    if hashlib.sha256(go.read_bytes()).hexdigest() != GO_SHA256:
        raise ValueError('iterator-reference-go-compiler-drift')
    if hashlib.sha256(node.read_bytes()).hexdigest() != NODE_SHA256:
        raise ValueError('iterator-reference-node-drift')
    env = dict(os.environ, GOENV='off', GOWORK='off', GOTOOLCHAIN='local', GOFLAGS='',
               CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off', GOMAXPROCS='1', GOGC='off')
    env.pop('GOROOT', None)
    env.pop('GOOS', None)
    env.pop('GOARCH', None)
    with tempfile.TemporaryDirectory(prefix='go-checkpoint-maps-') as temporary:
        root = Path(temporary)
        env['GOCACHE'] = str(root/'cache')
        if run([str(go), 'version'], env, root).strip() != b'go version go1.27.4 linux/amd64':
            raise ValueError('iterator-reference-go-version')
        if run([str(node), '--version'], env, root).strip() != b'v24.19.0':
            raise ValueError('iterator-reference-node-version')
        goroot = Path(run([str(go), 'env', 'GOROOT'], env, root).decode().strip())
        maps_source = goroot/'src/maps/iter.go'
        if hashlib.sha256(maps_source.read_bytes()).hexdigest() != 'a803b5b1b09aa2dcedf90db32270f9cec310bc7cf8f141f87c2e6567db0c4208':
            raise ValueError('maps-reference-standard-source-drift')
        original = goroot/'src/slices/iter.go'
        if hashlib.sha256(original.read_bytes()).hexdigest() != checkpoints.STANDARD_ITERATOR_SHA256:
            raise ValueError('iterator-reference-standard-source-drift')

        parser_source = root/'checkpoint-parser.go'
        parser_source.write_bytes((ROOT/'sdk/go-guest/runtime/checkpoint_transform.go.in').read_bytes())
        parser = root/'checkpoint-parser'
        run([str(go), 'build', '-p=1', '-o', str(parser), str(parser_source)], env, root)
        generated, output = root/'module', root/'selection'
        generated.mkdir()
        output.mkdir()
        def selected(_label, _tool, request, destination):
            return run([str(parser), str(request), str(destination)], env, root).decode()
        discovery = dict(env, GOOS='wasip1', GOARCH='wasm')
        packages = [json.loads(run([str(go), 'list', '-json', name], discovery, root))
                    for name in ('slices', 'maps')]
        replacements, records = checkpoints.transform(SimpleNamespace(run=selected, goroot=goroot),
                                                        generated, packages, set(), output)
        records_by_name = {record['name']: record for record in records}
        expected_names = {'go-compiler-checkpoints/standard/slices/iter.go',
                          'go-compiler-checkpoints/standard/maps/iter.go'}
        if (set(replacements) != {str(original), str(maps_source)} or len(records) != 2
                or set(records_by_name) != expected_names):
            raise ValueError('iterator-reference-selection')

        # The actual scheduler patch and both SDK bridge sources are used.
        # The activation flag and queue pump are test doubles; there is no host
        # import, task settlement, production dispatcher or signed execution.
        names = [name for name in runtime.UPSTREAM_PREIMAGES
                 if name.startswith('runtime/lock_') or name in {
                     'runtime/proc.go', 'runtime/os_wasm.go', 'runtime/debug.go'}]
        source = runtime.checked_sources(goroot, {name: runtime.UPSTREAM_PREIMAGES[name] for name in names})
        runtime.install_scheduler(source)
        if any(hashlib.sha256(text.encode()).hexdigest() != runtime.PREIMAGES[name]
               for name, text in source.items()):
            raise ValueError('iterator-reference-scheduler-source-drift')
        (root/'scheduler').mkdir()
        base = {}
        for name, text in source.items():
            target = root/'scheduler'/name.replace('/', '_')
            target.write_text(text, encoding='utf-8', newline='\n')
            base[str(goroot/'src'/name)] = str(target)
        proc = Path(base[str(goroot/'src/runtime/proc.go')])
        bridge = (ROOT/'sdk/go-guest/runtime/checkpoint_bridge.go.in').read_bytes()
        dispatcher = (ROOT/'sdk/go-guest/runtime/checkpoint_async.go.in').read_bytes()
        proc.write_bytes(proc.read_bytes() + b'\nvar lsfActivationActive = true\n' + bridge)
        (generated/'go.mod').write_text('module example.invalid/iteratorbridge\n\ngo 1.27.4\n')
        (generated/'main.go').write_bytes((ROOT/'tools/tests/fixtures/go-checkpoint-maps/main.go.txt').read_bytes())
        (generated/'dispatch').mkdir()
        (generated/'dispatch/dispatch.go').write_bytes(b'''package dispatch
import ("runtime"; "sync/atomic"; _ "unsafe")
type unit struct{}
type taskState struct { yielding *lsfYieldWait; yieldTail *lsfYieldWait }
var state = &taskState{}
var yielded atomic.Uint64
''' + dispatcher + b'''
func Count() uint64 { return yielded.Load() }
func init() { go func() {
    for {
        node := lsfTakeYields()
        if node == nil { runtime.Gosched(); continue }
        for node != nil {
            next := node.next; node.next = nil
            yielded.Add(1)
            node.channel <- unit{}
            node = next
        }
    }
}() }
''')
        runner = root/'wasi.mjs'
        runner.write_text('''import {readFile} from 'node:fs/promises';
import {WASI} from 'node:wasi';
const wasi = new WASI({version:'preview1',args:['iterator',process.argv[3]],env:{GOGC:'off'}});
const {instance} = await WebAssembly.instantiate(await readFile(process.argv[2]),{wasi_snapshot_preview1:wasi.wasiImport});
wasi.start(instance);
''')
        env.update(GOOS='wasip1', GOARCH='wasm')
        outcomes = {}
        profiles = [
            ('baseline', {}),
            ('slices-only', {str(original): replacements[str(original)]}),
            ('maps-only', {str(maps_source): replacements[str(maps_source)]}),
            ('together', replacements),
        ]
        for label, additions in profiles:
            overlay = root/(label+'-overlay.json')
            overlay.write_text(json.dumps({'Replace': {**base, **additions}}))
            wasm = root/(label+'.wasm')
            run([str(go), 'build', '-p=1', '-overlay', str(overlay), '-o', str(wasm), '.'], env, generated)
            outcomes[label] = {}
            for mode in ('sibling', 'alone', 'semantics'):
                output_bytes = run([str(node), '--no-warnings', str(runner), str(wasm), mode], env, root, 20)
                if mode == 'semantics':
                    if output_bytes != b'semantics=ok\n':
                        raise ValueError('iterator-reference-semantics')
                    outcomes[label][mode] = 'ok'
                    continue
                match = RECORD.fullmatch(output_bytes)
                if not match:
                    raise ValueError('iterator-reference-output-shape')
                sibling, yields = match[1] == b'true', int(match[2])
                expected = label in ('maps-only', 'together') and mode == 'sibling'
                if (sibling != expected or label == 'baseline' and yields != 0
                        or label in ('maps-only', 'together') and not 1000 <= yields <= 3000):
                    raise ValueError('iterator-reference-progress-or-cost')
                outcomes[label][mode] = {'siblingBeforeReturn': sibling, 'checkpointYields': yields}
        return {'scope': 'pinned-core-wasm-with-real-checkpoint-bridge-and-test-pump',
                'signedGuestExecuted': False, 'goSha256': GO_SHA256,
                'nodeSha256': NODE_SHA256,
                'standardSources': {'slices': checkpoints.STANDARD_ITERATOR_SHA256,
                                    'maps': checkpoints.STANDARD_MAP_ITERATOR_SHA256},
                'checkpointSites': {name: len(record['sites']) for name, record in records_by_name.items()},
                'outcomes': outcomes}


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--go', required=True)
    cli.add_argument('--node', required=True)
    args = cli.parse_args()
    print(json.dumps(reference(args.go, args.node), sort_keys=True))
