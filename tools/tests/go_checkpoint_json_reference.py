"""Pinned core-Wasm JSON scanner control; no signed guest or host imports."""
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
SOURCE_SHA256 = '2ec579bfd801743cb8073f89d35c1f5540811e435b53793b2732cf57423e2eaa'
RECORD = re.compile(rb'sibling=(true|false) valid=true yields=([0-9]+)\n\Z')


def run(command, env, cwd, timeout=180):
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError('json-reference-command:' + str(command[0]) + ':' +
                         result.stderr[-4096:].decode('utf-8', errors='replace'))
    return result.stdout


def reference(go, node):
    go, node = Path(go).resolve(strict=True), Path(node).resolve(strict=True)
    if hashlib.sha256(go.read_bytes()).hexdigest() != GO_SHA256:
        raise ValueError('json-reference-go-drift')
    if hashlib.sha256(node.read_bytes()).hexdigest() != NODE_SHA256:
        raise ValueError('json-reference-node-drift')
    env = dict(os.environ, GOENV='off', GOWORK='off', GOTOOLCHAIN='local', GOFLAGS='',
               CGO_ENABLED='0', GOPROXY='off', GOSUMDB='off', GOMAXPROCS='1', GOGC='off')
    for name in ('GOROOT', 'GOOS', 'GOARCH'):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix='go-checkpoint-json-') as temporary:
        root = Path(temporary)
        env['GOCACHE'] = str(root/'cache')
        if run([str(go), 'version'], env, root).strip() != b'go version go1.27.4 linux/amd64':
            raise ValueError('json-reference-go-version')
        if run([str(node), '--version'], env, root).strip() != b'v24.19.0':
            raise ValueError('json-reference-node-version')
        goroot = Path(run([str(go), 'env', 'GOROOT'], env, root).decode().strip())
        original = goroot/'src/encoding/json/internal/jsonwire/decode.go'
        if (checkpoints.STANDARD_JSON_WIRE_SHA256 != SOURCE_SHA256 or
                hashlib.sha256(original.read_bytes()).hexdigest() != SOURCE_SHA256):
            raise ValueError('json-reference-standard-source-drift')
        parser_source = root/'checkpoint-parser.go'
        parser_source.write_bytes((ROOT/'sdk/go-guest/runtime/checkpoint_transform.go.in').read_bytes())
        parser = root/'checkpoint-parser'
        run([str(go), 'build', '-p=1', '-o', str(parser), str(parser_source)], env, root)
        generated = root/'module'; generated.mkdir()
        output = root/'selection'; output.mkdir()
        def selected(_label, _tool, request, destination):
            return run([str(parser), str(request), str(destination)], env, root).decode()
        discovery = dict(env, GOOS='wasip1', GOARCH='wasm')
        names = ('encoding/json/internal/jsonwire', 'strings', 'bytes', 'maps', 'slices')
        packages = [json.loads(run([str(go), 'list', '-json', name], discovery, root)) for name in names]
        replacements, rows = checkpoints.transform(SimpleNamespace(run=selected, goroot=goroot),
                                                    generated, packages, set(), output)
        expected = {'encoding/json/internal/jsonwire/decode.go', 'strings/iter.go', 'bytes/iter.go',
                    'maps/iter.go', 'slices/iter.go'}
        if (len(rows) != len(expected) or set(replacements) != {str(goroot/'src'/path) for path in expected}
                or {row['name'] for row in rows} != {'go-compiler-checkpoints/standard/'+path for path in expected}):
            raise ValueError('json-reference-selection')
        json_row = next(row for row in rows if row['name'].endswith('/jsonwire/decode.go'))

        # The scheduler patch and bridge are production source. Activation and
        # the queue pump are finite test doubles, not a real LSF host.
        names = [name for name in runtime.UPSTREAM_PREIMAGES
                 if name.startswith('runtime/lock_') or name in {
                     'runtime/proc.go', 'runtime/os_wasm.go', 'runtime/debug.go'}]
        sources = runtime.checked_sources(goroot, {name: runtime.UPSTREAM_PREIMAGES[name] for name in names})
        runtime.install_scheduler(sources)
        if any(hashlib.sha256(text.encode()).hexdigest() != runtime.PREIMAGES[name]
               for name, text in sources.items()):
            raise ValueError('json-reference-scheduler-drift')
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
                         b'//go:linkname lsfJsonControlEnable\n'
                         b'func lsfJsonControlEnable(){ lsfActivationActive=true }\n' + bridge)
        (generated/'go.mod').write_text('module example.invalid/jsoncheckpoint\n\ngo 1.27.4\n')
        (generated/'main.go').write_bytes((ROOT/'tools/tests/fixtures/go-checkpoint-json/main.go.txt').read_bytes())
        (generated/'dispatch').mkdir()
        (generated/'dispatch/dispatch.go').write_bytes(b'''package dispatch
import ("runtime"; "sync/atomic"; _ "unsafe")
type unit struct{}
type taskState struct { yielding *lsfYieldWait; yieldTail *lsfYieldWait }
var state = &taskState{}
var yielded atomic.Uint64
//go:linkname Enable runtime.lsfJsonControlEnable
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
const wasi = new WASI({version:'preview1',args:['json',...process.argv.slice(3)],env:{GOGC:'off'}});
const {instance} = await WebAssembly.instantiate(await readFile(process.argv[2]),{wasi_snapshot_preview1:wasi.wasiImport});
wasi.start(instance);
''')
        env.update(GOOS='wasip1', GOARCH='wasm')
        outcomes, binaries = {}, {}
        for label, additions in [('baseline', {}), ('json-only', {str(original): replacements[str(original)]}),
                                 ('all-selected', replacements)]:
            overlay = root/(label+'-overlay.json')
            overlay.write_text(json.dumps({'Replace': {**base, **additions}}))
            wasm = root/(label+'.wasm')
            run([str(go), 'build', '-p=1', '-overlay', str(overlay), '-o', str(wasm), '.'], env, generated, 300)
            binaries[label] = wasm
            if run([str(node), '--no-warnings', str(runner), str(wasm), 'semantics'], env, root, 30) != b'semantics=ok\n':
                raise ValueError('json-reference-semantics')
            outcomes[label] = {}
            for mode in ('sibling', 'alone'):
                raw = run([str(node), '--no-warnings', str(runner), str(wasm), mode], env, root, 30)
                match = RECORD.fullmatch(raw)
                if not match:
                    raise ValueError('json-reference-output')
                sibling, yields = match[1] == b'true', int(match[2])
                if (sibling != (label != 'baseline' and mode == 'sibling') or
                        (label == 'baseline' and yields) or (label != 'baseline' and not 1000 <= yields <= 3000)):
                    raise ValueError('json-reference-progress:' + label + ':' + mode + ':' + repr(raw))
                outcomes[label][mode] = {'siblingBeforeReturn': sibling, 'checkpointYields': yields}
        samples = {'baseline': [], 'json-only': []}
        cpu = {'baseline': [], 'json-only': []}
        # The previous runs warm both variants. Alternate four additional runs;
        # process startup is included and these are not production measurements.
        for round_ in range(4):
            labels = ('baseline', 'json-only') if round_ % 2 == 0 else ('json-only', 'baseline')
            for label in labels:
                prior = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter_ns()
                raw = run([str(node), '--no-warnings', str(runner), str(binaries[label]), 'alone'], env, root, 30)
                elapsed = time.perf_counter_ns() - start
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                match = RECORD.fullmatch(raw)
                if not match or match[1] != b'false':
                    raise ValueError('json-reference-cost-output')
                samples[label].append(elapsed / 1_000_000)
                cpu[label].append(1000 * ((after.ru_utime + after.ru_stime) - (prior.ru_utime + prior.ru_stime)))
        cost = {label: {'elapsedMedianMs': round(statistics.median(samples[label]), 2),
                        'childCpuMedianMs': round(statistics.median(cpu[label]), 2)} for label in samples}
        return {'scope': 'pinned-core-wasm-with-test-activation-and-queue-pump', 'signedGuestExecuted': False,
                'source': SOURCE_SHA256, 'sites': json_row['sites'], 'outcomes': outcomes,
                'noSiblingCost': cost, 'costIncludesProcessStartup': True}


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('--go', required=True)
    cli.add_argument('--node', required=True)
    args = cli.parse_args()
    print(json.dumps(reference(args.go, args.node), sort_keys=True))
