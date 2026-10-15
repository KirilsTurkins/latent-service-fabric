#!/usr/bin/env python3
"""Compile unchanged standard Go APIs with captured activation infrastructure."""
import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.go_guest.activation import PROFILE
from tools.go_guest.compiler import Compiler
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, snapshot, write_json
from tools.stage_runtime_wit import stage


def compile_fixture(output: Path, *, offline_cache: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    original = ROOT / 'sdk/go-guest/runtime/conformance'
    source = (original / 'main.go').read_bytes()
    (output / 'src').mkdir()
    (output / 'src/main.go').write_bytes(source)
    for name in ('go.mod', 'go.sum'):
        (output / name).write_bytes((ROOT / 'sdk/go-guest/runtime-deps' / name).read_bytes())
    stage(output / 'wit', original)
    # stage copies only WIT; Go source remains separately captured above.
    commands = Commands(output, output, dict(os.environ))
    compiler = Compiler(output / 'compiler', ROOT / 'sdk/go-guest', commands, offline_cache=offline_cache)
    try:
        component, bindings = compiler.compile(output / 'src', output / 'wit', 'tests:caller/service@1.0.0',
            output / 'build', runtime_profile=PROFILE)
        overlay = json.loads((output / 'build/runtime-overlay/overlay.json').read_bytes())['Replace']
        transformations = [{'upstreamDigest': digest(Path(before).read_bytes()),
                            'adaptedDigest': digest(Path(after).read_bytes())}
                           for before, after in sorted(overlay.items())]
        record = {'formatVersion': 1, 'profile': PROFILE, 'sourceDigest': digest(source),
                  'componentDigest': digest(component.read_bytes()),
                  'bindingDigest': digest(inventory({name: json.dumps(value, sort_keys=True).encode()
                                                     for name, value in bindings.items()})),
                  'tools': compiler.materials, 'transformations': transformations,
                  'sourceUnchanged': source == (original / 'main.go').read_bytes(),
                  'ordinarySource': True, 'signedExecution': 'not-run', 'qualification': 'compile-only'}
        if not record['sourceUnchanged']:
            raise ValueError('Go-activation-source-changed')
        write_json(output / 'GO-ACTIVATION-COMPILE.json', record)
        return record
    except BaseException as error:
        write_json(output / 'GO-ACTIVATION-FAILED.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offline-cache', type=Path)
    args = parser.parse_args()
    print(json.dumps(compile_fixture(args.output, offline_cache=args.offline_cache)))
