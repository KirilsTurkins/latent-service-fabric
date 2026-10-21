"""Execute the exact completed df4 AOT package after its profile-reader repair."""
from __future__ import annotations

import argparse
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import release_preparation_cli_native_products as products
from tools import resource_late_facilities as late
from tools import qualify_dotnet_resource_runtime as base
from tools.java_replay_materials import api, git_source_identity, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

SOURCE = 'df4f5628add1a9ba9b1562ee00353fad57e4f7d5'
RUN, JOB = 39617997010, 119283819097
ARTIFACT = {'id': 12353339133, 'size_in_bytes': 8275406,
    'digest': 'sha256:11756833ae82517f0d8c21548dad42648dd3ea80ae2a130d10a2c629a11a85be'}
COMPONENT = {'sha256': 'sha256:8187d723f0c41b6232752a2a3e265cdbbde85b6dc6df7991af3d6489ae1e09b1', 'bytes': 2783038}
PREFIX = 'dotnet-resource-late/'
PREFIXES = {'dotnet-resource-late', 'dotnet-resource-late-reference', 'dotnet-resource-native', 'dotnet-resource-tools'}
READER = 'tools/qualify_dotnet_resource_runtime.py'
WORKFLOW = '.github/workflows/dotnet-resource-runtime.yml'
CHANGED = {
    READER: {'sha256': 'sha256:246f199200581ce3b1795585c0d868bfcbdf704b9e567fa8c30f05e9fc6aea69', 'bytes': 20848},
    WORKFLOW: {'sha256': 'sha256:da03d35554ebc1bb71bd606b86b7d8cd90ac92a0b2fbd4439439098b1ede644e', 'bytes': 15595},
}
WIT = {'wit/deps/activation-runtime/package.wit', 'wit/deps/clock/package.wit',
    'wit/deps/log/package.wit', 'wit/deps/random/package.wit', 'wit/world.wit'}


def validate_origin(metadata, job, run):
    require(all(metadata.get(key) == value for key, value in ARTIFACT.items())
        and metadata.get('expired') is False and metadata['workflow_run']['id'] == RUN
        and metadata['workflow_run']['head_sha'] == SOURCE
        and job.get('id') == JOB and job.get('run_id') == RUN and job.get('head_sha') == SOURCE
        and job.get('status') == 'completed' and job.get('conclusion') == 'failure'
        and all(run.get(key) == value for key, value in {
            'id': RUN, 'head_sha': SOURCE, 'head_branch': 'feat/java-dotnet-late-facilities-20261021',
            'path': WORKFLOW, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}.items()),
        'resource-late-replay-exact-failed-origin')


def archive_members(raw):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'],
        'resource-late-replay-original-whole-archive')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        require(len(rows) == 223 and len({row.filename for row in rows}) == len(rows),
            'resource-late-replay-archive-count-and-duplicates')
        total = 0
        for row in rows:
            path = PurePosixPath(row.filename)
            require(row.orig_filename == row.filename and not path.is_absolute() and path.parts
                and path.parts[0] in PREFIXES and '..' not in path.parts and path.as_posix() == row.filename
                and ':' not in row.filename and '\\' not in row.filename and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) != stat.S_IFLNK and not row.flag_bits & 1
                and not any(part.endswith(('.key', '.pem', '.pfx', '.p12')) for part in path.parts)
                and 0 <= row.file_size <= 64*1024**2, 'resource-late-replay-public-regular-member')
            total += row.file_size
            require(total <= 64*1024**2, 'resource-late-replay-expanded-bound')
            data = archive.read(row)
            require(len(data) == row.file_size, 'resource-late-replay-crc-and-length')
            yield row.filename, data


def acquire(output):
    output = fresh(Path(output).absolute())
    metadata, job, run = api(f'actions/artifacts/{ARTIFACT["id"]}'), api(f'actions/jobs/{JOB}'), api(f'actions/runs/{RUN}')
    validate_origin(metadata, job, run)
    token = os.environ.get('GH_TOKEN'); require(bool(token), 'resource-late-replay-retrieval-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer '+token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'resource-late-replay-api-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('resource-late-replay-api-redirect-required')
    token = request = None
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.port in (None, 443) and parsed.username is None
        and parsed.password is None and not parsed.fragment and parsed.hostname
        and parsed.hostname.endswith('.blob.core.windows.net'), 'resource-late-replay-public-artifact-host')
    raw = Ranges(url, ARTIFACT['size_in_bytes']).read(ARTIFACT['size_in_bytes'])
    (output/'artifact.zip').write_bytes(raw)
    members = {}
    for name, data in archive_members(raw):
        target = output/'contents'/name
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        members[name] = {'sha256': digest(data), 'bytes': len(data)}
    build = output/'contents'/PREFIX/'build'
    restored = {}
    for name, expected in read_json(build/'package-inputs.json').items():
        target = build/name
        if not target.exists():
            require(name in WIT, 'resource-late-replay-only-original-wit-restoration')
            data = read_file(build/'package/layers'/name, 256*1024)
            require({'digest': digest(data), 'size': len(data)} == expected,
                'resource-late-replay-original-wit-layer-bytes')
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
            restored[name] = {'sha256': digest(data), 'bytes': len(data)}
    record = {'schemaVersion': 'latent.dotnet.resource-late-acquisition.v1', 'artifact': metadata,
        'job': job, 'run': run, 'members': members, 'restoredOriginalWit': restored,
        'guestQualification': False, 'originalFailurePreserved': True}
    write_json(output/'retrieval.json', record)
    return record


def prepared(directory):
    record = read_json(directory/'retrieval.json')
    validate_origin(record['artifact'], record['job'], record['run'])
    members = {name: {'sha256': digest(data), 'bytes': len(data)}
        for name, data in archive_members(read_file(directory/'artifact.zip', 8*1024**2))}
    require(members == record['members'] and all(file_identity(directory/'contents'/name, 64*1024**2) == row
        for name, row in members.items()), 'resource-late-replay-retained-original-members')
    build = directory/'contents'/PREFIX/'build'
    require(set(record['restoredOriginalWit']) == WIT
        and all(file_identity(build/name) == row for name, row in record['restoredOriginalWit'].items()),
        'resource-late-replay-five-authenticated-wit-layers')
    return build, read_json(directory/'contents'/PREFIX/'FAILED.json'), record


def original_materials(original, build):
    require(original['source'] == SOURCE and original['status'] == 'failed'
        and original['stage'] == 'one-fresh-offline-normal-native-aot-component'
        and original['newGuestComponentsCompiled'] == 1 and original['newNativeProductsBuilt'] == 0
        and original['consumerNativeCompiledByThisCampaign'] is False
        and original['consumerNativeSourceObservation'] == git_source_identity(SOURCE),
        'resource-late-replay-original-build-not-guest-execution')
    expected = dict(original['materials'])
    for name, row in original['sdkSources'].items():
        expected['sdk/dotnet-guest/'+name] = {'sha256': row['digest'], 'bytes': row['size']}
    for name, row in read_json(build/'recipe-inputs.json').items():
        value = {'sha256': row['digest'], 'bytes': row['size']}
        require(name not in expected or expected[name] == value, 'resource-late-replay-consistent-source-preimage')
        expected[name] = value
    names = sorted(expected)
    raw = subprocess.check_output(['git', 'cat-file', '--batch'], input=''.join(SOURCE+':'+name+'\n' for name in names).encode(),
        cwd=ROOT, timeout=60)
    require(len(raw) <= 32*1024**2, 'resource-late-replay-original-source-bound')
    offset = 0; changes = {}
    import hashlib
    for name in names:
        end = raw.index(b'\n', offset); oid, kind, length = raw[offset:end].decode().split(); size = int(length); offset = end+1
        data = raw[offset:offset+size]; offset += size
        require(kind == 'blob' and raw[offset:offset+1] == b'\n'
            and hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data).hexdigest() == oid
            and {'sha256': digest(data), 'bytes': len(data)} == expected[name],
            'resource-late-replay-exact-git-blob-preimage')
        offset += 1
        current = file_identity(ROOT/name)
        if name in CHANGED:
            require(current == CHANGED[name], 'resource-late-replay-exact-reviewed-consumer-change')
            changes[name] = {'original': expected[name], 'consumer': current}
        else:
            require(current == expected[name], 'resource-late-replay-unchanged-compiled-material')
    require(offset == len(raw) and set(changes) == set(CHANGED), 'resource-late-replay-only-reader-and-owning-workflow-delta')
    return {'sourceFiles': len(names), 'sdkFiles': len(original['sdkSources']),
        'recipeFiles': len(read_json(build/'recipe-inputs.json')), 'reviewedConsumerChanges': changes}


def replay(directory, native_directory, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and not os.environ.get('GH_TOKEN'),
        'resource-late-replay-linux-python313-token-free-execution')
    directory, native_directory, output = Path(directory).resolve(strict=True), Path(native_directory).resolve(strict=True), Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != item and item not in output.parents and output not in item.parents for item in (directory, native_directory)),
        'resource-late-replay-owned-separated-output')
    output = fresh(output)
    build, original, acquisition = prepared(directory)
    compiled = products.verify_prepared(native_directory); native = products.native_products(native_directory)
    for path in native.values(): path.chmod(0o700)
    native_before = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    consumer = source_identity(ROOT); sdk = inventory(snapshot(ROOT/'sdk/dotnet-guest'))
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip()
    material_names = (*base.MATERIALS, 'tools/replay_dotnet_resource_late.py', 'tools/resource_late_facilities.py',
        'tools/sdk_native_products_reader.py', 'tools/release_preparation_cli_native_products.py',
        'tools/java_http_release_preparation.py', 'tools/fixtures/dotnet-resource-late/Library.cs')
    materials = {name: file_identity(ROOT/name) for name in dict.fromkeys(material_names)}
    before = base.build_evidence(build)
    record = {'schemaVersion': 'latent.dotnet.resource-late-replay.v1', 'status': 'incomplete', 'source': source,
        'compiledGuestSource': SOURCE, 'compiledNativeSource': products.SOURCE, 'compiledNative': compiled,
        'consumerNativeSourceObservation': consumer, 'consumerNativeCompiledByThisCampaign': False,
        'materials': materials, 'sdkSources': read_json(directory/'contents'/PREFIX/'FAILED.json')['sdkSources'],
        'newNativeProductsBuilt': 0, 'newGuestComponentsCompiled': 0, 'fullTicketQualification': False,
        'originalOuterFailurePreserved': True, 'build': before, 'originalAcquisition': file_identity(directory/'retrieval.json'),
        'frozenLogAccountingSources': late.accounting_sources(products.SOURCE)}
    try:
        record['sourceProof'] = original_materials(original, build)
        require(before['component'] == COMPONENT and original['compiledNative'] == compiled,
            'resource-late-replay-same-component-and-original-native-tuple')
        observed = base.execute(build, native, output/'node', late_completion=True, deadline=time.monotonic()+600)
        require(observed['status'] == 'passed' and observed['lateFacilitiesOnly'] is True
            and observed['originalProgrammePassed'] is False and len(observed['preparation']) == 2
            and len(observed['runtimeGrantDenials']) == 2 and len(observed['programme']['cases']) == 4
            and base.build_evidence(build) == before and prepared(directory)[2] == acquisition
            and original_materials(original, build) == record['sourceProof']
            and products.verify_prepared(native_directory) == compiled and source_identity(ROOT) == consumer
            and inventory(snapshot(ROOT/'sdk/dotnet-guest')) == sdk
            and {name: file_identity(path, 512*1024**2) for name, path in native.items()} == native_before
            and {name: file_identity(ROOT/name) for name in materials} == materials
            and late.accounting_sources(products.SOURCE) == record['frozenLogAccountingSources']
            and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == source,
            'resource-late-replay-final-original-materials-and-physical-retirement')
        record.update(status='passed', outcomes=6, signedAndAdmitted=True,
            nodeReceipt=file_identity(output/'node/qualified.json'))
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('acquire', 'run'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--native', type=Path)
    args = parser.parse_args()
    if args.command == 'acquire':
        print(acquire(args.output)['guestQualification'])
    else:
        parser.error('--prepared and --native are required for run') if args.prepared is None or args.native is None else None
        print(replay(args.prepared, args.native, args.output)['status'])
