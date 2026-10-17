#!/usr/bin/env python3
"""Execute the controlled root-stack profile using already qualified clocks.

The host's real StackMemory destructor is the retirement fence. This gate adds
no canonical thread permission and does not qualify std::thread or executors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_rust_standard_clocks as clocks
from tools.build_observation import build_environment, file_identity
from tools.dev_workflow.common import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import checked_path, decode_json, digest, fresh, inventory, read_file, write_json

CASES = {'wall': 'ordinary_std_systemtime_with_owned_native_stack',
         'monotonic': 'monotonic::ordinary_std_instant_with_owned_native_stack'}
RECIPE = ('tools/qualify_owned_native_stacks.py',
          'crates/latent-wasmtime/src/native_stacks.rs',
          'crates/latent-wasmtime/src/native_stacks/tests.rs',
          'crates/latent-wasmtime/src/host/runtime.rs',
          'crates/latent-wasmtime/src/backend.rs',
          'crates/latent-wasmtime/src/backend/input.rs',
          'crates/latent-wasmtime/src/config.rs',
          'crates/latent-wasmtime/src/config/engine.rs',
          'crates/latent-wasmtime/src/config/profile.rs',
          *clocks.clock.RECIPE)


def clock_input(root: Path, kind: str, native_digest: str):
    require(kind in CASES, 'native-stack-clock-kind')
    summary = decode_json(read_file(root / 'report.json', 128 * 1024))
    result = decode_json(read_file(root / kind / 'qualification.json', 256 * 1024))
    marker = decode_json(read_file(root / kind / 'clock-guest.json', 256 * 1024))
    component = read_file(root / kind / 'component.wasm', 4 * 1024 * 1024)
    require(summary.get('schemaVersion') == 'latent.rust.standard-clocks-gate.v1'
            and summary.get('status') == 'passed' and result.get('status') == 'passed',
            'native-stack-clock-baseline-not-passed')
    require(result.get('component') == marker and marker.get('clockKind') == kind
            and marker.get('profile') == clocks.clock.std.PROFILE
            and marker.get('applicationClockSdkCalled') is False
            and marker.get('componentDigest') == digest(component),
            'native-stack-clock-component-identity')
    require(result.get('nativeFixture', {}).get('testDigest') == native_digest
            and summary.get('clocks', {}).get(kind, {}).get('componentDigest') == digest(component)
            and summary['clocks'][kind].get('sysrootIdentity') == marker.get('sysrootIdentity'),
            'native-stack-clock-native-source-identity')
    return marker


def run(output: Path, inventory_path: Path, target: Path, clock_root: Path):
    native = clocks.test_executable(read_file(checked_path(inventory_path), 4 * 1024 * 1024), target)
    native_identity = file_identity(native, 'clock-admission-test')
    clock_root = checked_path(clock_root)
    markers = {kind: clock_input(clock_root, kind, native_identity['digest']) for kind in CASES}
    inputs = {name: read_file(clocks.ROOT / name) for name in dict.fromkeys(RECIPE)}
    output = fresh(output)
    result = {'schemaVersion': 'latent.owned-native-stack-qualification.v1',
              'status': 'in-progress', 'profile': 'original-lease-physical-drop-v1',
              'scope': 'one-pre-admitted-root-stack-linux-x86_64-on-demand',
              'canonicalThreadCreationEnabled': False, 'standardThreadsQualified': False,
              'defaultExecutorsQualified': False, 'nativeTest': native_identity,
              'recipeDigest': digest(inventory(inputs)), 'clocks': {}}
    try:
        for kind, case in CASES.items():
            with tempfile.TemporaryDirectory(prefix='lsf-owned-native-stack-') as temporary:
                environment = build_environment(Path(temporary))
                environment['LSF_RUST_STD_CLOCK_GUEST'] = str(clock_root / kind)
                log = output / kind
                log.mkdir()
                commands = Commands(clock_root, log, environment, deadline_seconds=120, command_seconds=60)
                listing = commands.run('case-list', native, '--list').decode()
                require(case + ': test' in listing, 'native-stack-signed-case-missing')
                commands.run('signed-owned-stack', native, '--exact', case, '--ignored',
                             '--test-threads=1', '--nocapture')
            require(clock_input(clock_root, kind, native_identity['digest']) == markers[kind],
                    'native-stack-clock-input-mutated')
            result['clocks'][kind] = {'case': case, 'status': 'passed',
                'componentDigest': markers[kind]['componentDigest'], 'commands': commands.records}
        require(file_identity(native, 'clock-admission-test') == native_identity,
                'native-stack-native-test-mutated')
        require({name: read_file(clocks.ROOT / name) for name in inputs} == inputs,
                'native-stack-recipe-mutated')
        result['status'] = 'passed'
        write_json(output / 'report.json', result)
        return result
    except Exception:
        result['status'] = 'failed'
        write_json(output / 'report.json', result)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo-inventory', type=Path, required=True)
    parser.add_argument('--native-target', type=Path, required=True)
    parser.add_argument('--clocks', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.output, args.cargo_inventory, args.native_target, args.clocks)))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f'Owned native stack gate failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
