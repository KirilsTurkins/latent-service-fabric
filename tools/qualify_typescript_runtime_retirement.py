"""One exact signed native retirement case; reuse authenticated compiler inputs only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_typescript_standard_clocks import engine_inputs
from tools.replay_typescript_standard_entropy import historical
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

CASE = 'runtime::typescript::signed_pending_promise_cancellation_deadline_and_timer_failures_retire_before_fresh_state'
EXPECTED = (
    ('typescript-retirement-reference-1', 1, 'Succeeded'),
    ('typescript-retirement-reference-3', 3, 'Succeeded'),
    ('typescript-promise-pending-then-resolved', 5, 'Succeeded'),
    ('typescript-fresh-after-promise-resolution', 1, 'Succeeded'),
    ('typescript-pending-promise-cancel', 0, 'Cancelled'),
    ('typescript-fresh-after-promise-cancel', 1, 'Succeeded'),
    ('typescript-promise-original-root-deadline', 0, 'DeadlineExceeded'),
    ('typescript-fresh-after-promise-deadline', 1, 'Succeeded'),
    ('typescript-root-trap-mode', 2, 'GuestTrap'),
    ('typescript-fresh-after-root-trap', 1, 'Succeeded'),
)
IDLE = frozenset(('activeInvocations', 'stores', 'hostStates', 'componentInstances',
    'cancellationProbes', 'temporaryBuffers', 'calls', 'sessions', 'handles', 'results',
    'bufferBytes', 'readWaits', 'quotaActivations', 'instanceReservations', 'cancellationRegistrations'))
MATERIALS = ('tools/qualify_typescript_runtime_retirement.py', 'tools/typescript_runtime_retirement_fixture.py',
    'crates/latent-wasmtime/tests/local_service/runtime/typescript.rs',
    'tools/typescript_guest/build.py', 'tools/typescript_guest/bundle.mjs',
    'tools/typescript_guest/runtime_profile.py', 'tools/typescript_guest/clock_engine.py',
    'tools/typescript_guest/clock_app.mjs')


def test_command():
    return ['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--test', 'local_service',
            CASE, '--', '--ignored', '--exact', '--show-output', '--test-threads=1']


def observation(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 4*1024**2, 'typescript-retirement-output-bound')
    text = raw.decode('utf-8', errors='strict')
    require(f'test {CASE} ... ok' in text
            and re.search(r'^test result: ok\. 1 passed; 0 failed; 0 ignored;', text, re.MULTILINE),
            'typescript-retirement-one-exact-native-case')
    lines = [line.removeprefix('TYPESCRIPT_RETIREMENT ') for line in text.splitlines()
             if line.startswith('TYPESCRIPT_RETIREMENT ')]
    require(len(lines) == 1 and len(lines[0]) <= 65536, 'typescript-retirement-one-bounded-observation')
    value = json.loads(lines[0])
    require(type(value) is dict and value.get('schemaVersion') == 'latent.typescript.runtime-retirement.v1'
            and value.get('status') == 'passed' and value.get('fullTicketQualification') is False
            and value.get('crossTenantQualified') is False, 'typescript-retirement-observation-identity')
    rows = value.get('cases')
    require(type(rows) is list and len(rows) == len(EXPECTED), 'typescript-retirement-ten-outcomes')
    for row, (identity, mode, outcome) in zip(rows, EXPECTED, strict=True):
        require(type(row) is dict and row.get('case') == identity and type(row.get('mode')) is int
                and row['mode'] == mode and row.get('outcome') == outcome, 'typescript-retirement-exact-outcome')
        idle = row.get('idle')
        require(type(idle) is dict and set(idle) == IDLE
                and all(type(v) is int and v == 0 for v in idle.values()), 'typescript-retirement-original-owners-idle')
        if outcome == 'Succeeded':
            require(row.get('decoded') == [42] and all(type(row.get(key)) is int and row[key] > 0
                    for key in ('cpuFuel', 'peakMemoryBytes')), 'typescript-retirement-real-success')
        if mode in (0, 5):
            pending = row.get('pending')
            require(type(pending) is dict and set(pending) == {'stores', 'readWaits', 'calls'}
                    and pending['stores'] == 1 and all(type(v) is int and v > 0 for v in pending.values()),
                    'typescript-retirement-real-pending-owners')
        if outcome == 'GuestTrap':
            require(row.get('callbackOriginProven') is False, 'typescript-retirement-no-callback-cause-inference')
    return value


def build_proof(directory):
    marker = read_json(directory/'BUILD-COMPLETE.json')
    fields = {'component.wasm': 'componentDigest', 'source-inputs.json': 'sourceDigest',
              'build-observation.json': 'observationDigest'}
    files = {name: file_identity(directory/name, 64*1024**2) for name in fields}
    require(marker.get('packageAssembled') is True
            and all(files[name]['sha256'] == marker[field] for name, field in fields.items()),
            'typescript-retirement-actual-build-observation')
    return {'marker': file_identity(directory/'BUILD-COMPLETE.json'), 'files': files,
            'packageInputs': file_identity(directory/'package-inputs.json')}


def qualify(acquired, engine, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'typescript-retirement-Linux-Python313')
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.runtime-retirement-qualification.v1', 'status': 'incomplete',
        'engineRebuilt': False, 'historicalNativeProductsRebuilt': False, 'currentNativeTestTarget': True,
        'normalReceiptRewritten': False, 'fullTicketQualification': False}
    stage, commands = 'authenticated-original-compiler', None
    try:
        products, _normal, inherited = historical(acquired)
        core, envelope, original_engine = engine_inputs(engine)
        record.update(historicalCompiler=inherited, originalEngine=original_engine)
        source = source_identity(ROOT)
        material = {name: file_identity(ROOT/name) for name in MATERIALS}
        write_json(output/'native-test-source.json', source)
        record.update(nativeTestSource=source, materials=material)
        environment = build_environment(output)
        environment.update(CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        commands = Commands(ROOT, output, environment, deadline_seconds=1200, command_seconds=900)
        stage = 'fresh-ordinary-caller-and-callee'
        inputs = output/'compiler'
        commands.run(stage, sys.executable, '-B', ROOT/'tools/typescript_runtime_retirement_fixture.py',
            '--output', inputs, '--tools', tools, '--contracts', products['examples/capsule_contracts'],
            '--packager', products['examples/package'], '--engine', core, '--envelope', envelope)
        record['builds'] = {name: build_proof(inputs/name)
                           for name in ('typescript-runtime-retirement', 'typescript-service-callee')}
        commands.environment.update(LSF_GUEST_SDK_LANGUAGE='typescript', LSF_GUEST_CAPSULES=str(inputs))
        stage = 'exact-signed-native-retirement'
        raw = commands.run(stage, *test_command())
        observed = observation(raw)
        write_json(output/'native-observation.json', observed)
        require(source_identity(ROOT) == source
                and {name: file_identity(ROOT/name) for name in MATERIALS} == material,
                'typescript-retirement-source-changed')
        record.update(status='passed', nativeObservation=file_identity(output/'native-observation.json'),
                      outcomes=len(observed['cases']), signedAndAdmitted=True, nativeTestSourceUnchanged=True)
        write_json(output/'qualification.json', record)
        return record
    except Exception as error:
        record.update(status='failed', stage=stage, errorType=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise
    finally:
        if commands is not None:
            write_json(output/'commands.json', commands.records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('acquired', 'engine', 'tools', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.acquired, args.engine, args.tools, args.output)))
