"""Retain actual pinned parser graphs for the explicit SDK fetch source seam."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from tools.typescript_guest import runtime_profile as runtime
from tools.typescript_guest import fetch_profile as fetch
from tools.typescript_guest.clock_engine import derive_clock_world

ROOT = Path(__file__).resolve().parents[4]
SOURCES = ('sdk/typescript-guest/probes/world.wit', 'wit/platform/http-v3/package.wit',
           'wit/platform/activation-runtime/package.wit', 'wit/platform/clock/package.wit')
WORLD = 'lsf:typescript-probe/capsule@1.0.0'


def run(wasm, *arguments):
    return subprocess.run([wasm, *map(str, arguments)], capture_output=True,
                          check=True, timeout=30).stdout


def materialize(root, files):
    for name, raw in files.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def generate(wasm):
    if run(wasm, '--version').split()[:2] != [b'wasm-tools', b'1.254.0']:
        raise ValueError('actual-pinned-parser-required')
    inputs = {name: (ROOT/name).read_bytes() for name in SOURCES}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        def graph(directory):
            return json.loads(run(wasm, 'component', 'wit', directory, '--json'))
        original = root/'original'
        materialize(original, {'world.wit': inputs[SOURCES[0]]})
        before = graph(original)
        canonical = run(wasm, 'component', 'wit', original, '--no-docs')
        http = root/'http'
        materialize(http, {'world.wit': b'package lsf:typescript-fetch-sdk@1.0.0;\nworld sdk-http { import latent:http/streaming@0.3.0; }\n',
                           'deps/http/package.wit': inputs[SOURCES[1]]})
        supplied = graph(http)
        binding = root/'binding'
        materialize(binding, runtime.original_world_sources(
            fetch.binding_world(canonical, before, WORLD, inputs[SOURCES[1]]),
            {'world.wit': inputs[SOURCES[0]]}))
        bound = graph(binding)
        fetch.check_binding_world(before, bound, supplied, WORLD, runtime.scoped_selected_world(WORLD))
        selected = root/'runtime'
        files = derive_clock_world(canonical, before, WORLD, inputs[SOURCES[2]], inputs[SOURCES[3]])
        files = fetch.runtime_world(files, before, WORLD, inputs[SOURCES[1]])
        materialize(selected, runtime.original_world_sources(files, {'world.wit': inputs[SOURCES[0]]}))
        after = graph(selected)
        abi = root/'activation'
        materialize(abi, {'world.wit': b'package lsf:typescript-abi@1.0.0;\nworld abi { import latent:runtime/activation@0.1.0; }\n',
                          'deps/activation/package.wit': inputs[SOURCES[2]]})
        clock = root/'clock'
        materialize(clock, {'world.wit': b'package lsf:clock-abi@1.0.0;\nworld abi { import latent:clock/monotonic@0.1.0; import latent:clock/wall@0.1.0; }\n',
                            'deps/clock/package.wit': inputs[SOURCES[3]]})
        activation, clocks = graph(abi), graph(clock)
        runtime.check_derived_world(bound, after, activation, runtime.scoped_selected_world(WORLD),
                                    selected_world=runtime.scoped_selected_world(WORLD), clock=clocks)
        return {'parser': 'wasm-tools1.254.0',
                'sources': {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()},
                'original': before, 'binding': bound, 'http': supplied,
                'runtime': after, 'activation': activation, 'clock': clocks}


if __name__ == '__main__':
    Path(sys.argv[2]).write_text(json.dumps(generate(sys.argv[1]), indent=2) + '\n', encoding='utf-8')
