#!/usr/bin/env python3
"""Compile unchanged standard Go APIs with captured activation infrastructure."""
import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.go_guest.activation import PROFILE, PROFILES
from tools.go_guest.compiler import Compiler
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, inventory, snapshot, write_json
from tools.stage_runtime_wit import stage


def fixture_reference(output, commands, compiler, source, fixture):
    """Run only this reviewed fixture on the pinned native Go reference."""
    if fixture == 'checkpoints':
        modes = [0, 1, 4]
    elif fixture == 'timers':
        # Mode 4 intentionally returns with accepted callbacks: native Go main
        # exits immediately, whereas the component profile requires drain.
        # Failure/cancellation modes have their own signed-node assertions.
        modes = [0, 1, 2, 3, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17]
    elif fixture == 'initializers':
        modes = [0]
    else:
        raise ValueError('Go-native-reference-unreviewed-fixture')
    reference = output / 'native-reference'
    reference.mkdir()
    ordinary = reference / 'ordinary.go'
    ordinary.write_bytes(source.replace(b'package export_tests_caller_api\n', b'package main\n', 1))
    harness = reference / 'main.go'
    harness.write_text('package main\nimport("fmt";"os";"strconv")\n'
        'func main(){n,e:=strconv.ParseUint(os.Args[1],10,32);if e!=nil{panic(e)};fmt.Println(Run(uint32(n)))}\n')
    binary = reference / 'reference'
    previous = dict(commands.environment)
    commands.environment.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
                                 GOPROXY='off', GOSUMDB='off')
    try:
        commands.run(fixture + '-native-build', compiler.paths['go'], 'build', '-o', binary, ordinary, harness)
        for mode in modes:
            if commands.run(fixture + '-native-' + str(mode), binary, str(mode)).strip() != b'42':
                raise ValueError('Go-native-reference-output')
    finally:
        commands.environment.clear()
        commands.environment.update(previous)
    return {'qualification': 'reviewed-fixture-only', 'fixture': fixture, 'modes': modes, 'output': 42,
            'freshProcessPerMode': True, 'sourceDigest': digest(source), 'binaryDigest': digest(binary.read_bytes())}


def compile_fixture(output: Path, *, offline_cache: Path | None = None, runtime_profile=PROFILE,
                    fixture='ordinary') -> dict:
    if runtime_profile not in PROFILES:
        raise ValueError('unsupported-Go-activation-qualification-profile')
    output.mkdir(parents=True, exist_ok=False)
    if fixture not in {'ordinary', 'checkpoints', 'timers', 'initializers'}:
        raise ValueError('unsupported-Go-activation-fixture')
    original = ROOT / 'sdk/go-guest/runtime' / {'ordinary': 'conformance', 'checkpoints': 'checkpoints-conformance', 'timers': 'timers-conformance', 'initializers': 'initializers-conformance'}[fixture]
    source = (original / 'main.go').read_bytes()
    (output / 'src').mkdir()
    (output / 'src/main.go').write_bytes(source)
    for name in ('go.mod', 'go.sum'):
        (output / name).write_bytes((ROOT / 'sdk/go-guest/runtime-deps' / name).read_bytes())
    stage(output / 'wit', original)
    # stage copies only WIT; Go source remains separately captured above.
    commands = Commands(output, output, dict(os.environ))
    compiler = Compiler(output / 'compiler', ROOT / 'sdk/go-guest', commands, offline_cache=offline_cache,
                        runtime_profile=runtime_profile)
    try:
        component, bindings = compiler.compile(output / 'src', output / 'wit', 'tests:caller/service@1.0.0',
            output / 'build', runtime_profile=runtime_profile)
        overlay = json.loads((output / 'build/runtime-overlay/overlay.json').read_bytes())['Replace']
        transformations = [{'upstreamDigest': digest(Path(before).read_bytes()),
                            'adaptedDigest': digest(Path(after).read_bytes())}
                           for before, after in sorted(overlay.items())]
        record = {'formatVersion': 1, 'profile': runtime_profile, 'fixture': fixture, 'sourceDigest': digest(source),
                  'componentDigest': digest(component.read_bytes()),
                  'bindingDigest': digest(inventory({name: json.dumps(value, sort_keys=True).encode()
                                                     for name, value in bindings.items()})),
                  'tools': compiler.materials, 'transformations': transformations,
                  'sourceUnchanged': source == (original / 'main.go').read_bytes(),
                  'ordinarySource': True, 'signedExecution': 'not-run', 'qualification': 'compile-only'}
        if not record['sourceUnchanged']:
            raise ValueError('Go-activation-source-changed')
        if fixture == 'checkpoints' and runtime_profile == 'go-component-activation-v2':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'timers' and runtime_profile == 'go-component-activation-v3':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'initializers' and runtime_profile == 'go-component-activation-v4':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        write_json(output / 'GO-ACTIVATION-COMPILE.json', record)
        return record
    except BaseException as error:
        write_json(output / 'GO-ACTIVATION-FAILED.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--offline-cache', type=Path)
    parser.add_argument('--runtime-profile', choices=sorted(PROFILES), default=PROFILE)
    parser.add_argument('--fixture', choices=('ordinary', 'checkpoints', 'timers', 'initializers'), default='ordinary')
    args = parser.parse_args()
    print(json.dumps(compile_fixture(args.output, offline_cache=args.offline_cache,
        runtime_profile=args.runtime_profile, fixture=args.fixture)))
