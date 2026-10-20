"""Finite signed Go runtime targets, preserving actual original owners."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_inventory as registry
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh
from tools.test_run import redact

ROOT = Path(__file__).resolve().parents[1]
CASE = 'runtime::go::synchronization::signed_condition_once_rwmutex_and_channel_ordering_retire_original_v5_owners'
ADMISSION_CASE = 'runtime::go::admission::signed_cross_tenant_cell_saturation_keeps_original_owners_until_cancel_and_trap_retire'
MANAGED_TIMER_CASE = 'runtime::go::managed_timers::signed_managed_v5_timers_gc_callbacks_and_stop_reset_preserve_original_owners'
TIMER_MODES = [0, 1, 2, 3, 4, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17]
TIMER_NATIVE_MODES = [mode for mode in TIMER_MODES if mode != 4]
MANAGED_TIMER_ROWS = [('ordinary', iteration, mode, 'success') for iteration in range(2) for mode in TIMER_MODES]
MANAGED_TIMER_ROWS += [('timer-capacity', 0, 8, 'guest-trap'), ('fresh-after-timer-capacity', 0, 0, 'success'),
                       ('callback-failure', 0, 10, 'guest-trap'), ('fresh-after-callback-failure', 0, 0, 'success'),
                       ('cancel-original-root', 0, 7, 'cancelled'), ('deadline-original-root', 0, 7, 'deadline-exceeded'),
                       ('fresh-after-cancel-deadline', 0, 0, 'success')]
QUEUED_CASE = 'runtime::go::queued::signed_ordinary_queue_keeps_original_budgets_deadlines_and_tenant_ownership'
ADMISSION_ROWS = [
    ('warm', 'tenant-a', 'success'), ('warm', 'tenant-b', 'success'),
    ('saturated', 'tenant-b', 'resource-exhausted'), ('foreign-cancel', 'tenant-b', 'not-found'),
    ('original', 'tenant-a', 'cancelled'), ('fresh-after-retirement', 'tenant-b', 'success'),
    ('saturated', 'tenant-a', 'resource-exhausted'), ('foreign-cancel', 'tenant-a', 'not-found'),
    ('original', 'tenant-b', 'guest-trap'), ('fresh-after-retirement', 'tenant-a', 'success'),
    ('final-fresh', 'tenant-a', 'success'), ('final-fresh', 'tenant-b', 'success'),
]
QUEUED_ROWS = [('warm', tenant, 0, 'success') for tenant in ('tenant-a', 'tenant-b')]
for _owner, _peer, _terminal in [('tenant-a', 'tenant-b', 'cancelled'), ('tenant-b', 'tenant-a', 'guest-trap')]:
    QUEUED_ROWS += [('queued-full', _peer, 0, 'pending'),
                    ('saturated', _owner, 0, 'resource-exhausted'),
                    ('foreign-cancel', _owner, 0, 'not-found'),
                    ('queued-cancel', _peer, 0, 'cancelled'),
                    ('replacement-queued', _peer, 0, 'pending'),
                    ('queued-deadline', _peer, 0, 'deadline-exceeded'),
                    ('deadline-replacement', _peer, 0, 'pending'),
                    ('original', _owner, 0, _terminal)]
    QUEUED_ROWS += [('queued-fresh', _peer, index, 'success') for index in range(7)]
QUEUED_ROWS += [('final-fresh', tenant, 0, 'success') for tenant in ('tenant-a', 'tenant-b')]
NATIVE_MODES = [0, 1, 2, 3, 4, 5, 9]
ORDINARY_MODES = [0, 1, 2, 3, 4, 5, 6, 9]
EXTRA = [('blocked-condition', 7, 'guest-trap'), ('fresh-after-blocked', 4, 'success'),
         ('task-exhaustion', 0, 'guest-trap'), ('cancel-original-root', 8, 'cancelled'),
         ('deadline-original-root', 8, 'deadline-exceeded'), ('fresh-after-cancel-deadline', 4, 'success'),
         ('no-checkpoint-startup', 4, 'success'), ('no-checkpoint-spin', 9, 'resource-exhausted'),
         ('no-checkpoint-fresh', 4, 'success')]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-synchronization-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-synchronization-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_SYNCHRONIZATION_CASE (.+)$', raw, re.M)]
    expected = [('ordinary', iteration, mode, 'success') for iteration in range(3) for mode in ORDINARY_MODES]
    expected += [(case, 0, mode, outcome) for case, mode, outcome in EXTRA]
    if len(rows) != len(expected):
        raise ValueError('Go-synchronization-missing-or-extra-invocation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'iteration', 'mode', 'outcome'}
                or type(row['iteration']) is not int or type(row['mode']) is not int):
            raise ValueError('Go-synchronization-private-or-unknown-field')
        actual.append((row['case'], row['iteration'], row['mode'], row['outcome']))
    if actual != expected:
        raise ValueError('Go-synchronization-invocation-contract')
    return rows



def admission_observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-admission-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [ADMISSION_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-admission-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_ADMISSION_CASE (.+)$', raw, re.M)]
    if len(rows) != len(ADMISSION_ROWS):
        raise ValueError('Go-admission-missing-or-extra-observation')
    actual = []
    for row in rows:
        if set(row) != {'case', 'tenant', 'outcome'} or not all(type(value) is str for value in row.values()):
            raise ValueError('Go-admission-private-or-unknown-field')
        actual.append((row['case'], row['tenant'], row['outcome']))
    if actual != ADMISSION_ROWS:
        raise ValueError('Go-admission-observation-contract')
    return rows


def queued_observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-queued-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [QUEUED_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-queued-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_QUEUED_CASE (.+)$', raw, re.M)]
    if len(rows) != len(QUEUED_ROWS):
        raise ValueError('Go-queued-missing-or-extra-observation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'tenant', 'index', 'outcome'} or type(row['index']) is not int
                or not all(type(row[key]) is str for key in ('case', 'tenant', 'outcome'))):
            raise ValueError('Go-queued-private-or-unknown-field')
        actual.append((row['case'], row['tenant'], row['index'], row['outcome']))
    if actual != QUEUED_ROWS:
        raise ValueError('Go-queued-observation-contract')
    return rows


def managed_timer_observations(raw: bytes, filtered: int) -> list[dict]:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Go-managed-timers-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if names != [MANAGED_TIMER_CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', str(filtered).encode())]:
        raise ValueError('Go-managed-timers-exact-signed-case-required')
    rows = [json.loads(value) for value in re.findall(rb'^GO_MANAGED_TIMER_CASE (.+)$', raw, re.M)]
    if len(rows) != len(MANAGED_TIMER_ROWS):
        raise ValueError('Go-managed-timers-missing-or-extra-invocation')
    actual = []
    for row in rows:
        if (set(row) != {'case', 'iteration', 'mode', 'outcome'}
                or type(row['iteration']) is not int or type(row['mode']) is not int
                or type(row['case']) is not str or type(row['outcome']) is not str):
            raise ValueError('Go-managed-timers-private-or-unknown-field')
        actual.append((row['case'], row['iteration'], row['mode'], row['outcome']))
    if actual != MANAGED_TIMER_ROWS:
        raise ValueError('Go-managed-timers-invocation-contract')
    return rows


def campaign(campaign: str, fixture: Path, negative: Path | None) -> dict:
    if campaign == 'synchronization' and negative is not None:
        return {'case': CASE, 'fixture': 'synchronization', 'variable': 'LSF_GO_SYNCHRONIZATION_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5'), (negative, 'go-component-activation-v1')]}
    if campaign in {'admission', 'queued'} and negative is None:
        return {'case': ADMISSION_CASE if campaign == 'admission' else QUEUED_CASE,
                'fixture': 'managed-idle', 'variable': 'LSF_GO_MANAGED_IDLE_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    if campaign == 'managed-timers' and negative is None:
        return {'case': MANAGED_TIMER_CASE, 'fixture': 'timers', 'variable': 'LSF_GO_MANAGED_TIMER_FIXTURE',
                'inputs': [(fixture, 'go-component-activation-v5')]}
    raise ValueError('Go-runtime-unreviewed-campaign-or-negative')


def source_snapshot(root: Path) -> dict:
    files = {path for folder in ('sdk/go-guest', 'tools/go_guest')
             for path in (root / folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts}
    files |= {root / name for name in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.cargo/managed-guest.toml',
              'crates/latent-wasmtime/Cargo.toml', 'crates/latent-wasmtime/tests/local_service.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/synchronization.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/admission.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/queued.rs',
              'crates/latent-wasmtime/tests/local_service/runtime/go/managed_timers.rs',
              'crates/latent-wasmtime/tests/local_service/fixture.rs',
              'crates/latent-wasmtime/tests/guest_sdk/runtime.rs',
              'crates/latent-wasmtime/tests/local_service/packages.rs',
              'crates/latent-wasmtime/tests/local_service/component.rs',
              'tools/ci/suites.json', 'tools/qualify_go_activation.py', 'tools/qualify_go_synchronization.py')}
    if len(files) > 1024:
        raise ValueError('Go-synchronization-source-count')
    rows = {}
    for path in sorted(files):
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Go-synchronization-source-file')
        rows[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return rows


def compile_identity(path: Path, root: Path, profile: str, fixture: str = 'synchronization') -> dict:
    raw = (path / 'GO-ACTIVATION-COMPILE.json').read_bytes()
    if len(raw) > 512 * 1024:
        raise ValueError('Go-synchronization-compiler-receipt-bound')
    record = json.loads(raw)
    if (fixture not in {'synchronization', 'managed-idle', 'timers'}
            or (fixture in {'managed-idle', 'timers'} and profile != 'go-component-activation-v5')):
        raise ValueError('Go-runtime-unreviewed-source-profile')
    folder = {'synchronization': 'synchronization-conformance', 'managed-idle': 'managed-idle-conformance',
              'timers': 'timers-conformance'}[fixture]
    source = (root / 'sdk/go-guest/runtime' / folder / 'main.go').read_bytes()
    if (record['profile'] != profile or record['fixture'] != fixture
            or record['sourceDigest'] != 'sha256:' + digest(source) or record['sourceUnchanged'] is not True
            or record['ordinarySource'] is not True or record['signedExecution'] != 'not-run'
            or (path / 'src/main.go').read_bytes() != source):
        raise ValueError('Go-synchronization-compiler-source-or-profile')
    component = path / 'build/component.wasm'
    if component.is_symlink() or component.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Go-synchronization-component-bound')
    if record['componentDigest'] != 'sha256:' + digest(component.read_bytes()):
        raise ValueError('Go-synchronization-component-identity')
    if profile == 'go-component-activation-v5':
        native = record['nativeReference']
        expected_modes = {'synchronization': NATIVE_MODES, 'managed-idle': [0, 1, 2], 'timers': TIMER_NATIVE_MODES}[fixture]
        if (native['modes'] != expected_modes or native['output'] != 42
                or native['freshProcessPerMode'] is not True or native['sourceDigest'] != record['sourceDigest']):
            raise ValueError('Go-synchronization-native-reference')
    return {'receiptSha256': digest(raw), 'profile': profile, 'sourceDigest': record['sourceDigest'],
            'componentDigest': record['componentDigest'], 'bindingDigest': record['bindingDigest'],
            'toolMaterialsSha256': digest(json.dumps(record['tools'], sort_keys=True).encode()),
            'transformationsSha256': digest(json.dumps(record['transformations'], sort_keys=True).encode()),
            'nativeReference': record.get('nativeReference')}


def qualify(root: Path, output: Path, fixture: Path, negative: Path | None, revision: str, programme: str = 'synchronization') -> dict:
    if sys.platform != 'linux':
        raise ValueError('Go-synchronization-Linux-owned-execution-required')
    plan = campaign(programme, fixture, negative)
    environment = {**os.environ, 'CARGO_BUILD_JOBS': '2', 'CARGO_INCREMENTAL': '0',
                   'LSF_GUEST_SDK_LANGUAGE': 'go', plan['variable']: str(fixture.resolve())}
    if negative is not None:
        environment['LSF_GO_SYNCHRONIZATION_NO_CHECKPOINT_FIXTURE'] = str(negative.resolve())
    artifacts.require_source(root, revision, environment)
    def clean_source():
        state = run_owned(['git', '-c', 'gc.auto=0', 'status', '--porcelain'], cwd=root,
                          env=environment, timeout=30, maximum=65536)
        if state.returncode or state.output.strip():
            raise ValueError('Go-synchronization-uncommitted-source')
    clean_source()
    before = source_snapshot(root)
    material = {profile: compile_identity(path, root, profile, plan['fixture']) for path, profile in plan['inputs']}
    suites = registry.load(root / 'tools/ci/suites.json')['suites']
    suite, = [row for row in suites if row['id'] == 'latent-wasmtime.test.local-service']
    if plan['case'] not in suite['expectedCases'] or plan['case'] not in suite['expectedIgnored'] or suite['timeoutSeconds'] != 900:
        raise ValueError('Go-synchronization-suite-contract')
    output = fresh(output)
    command = ['cargo', '--config', '.cargo/managed-guest.toml', 'test', '--locked', '-p', 'latent-wasmtime',
               '--test', 'local_service', plan['case'], '--', '--ignored', '--exact', '--show-output']
    try:
        result = run_owned(command, cwd=root, env=environment, timeout=1800,
                           maximum=2 * 1024 * 1024, separate_stderr=True)
    except ProcessFailure as error:
        if error.result is not None:
            (output / 'signed.stdout.log').write_bytes(error.result.output)
            (output / 'signed.stderr.log').write_bytes(redact(error.result.stderr.decode('utf-8', 'replace')).encode())
        raise
    (output / 'signed.stdout.log').write_bytes(result.output)
    (output / 'signed.stderr.log').write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
    if result.returncode:
        raise ValueError('Go-synchronization-signed-command-failed')
    parser = {'synchronization': observations, 'admission': admission_observations,
              'queued': queued_observations, 'managed-timers': managed_timer_observations}[programme]
    rows = parser(result.output, len(suite['expectedCases']) - 1)
    after = source_snapshot(root)
    after_material = {profile: compile_identity(path, root, profile, plan['fixture']) for path, profile in plan['inputs']}
    clean_source()
    if before != after or material != after_material:
        raise ValueError('Go-synchronization-source-or-component-changed')
    receipt = {'schemaVersion': {'synchronization': 'lsf.go-synchronization-reference.v1',
                                 'admission': 'lsf.go-admission-reference.v1',
                                 'queued': 'lsf.go-queued-reference.v1',
                                 'managed-timers': 'lsf.go-managed-timers-reference.v1'}[programme], 'sourceRevision': revision,
               'sourceBefore': before, 'sourceAfter': after, 'compilerInputsBefore': material,
               'compilerInputsAfter': after_material, 'case': plan['case'], 'signedCases': rows,
               'signedInvocations': {'synchronization': len(rows), 'admission': 8, 'queued': 20, 'managed-timers': len(rows)}[programme], 'guestTaskCeiling': 16,
               'managedCapacity': 8, 'waitCeiling': 4, 'newRuntimeProfile': False,
               'kernelTlsOrCrossTenantQualified': False, 'fullGoRuntimeQualified': False}
    if programme == 'synchronization':
        receipt['limitedTaskCeiling'] = 10
    elif programme in {'admission', 'queued'}:
        receipt.update({'signedObservationCount': len(rows), 'admissionRefusals': 2, 'foreignCancellationControls': 2,
                        'physicalCells': 1, 'nodeAdmissionCeiling': 1 if programme == 'admission' else 8,
                        'tenantsShareManagerBackendAndCell': True,
                        'generalSchedulerFairnessQualified': False,
                        'auxiliaryCallee': {'kind': 'synthetic-handwritten-wasm-encoder',
                                            'constructor': 'packages::callee(42)', 'invoked': False,
                                            'sources': ['crates/latent-wasmtime/tests/local_service/packages.rs',
                                                        'crates/latent-wasmtime/tests/local_service/component.rs']}})
        if programme == 'queued':
            receipt.update({'nodeQueueCeiling': 8, 'observedMaximumQueued': 7,
                            'queuedCancellationBeforeStore': 2, 'queuedDeadlineBeforeStore': 2,
                            'rootDeadlineIncludesQueueWaiting': True,
                            'aggregateCpuAndMemoryCeilingsUnchanged': True})
    else:
        receipt.update({'timerCeiling': 2, 'signedObservationCount': 43,
                        'nativeReferenceModes': TIMER_NATIVE_MODES,
                        'relabelsLegacyV3Evidence': False, 'fullTimerRaceMatrixQualified': False})
    raw = (json.dumps(receipt, indent=2) + '\n').encode()
    if len(raw) > 262144:
        raise ValueError('Go-synchronization-receipt-bound')
    (output / 'receipt.json').write_bytes(raw)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--no-checkpoints', type=Path)
    parser.add_argument('--campaign', choices=('synchronization', 'admission', 'queued', 'managed-timers'), default='synchronization')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    qualify(ROOT, args.output, args.fixture, args.no_checkpoints, args.source_commit, args.campaign)
    print('Actual signed Go ' + args.campaign + ' and original-owner controls passed; full #742 remains open')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
