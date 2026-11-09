#!/usr/bin/env python3
"""Compile unchanged standard Go APIs with captured activation infrastructure."""
import argparse
import json
import os
import shutil
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
    elif fixture == 'managed-idle':
        modes = [0, 1, 2]
    elif fixture == 'task-saturation':
        # Native Go has no managed activation Task ceiling. Only the bounded
        # release/join path is a comparable native observable.
        modes = [0]
    elif fixture == 'timer-overlap':
        # Native execution checks public return values; only the signed host
        # witness establishes that the operations actually overlapped.
        modes = [0, 1, 2, 3]
    elif fixture == 'timer-fired':
        modes = [0, 1, 2, 3]
    elif fixture == 'synchronization':
        # Native main does not implement the component's accepted-work drain.
        # The parked/late-root/cancellation cases retain signed-only assertions.
        modes = [0, 1, 2, 3, 4, 5, 9]
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
        outputs = []
        for mode in modes:
            value = commands.run(fixture + '-native-' + str(mode), binary, str(mode)).strip()
            allowed = {b'42', b'43'} if fixture == 'timer-overlap' and mode in (1, 3) else {b'42'}
            if value not in allowed:
                raise ValueError('Go-native-reference-output')
            outputs.append(int(value))
    finally:
        commands.environment.clear()
        commands.environment.update(previous)
    result = {'qualification': 'reviewed-fixture-only', 'fixture': fixture, 'modes': modes,
              'freshProcessPerMode': True, 'sourceDigest': digest(source), 'binaryDigest': digest(binary.read_bytes())}
    if fixture == 'timer-overlap':
        result['outputs'] = outputs
    else:
        result['output'] = 42
    return result


def compile_fixture(output: Path, *, offline_cache: Path | None = None, runtime_profile=PROFILE,
                    fixture='ordinary') -> dict:
    if runtime_profile not in PROFILES:
        raise ValueError('unsupported-Go-activation-qualification-profile')
    if fixture == 'synchronization' and runtime_profile not in {'go-component-activation-v1', 'go-component-activation-v5'}:
        raise ValueError('Go-synchronization-requires-v5-or-exact-no-checkpoint-control')
    if fixture == 'task-saturation' and runtime_profile != 'go-component-activation-v5':
        raise ValueError('Go-task-saturation-requires-v5')
    if fixture == 'timer-overlap' and runtime_profile not in {'go-component-activation-v5', 'go-component-activation-v7'}:
        raise ValueError('Go-timer-overlap-requires-v5-or-v7')
    if fixture == 'timer-fired' and runtime_profile != 'go-component-activation-v7':
        raise ValueError('Go-fired-timer-requires-v7')
    output.mkdir(parents=True, exist_ok=False)
    if fixture not in {'ordinary', 'checkpoints', 'timers', 'initializers', 'managed-idle', 'synchronization', 'task-saturation', 'timer-overlap', 'timer-fired'}:
        raise ValueError('unsupported-Go-activation-fixture')
    if fixture == 'managed-idle' and runtime_profile != 'go-component-activation-v5':
        raise ValueError('Go-managed-idle-fixture-requires-v5')
    original = ROOT / 'sdk/go-guest/runtime' / {'ordinary': 'conformance', 'checkpoints': 'checkpoints-conformance', 'timers': 'timers-conformance', 'initializers': 'initializers-conformance', 'managed-idle': 'managed-idle-conformance', 'synchronization': 'synchronization-conformance', 'task-saturation': 'task-saturation-conformance', 'timer-overlap': 'timer-overlap-conformance', 'timer-fired': 'timer-fired-conformance'}[fixture]
    source = (original / 'main.go').read_bytes()
    (output / 'src').mkdir()
    (output / 'src/main.go').write_bytes(source)
    for name in ('go.mod', 'go.sum'):
        (output / name).write_bytes((ROOT / 'sdk/go-guest/runtime-deps' / name).read_bytes())
    stage(output / 'wit', original)
    # stage copies only WIT; Go source remains separately captured above.
    commands = Commands(output, output, dict(os.environ))
    sdk = ROOT / 'sdk/go-guest'
    diagnostic = None
    if fixture == 'timer-fired':
        from tools.go_guest.fired_timer_witness import (derive, derive_bridge, derive_activation_bridge,
            GO_CHAN_SHA256, GO_RUNTIME2_SHA256, verified_runtime_sources)
        sdk_copy = output / 'diagnostic-sdk'
        shutil.copytree(sdk, sdk_copy)
        timer = sdk_copy / 'runtime/timer_async.go.in'
        original_timer = (sdk / 'runtime/timer_async.go.in').read_bytes()
        derived_timer = derive(original_timer)
        timer.write_bytes(derived_timer)
        bridge = sdk_copy / 'runtime/timer_bridge.go.in'
        activation = sdk_copy / 'runtime/activation_bridge.go.in'
        original_bridge = (sdk / 'runtime/timer_bridge.go.in').read_bytes()
        original_activation = (sdk / 'runtime/activation_bridge.go.in').read_bytes()
        derived_bridge = derive_bridge(original_bridge)
        derived_activation = derive_activation_bridge(original_activation)
        bridge.write_bytes(derived_bridge)
        activation.write_bytes(derived_activation)
        diagnostic = {'kind': 'selected-returned-ticker-cancel-fence-observe-v4',
                      'originalTimerAsyncDigest': digest(original_timer),
                      'derivedTimerAsyncDigest': digest(derived_timer),
                      'originalTimerBridgeDigest': digest(original_bridge),
                      'derivedTimerBridgeDigest': digest(derived_bridge),
                      'originalActivationBridgeDigest': digest(original_activation),
                      'derivedActivationBridgeDigest': digest(derived_activation),
                      'runtimeChanDigest': 'sha256:' + GO_CHAN_SHA256,
                      'runtimeDescriptorDigest': 'sha256:' + GO_RUNTIME2_SHA256}
        sdk = sdk_copy
    compiler = Compiler(output / 'compiler', sdk, commands, offline_cache=offline_cache,
                        runtime_profile=runtime_profile)
    try:
        if fixture == 'timer-fired':
            # The exact channel enqueue/commit and sudog layout underpin the
            # channel-specific park probe. Preserve these authenticated inputs.
            for name, content in verified_runtime_sources(compiler.goroot).items():
                target = output / 'diagnostic-runtime-inputs' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.encode('utf-8'))
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
        if diagnostic is not None:
            record['diagnosticRuntime'] = diagnostic
        if not record['sourceUnchanged']:
            raise ValueError('Go-activation-source-changed')
        if fixture == 'checkpoints' and runtime_profile == 'go-component-activation-v2':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'timers' and runtime_profile in {
                'go-component-activation-v3', 'go-component-activation-v5', 'go-component-activation-v7'}:
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'initializers' and runtime_profile == 'go-component-activation-v4':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'managed-idle':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'task-saturation':
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture in {'timer-overlap', 'timer-fired'}:
            record['nativeReference'] = fixture_reference(output, commands, compiler, source, fixture)
        if fixture == 'synchronization' and runtime_profile == 'go-component-activation-v5':
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
    parser.add_argument('--fixture', choices=('ordinary', 'checkpoints', 'timers', 'initializers', 'managed-idle', 'synchronization', 'task-saturation', 'timer-overlap', 'timer-fired'), default='ordinary')
    args = parser.parse_args()
    print(json.dumps(compile_fixture(args.output, offline_cache=args.offline_cache,
        runtime_profile=args.runtime_profile, fixture=args.fixture)))
