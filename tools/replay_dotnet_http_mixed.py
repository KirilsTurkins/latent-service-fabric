"""Authenticate one failed managed programme and continue only its unrun node cases."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import dotnet_http_mixed_continuation as continuation
from tools import dotnet_http_mixed_node as node, dotnet_http_tenant_node as tenants
from tools import qualify_dotnet_http_mixed as qualification
from tools import release_preparation_cli_native_products as products
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

SOURCE = '9af3b431816650679c85f3da6ee4f5ad28a8473e'
RUN = 39538704070
JOB = 119021245071
ARTIFACT = {'id': 12318579800, 'size_in_bytes': 11125405,
    'digest': 'sha256:5688a832869fba399e9664c182c2853ba9146fdc0fd9d8d9ae70bb0e0496b970'}
COMPONENT = {'sha256': 'sha256:5fb10e8d82dbcb78ee68ed9954b7cda3441e2fc28fc7327a2b37dab4b326782e', 'bytes': 5336241}
PREFIX = 'managed-http-mixed/'
WORKFLOW = '.github/workflows/dotnet-published-http.yml'
OWN = ('tools/replay_dotnet_http_mixed.py', 'tools/dotnet_http_mixed_continuation.py', WORKFLOW)


def validate_origin(metadata, job, run):
    require(all(metadata.get(key) == value for key, value in ARTIFACT.items())
        and metadata.get('expired') is False and metadata.get('workflow_run', {}).get('id') == RUN
        and metadata['workflow_run'].get('head_sha') == SOURCE and job.get('id') == JOB
        and job.get('run_id') == RUN and job.get('head_sha') == SOURCE
        and job.get('conclusion') == 'failure' and job.get('status') == 'completed'
        and run.get('id') == RUN and run.get('head_sha') == SOURCE
        and run.get('head_branch') == 'feat/dotnet-http-completion-20261021'
        and run.get('event') == 'workflow_dispatch' and run.get('path') == WORKFLOW
        and run.get('status') == 'completed' and run.get('conclusion') == 'failure',
        'managed-replay-exact-failed-original')


def unpack(raw, output):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'],
        'managed-replay-original-archive-identity')
    rows = [];total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        require(len(members) == len({row.filename for row in members}) == 351, 'managed-replay-fixed-member-count')
        for member in members:
            path = PurePosixPath(member.filename)
            require(member.orig_filename == member.filename and not path.is_absolute()
                and '..' not in path.parts and '\\' not in member.filename and ':' not in member.filename
                and path.as_posix() == member.filename and not member.is_dir()
                and path.parts[0] in {'managed-http-mixed', 'mixed-native', 'mixed-tools'}
                and not set(path.parts) & {'releases', 'credentials', 'private', 'keys'}
                and stat.S_IFMT(member.external_attr >> 16) != stat.S_IFLNK and not member.flag_bits & 1
                and 0 <= member.file_size <= 64*1024**2, 'managed-replay-public-regular-member')
            total += member.file_size
            require(total <= 64*1024**2, 'managed-replay-expanded-byte-bound')
            body = archive.read(member)
            require(len(body) == member.file_size, 'managed-replay-original-crc')
            rows.append({'path': member.filename, 'sha256': digest(body), 'bytes': len(body)})
            if member.filename.startswith(PREFIX+'build/') or member.filename in (
                    PREFIX+'FAILED.json', PREFIX+'catalogue-free-source.json', PREFIX+'node/FAILED.json',
                    PREFIX+'node/controls/managed-mixed-request-limit-result.json'):
                target = output.joinpath(*path.parts);target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:stream.write(body)
    return {'archive': ARTIFACT, 'members': rows, 'expandedBytes': total}


def prepare(output):
    output = fresh(output)
    metadata, job, run = (api(path) for path in (
        f'actions/artifacts/{ARTIFACT["id"]}', f'actions/jobs/{JOB}', f'actions/runs/{RUN}'))
    validate_origin(metadata, job, run)
    token = os.environ.get('GH_TOKEN');require(bool(token), 'managed-replay-explicit-retrieval-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'managed-replay-archive-redirect');url = error.headers['Location']
    else:raise ValueError('managed-replay-archive-redirect-required')
    require(url.startswith('https://'), 'managed-replay-archive-https')
    remote = Ranges(url, ARTIFACT['size_in_bytes']);parts = []
    for offset in range(0, ARTIFACT['size_in_bytes'], 8*1024**2):
        count = min(8*1024**2, ARTIFACT['size_in_bytes']-offset);part = remote.read(count)
        require(len(part) == count, 'managed-replay-archive-range');parts.append(part)
    value = unpack(b''.join(parts), output)
    write_json(output/'retrieval.json', {'run': run, 'job': job, 'artifact': metadata, **value})
    return value


def verify_original(prepared):
    retrieval = read_json(prepared/'retrieval.json', 2*1024**2)
    validate_origin(retrieval['artifact'], retrieval['job'], retrieval['run'])
    original = read_json(prepared/PREFIX/'FAILED.json', 4*1024**2)
    artifact = prepared/PREFIX/'build'
    require(original['status'] == 'failed' and original['fixtureSource'] == SOURCE
        and original['compiledNativeSource'] == products.SOURCE
        and original['nativeProducer']['producerReceipt'] == products.RECEIPTS['native-products.json']
        and original['nativeProducer']['sourceSnapshot'] == products.RECEIPTS['source-inputs.json']
        and original['stage'] == 'signed-default-http-content-and-work'
        and set(original['materials']) == set(qualification.MATERIALS), 'managed-replay-original-stage-and-native')
    material_rows = {}
    for name, expected in original['materials'].items():
        raw = subprocess.check_output(['git', 'show', SOURCE+':'+name], cwd=ROOT, timeout=15)
        require({'sha256': digest(raw), 'bytes': len(raw)} == expected, 'managed-replay-original-git-material')
        if name != WORKFLOW:require(file_identity(ROOT/name, 16*1024**2) == expected, 'managed-replay-current-original-material')
        material_rows[name] = expected
    require(json.loads(inventory(snapshot(ROOT/'sdk/dotnet-guest'))) == original['sdkSources'],
        'managed-replay-entire-original-sdk')
    for name, expected in read_json(artifact/'recipe-inputs.json').items():
        raw = read_file(ROOT/name, 16*1024**2)
        require({'digest': digest(raw), 'size': len(raw)} == expected, 'managed-replay-entire-original-recipe')
    marker = read_json(artifact/'BUILD-COMPLETE.json', 16*1024**2)
    observed = qualification.build_evidence(artifact)
    require(observed == original['build'] and observed['component'] == COMPONENT
        and marker['sourceDigest'] == digest(read_file(artifact/'source-inputs.json'))
        and all(row['exitCode'] == 0 for row in marker['commands'])
        and any(row['stage'] == 'native-aot' for row in marker['commands']), 'managed-replay-original-real-aot-and-package')
    failed = read_json(prepared/PREFIX/'node/FAILED.json')
    row = read_json(prepared/PREFIX/'node/controls/managed-mixed-request-limit-result.json')
    continuation.preserved_limit(row, row['response']['data']['resolvedRevision'],
        {'cpuFuel': 1000000000, 'memoryBytes': 134217728})
    require(failed['status'] == 'failed' and failed['stage'] == 'request-limit'
        and [case['mode'] for case in failed['cases']] == list(range(8))
        and failed['originalBuild'] == node.identities(artifact), 'managed-replay-original-failure-not-waived')
    return {'source': SOURCE, 'component': COMPONENT, 'materialRows': len(material_rows),
        'sdkFiles': len(original['sdkSources']), 'recipeFiles': len(read_json(artifact/'recipe-inputs.json')),
        'originalFailure': file_identity(prepared/PREFIX/'node/controls/managed-mixed-request-limit-result.json')}


def run(prepared, native_directory, output):
    prepared, native_directory = (Path(path).resolve(strict=True) for path in (prepared, native_directory))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != path and output not in path.parents and path not in output.parents
            for path in (prepared, native_directory)), 'managed-replay-separated-output')
    output = fresh(output);deadline = time.monotonic()+900
    native = products.native_products(native_directory);native_record = products.verify_prepared(native_directory)
    for path in native.values():path.chmod(0o700)
    proof = verify_original(prepared);original_native = source_identity(ROOT)
    material_rows = {name: file_identity(ROOT/name) for name in OWN}
    artifact = prepared/PREFIX/'build';build = node.identities(artifact)
    record = {'schemaVersion': 'latent.dotnet.http-mixed-replay.v1', 'status': 'failed',
        'programmeQualified': False, 'requestLimitQualified': False, 'originalRequestLimitFailurePreserved': True,
        'compiledGuestSource': SOURCE, 'compiledNativeSource': products.SOURCE,
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'newGuestComponentsCompiled': 0, 'newNativeProductsBuilt': 0, 'proof': proof,
        'sourceMaterials': material_rows, 'nativeProducer': native_record, 'casesSourceUnchanged': True}
    stage = 'continue-unrun-mixed-cases'
    try:
        continued = continuation.run(artifact, native, output/'node', deadline=deadline)
        require(continued['status'] == 'failed' and continued['diagnosticCompleted'] is True
            and continued['continuedInvocations'] == 11 and continued['freshAfterFailureInvocations'] == 1,
            'managed-replay-continuation-stays-failed')
        record['continuationReceipt'] = file_identity(output/'node/diagnostic.json')
        stage = 'unchanged-ten-tenant-cases'
        isolated = tenants.run(artifact, native, output/'tenants', deadline=deadline)
        require(isolated['status'] == 'passed' and isolated['invocations'] == 10
            and isolated['preEntryRefusals'] == isolated['credentialRefusals'] == 1 and isolated['httpContacts'] == 8,
            'managed-replay-all-original-tenant-cases')
        require(verify_original(prepared) == proof and products.verify_prepared(native_directory) == native_record
            and node.identities(artifact) == build and source_identity(ROOT) == original_native
            and material_rows == {name: file_identity(ROOT/name) for name in OWN} and time.monotonic() < deadline,
            'managed-replay-final-source-native-build-fences')
        record.update(diagnosticCompleted=True, continuedMixedOutcomes=11, freshAfterFailureOutcomes=1,
            tenantOutcomes=10, tenantReceipt=file_identity(output/'tenants/qualification.json'))
        write_json(output/'diagnostic.json', record)
        return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'diagnosticCompleted': False, 'stage': stage})
        except BaseException:pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run'))
    for name in ('output', 'prepared', 'native'):parser.add_argument('--'+name, type=Path, required=name == 'output')
    args = parser.parse_args()
    if args.mode == 'prepare':prepare(args.output)
    else:
        require(args.prepared is not None and args.native is not None, 'managed-replay-prepared-and-native-required')
        run(args.prepared, args.native, args.output)
        raise SystemExit('Original request-limit programme remains FAILED; diagnostic collection completed.')
