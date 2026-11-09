"""Check same-run Rust HTTP native evidence before compiling the backend.

This does not change historical readers, execute a guest, or qualify a signed
runtime. The existing native and backend owners retain their own deadlines.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORKFLOW = '.github/workflows/rust-http-current-native.yml'
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
SOURCE = 'tools/rust_http_current_backend_handoff.py'
TESTS = 'tools/tests/test_rust_http_current_backend_handoff.py'
ORIGIN_SCHEMA = 'latent.rust.http.same-run-native-origin.v1'
RESULT_SCHEMA = 'latent.rust.http.current-backend-handoff.v1'


def require(value, reason):
    if not value:
        raise ValueError('rust-http-backend-handoff-' + reason)


def context(environ, root, job):
    """Require one workflow execution, exact checkout path and expected job."""
    root = Path(root).resolve(strict=True)
    names = ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
        'GITHUB_SHA', 'GITHUB_REF', 'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW_SHA',
        'GITHUB_EVENT_NAME', 'GITHUB_JOB', 'GITHUB_WORKSPACE')
    require(all(type(environ.get(name)) is str for name in names), 'missing-github-context')
    require(environ['GITHUB_REPOSITORY'] == REPOSITORY
        and re.fullmatch(r'[1-9][0-9]{0,19}', environ['GITHUB_RUN_ID'])
        and re.fullmatch(r'[1-9][0-9]{0,9}', environ['GITHUB_RUN_ATTEMPT'])
        and re.fullmatch(r'[0-9a-f]{40}', environ['GITHUB_SHA'])
        and environ['GITHUB_REF'].startswith('refs/heads/')
        and environ['GITHUB_WORKFLOW_REF'] == REPOSITORY + '/' + WORKFLOW + '@' + environ['GITHUB_REF']
        and environ['GITHUB_WORKFLOW_SHA'] == environ['GITHUB_SHA']
        and environ['GITHUB_EVENT_NAME'] in ('push', 'workflow_dispatch')
        and environ['GITHUB_JOB'] == job
        and Path(environ['GITHUB_WORKSPACE']).resolve(strict=True) == root,
        'github-context')
    return {'repository': REPOSITORY, 'runId': environ['GITHUB_RUN_ID'],
        'attempt': environ['GITHUB_RUN_ATTEMPT'], 'revision': environ['GITHUB_SHA'],
        'ref': environ['GITHUB_REF'], 'workflowRef': environ['GITHUB_WORKFLOW_REF'],
        'workflowRevision': environ['GITHUB_WORKFLOW_SHA'], 'event': environ['GITHUB_EVENT_NAME'],
        'checkoutPath': str(root)}


def check_rows(record, plan, tests, native_record, root, directory, owner, producer, read_file):
    """Replay the selected historical command plan over the retained streams."""
    require(len(plan) == 34 and len(record) == 63, 'supplement-command-count')
    for index in (0, 1):
        expected = [str(root / '.cargo/managed-guest.toml') if part == 'ROOT/.cargo/managed-guest.toml'
            else part for part in plan[index][1:]]
        require(native_record['commands'][index + 1]['argv'] == expected, 'native-original-argv')
    cursor = total_bytes = 0
    elapsed = 0.0

    def consume(stage, args):
        nonlocal cursor, total_bytes, elapsed
        require(cursor < len(record), 'missing-command')
        row = record[cursor]
        require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds', 'argv', 'logs'}
            and row['stage'] == stage and row['argv'] == args
            and type(row['exitCode']) is int and row['exitCode'] == 0
            and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
            and 0 <= row['seconds'] <= 1320 and type(row['logs']) is dict
            and set(row['logs']) == {'stdout', 'stderr'}, 'command-record')
        elapsed += row['seconds']
        streams = {}
        for stream in ('stdout', 'stderr'):
            relative = f'logs/{cursor:02d}-{stage}.{stream}.txt'
            logged = row['logs'][stream]
            require(type(logged) is dict and set(logged) == {'path', 'bytes', 'sha256'}
                and logged['path'] == relative, 'log-path')
            raw = read_file(directory / relative, 4 * 1024**2)
            require(logged['bytes'] == len(raw) and logged['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest(),
                'log-identity')
            total_bytes += len(raw)
            streams[stream] = raw
        cursor += 1
        return streams['stdout']

    for item in plan[2:]:
        stage = item[0]
        args = [str(root / '.cargo/managed-guest.toml') if part == 'ROOT/.cargo/managed-guest.toml'
            else part for part in item[1:]]
        if stage == 'release-preparation-protocol-reader-controls':
            raw = consume(stage, args)
            require(re.search(rb'^Ran 12 tests in [^\r\n]+$', raw, re.M)
                and re.search(rb'^OK$', raw, re.M), 'original-python-tests')
            continue
        require('--' in args, 'original-test-separator')
        split = args.index('--')
        listing = args[:split + 1] + (['--exact'] if '--exact' in args[split + 1:] else []) + ['--list']
        expected = tests.get(stage)
        if expected is None:
            require('--exact' in args[split + 1:] and split > 0, 'exact-test-selector')
            expected = frozenset((args[split - 1],))
        selected = owner.list_tests(consume(stage + '-list', listing), expected)
        producer.exact_result(consume(stage + '-run', args), selected)
    require(cursor == len(record) and total_bytes <= 16 * 1024**2, 'supplement-log-bound')
    return elapsed


def verify(prepared, controls):
    """Recheck current source, original 91 native commands and 63 supplemental commands."""
    from tools import c_timed_current_products as current, qualify_host_codec_native as producer
    from tools import rust_http_current_controls as owner
    from tools.build_observation import build_environment
    from tools.phase3_resource_identity import file_identity
    from tools.rust_capsule_project import ROOT, checked_path, read_file, read_json

    prepared, controls = checked_path(prepared), checked_path(controls)
    require(prepared.is_dir() and controls.is_dir() and prepared != controls
        and prepared not in controls.parents and controls not in prepared.parents,
        'separate-input-directories')
    head, _ = current.current_source()
    native = current.native_evidence(prepared)
    native_record = read_json(prepared / 'native-products.json', 1024**2)
    record = read_json(controls / 'qualification.json', 16 * 1024**2)
    fields = {'schemaVersion', 'status', 'sourceRevision', 'historicalSource', 'historicalWorkflowSha256',
        'materials', 'sourceBoundNativeVerified', 'signedQualification', 'guestComponentsBuilt',
        'historicalReceiptRewritten', 'cargoFeatureSelection', 'featureClosureBoundary', 'commands',
        'nativeEvidence', 'elapsedSeconds', 'historicalCommandStages', 'currentCodecControls', 'toolchain'}
    require(type(record) is dict and set(record) == fields
        and record['schemaVersion'] == 'latent.rust.http.current-native-controls.v1'
        and record['status'] == 'passed' and record['sourceRevision'] == head
        and record['historicalSource'] == owner.HISTORICAL
        and record['historicalWorkflowSha256'] == owner.WORKFLOW_SHA256
        and record['sourceBoundNativeVerified'] is True and record['signedQualification'] is False
        and type(record['guestComponentsBuilt']) is int and record['guestComponentsBuilt'] == 0
        and record['historicalReceiptRewritten'] is False
        and record['cargoFeatureSelection'] == 'original-default-no-extra-feature-flags'
        and record['featureClosureBoundary'] == 'test targets may resolve different dev dependencies; identical full graphs are not claimed'
        and type(record['historicalCommandStages']) is int and record['historicalCommandStages'] == 34
        and type(record['currentCodecControls']) is int and record['currentCodecControls'] == 254
        and type(record['elapsedSeconds']) in (int, float) and math.isfinite(record['elapsedSeconds'])
        and 0 <= record['elapsedSeconds'] < 1320 and record['nativeEvidence'] == native[0],
        'supplement-receipt')
    materials = record['materials']
    require(type(materials) is dict, 'supplement-material-shape')
    selected = producer.materials(ROOT)
    required = {WORKFLOW, owner.WORKFLOW, 'tools/qualify_rust_capsules.py',
        'tools/rust_http_current_controls.py', 'tools/tests/test_rust_http_current_controls.py',
        'tools/sdk_native_products_reader.py', 'tools/tests/test_sdk_native_products_reader.py'}
    require(required <= set(materials) and all(materials.get(k) == v for k, v in selected.items()),
        'supplement-materials')
    current.committed_materials(head, materials)
    handoff = {name: file_identity(ROOT / name) for name in (SOURCE, TESTS, WORKFLOW)}
    current.committed_materials(head, handoff)
    historical_names = {owner.WORKFLOW, *(path for sources in owner.TEST_SOURCES.values() for path, _, _ in sources)}
    history = owner.historical_files(ROOT, historical_names)
    plan = owner.historical_plan(history[owner.WORKFLOW])
    tests = owner.historical_tests(history)
    elapsed = check_rows(record['commands'], plan, tests, native_record, ROOT, controls, owner, producer, read_file)
    native_elapsed = sum(row['seconds'] for row in native_record['commands'])
    require(elapsed + native_elapsed <= record['elapsedSeconds'] + 0.001,
        'original-overall-deadline-evidence')
    environment = build_environment(controls)
    environment['RUSTUP_TOOLCHAIN'] = '1.97.1'
    require(record['toolchain'] == owner.toolchain_snapshot(environment, ROOT, file_identity),
        'cross-job-toolchain-drift')
    return {'sourceRevision': head, 'nativeEvidence': native[0],
        'nativeProof': native[1], 'supplementReceipt': file_identity(controls / 'qualification.json', 16*1024**2),
        'handoffMaterials': handoff}


def write_origin(prepared, controls, output):
    from tools.rust_capsule_project import ROOT, checked_path, write_json
    ctx = context(os.environ, ROOT, 'native-controls')
    evidence = verify(prepared, controls)
    require(ctx['revision'] == evidence['sourceRevision'], 'origin-source')
    path = checked_path(output)
    require(path.parent == checked_path(controls) and path.name == 'same-run-origin.json' and not path.exists(),
        'origin-output')
    record = {'schemaVersion': ORIGIN_SCHEMA, 'producerJob': 'native-controls', 'context': ctx,
        'evidence': evidence, 'signedQualification': False}
    write_json(path, record)
    return record


def check_origin(origin, ctx):
    require(type(origin) is dict and set(origin) == {'schemaVersion', 'producerJob', 'context', 'evidence', 'signedQualification'}
        and origin['schemaVersion'] == ORIGIN_SCHEMA and origin['producerJob'] == 'native-controls'
        and origin['context'] == ctx and origin['signedQualification'] is False, 'same-run-origin')


def build(prepared, controls, output):
    from tools import rust_wasi_http_inputs as runtime
    from tools.phase3_resource_identity import file_identity
    from tools.rust_capsule_project import ROOT, checked_path, fresh, read_json, write_json
    ctx = context(os.environ, ROOT, 'current-backend')
    prepared, controls, output = map(checked_path, (prepared, controls, output))
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (prepared, controls, ROOT)), 'output-separation')
    origin = read_json(controls / 'same-run-origin.json', 1024**2)
    check_origin(origin, ctx)
    before = verify(prepared, controls)
    require(origin['evidence'] == before and before['sourceRevision'] == ctx['revision'], 'same-run-evidence')
    origin_id = file_identity(controls / 'same-run-origin.json', 1024**2)
    output = fresh(output)
    try:
        backend = runtime.install(output / 'backend')
        require(origin_id == file_identity(controls / 'same-run-origin.json', 1024**2)
            and before == verify(prepared, controls), 'post-build-input-change')
        record = {'schemaVersion': RESULT_SCHEMA, 'status': 'passed', 'context': ctx,
            'nativeOrigin': origin_id, 'nativeEvidence': before,
            'backendReceipt': file_identity(backend / runtime.RECEIPT, 1024**2),
            'qualification': 'compiled-adapter-only', 'signedQualification': False,
            'guestComponentsBuilt': 0, 'historicalReceiptRewritten': False}
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'schemaVersion': RESULT_SCHEMA, 'status': 'failed',
                'errorCategory': type(error).__name__, 'signedQualification': False})
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('origin', 'build'))
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--controls', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = write_origin(args.prepared, args.controls, args.output) if args.mode == 'origin' else build(args.prepared, args.controls, args.output)
    print(result['schemaVersion'])


if __name__ == '__main__':
    main()
