"""Authenticate the fixed e1c build; replay only fresh optional SPI node work."""
from __future__ import annotations
import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.java_http_spi_fixture import SOURCE as APP_SOURCE, WORLD as APP_WORLD
from tools.java_http_spi_node import run as node_controls
from tools.qualify_java_http_spi import MATERIALS
from tools.qualify_java_http_phases import component_profile, native_source
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_json, write_json
from tools.wait_runtime_native_products import verify_prepared, native_products

SOURCE = 'e1c33adb2414a8371026d479600e08d48b6df88a'
RUN, JOB = 39494971018, 118877563609
ARTIFACT = {'id': 12296844781, 'size_in_bytes': 2003357,
    'digest': 'sha256:cc7bc2b4aa07072943925f3a8aea098f338f9c3b44724a2f97fdad8e33bea9c4'}
PREFIX = 'java-http-spi/campaign/build/'
PINS = 'tools/fixtures/java-http-spi-prepared-e1c.json'
CONTROLLER = 'tools/java_http_spi_node.py'
CONTROLLER_DIGEST = 'sha256:f6ce9ebcbb7ccae0ff0fd94226d3e41b0f17b50cdc61c6292a98a1e9104010cd'


def safe(name):
    require(type(name) is str, 'java-spi-replay-path')
    path = PurePosixPath(name)
    require(path.as_posix() == name and not path.is_absolute()
        and '..' not in path.parts and '\\' not in name, 'java-spi-replay-path')


def pins():
    value = read_json(ROOT/PINS)
    require(type(value) is dict and len(value) == 55
        and sum(row['bytes'] for row in value.values()) < 128*1024**2, 'java-spi-replay-pin-count')
    for name, row in value.items():
        safe(name)
        require(type(row['bytes']) is int and 0 < row['bytes'] <= 64*1024**2,
            'java-spi-replay-file-bound')
    return value


def source_proof(build):
    snapshot = read_json(build/'source-inputs.json')
    vendor = {name.removeprefix('vendor/lsf/'): row for name, row in snapshot.items()
        if name.startswith('vendor/lsf/')}
    require(len(vendor) == 199, 'java-spi-replay-sdk-source-count')
    recipe = read_json(build/'recipe-inputs.json')
    require(len(recipe) == 73, 'java-spi-replay-recipe-count')
    for group in (vendor, recipe):
        for name, row in group.items():
            safe(name)
            require(file_identity(ROOT/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
                'java-spi-replay-compiler-or-sdk-drift')
    for original, current in [('src/dev/latent/app/Capsule.java', APP_SOURCE), ('wit/world.wit', APP_WORLD)]:
        row = snapshot[original]
        require(file_identity(ROOT/current) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-spi-replay-original-app-drift')
    names = list(dict.fromkeys(MATERIALS))
    require(len(names) < 256, 'java-spi-replay-material-count')
    entries = subprocess.check_output(['git', 'ls-tree', '-rz', SOURCE, '--', *names], cwd=ROOT, timeout=30)
    require(len(entries) < 1024**2, 'java-spi-replay-material-tree-bound')
    rows = []
    for entry in entries.rstrip(b'\0').split(b'\0'):
        meta, name = entry.split(b'\t');mode, kind, oid = meta.decode().split();name = name.decode()
        require(mode in ('100644', '100755') and kind == 'blob' and name in names,
            'java-spi-replay-material-regular')
        rows.append((name, oid))
    require(len(rows) == len(names) and {n for n, _ in rows} == set(names),
        'java-spi-replay-material-complete')
    raw = subprocess.check_output(['git', 'cat-file', '--batch'],
        input=''.join(oid+'\n' for _, oid in rows).encode(), cwd=ROOT, timeout=30)
    require(len(raw) < 16*1024**2, 'java-spi-replay-material-batch-bound')
    position = 0;changed = {}
    for name, oid in rows:
        end = raw.index(b'\n', position);header = raw[position:end].decode().split();size = int(header[2])
        require(header[:2] == [oid, 'blob'] and 0 < size <= 4*1024**2, 'java-spi-replay-material-header')
        data = raw[end+1:end+1+size];position = end+size+2
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data, usedforsecurity=False).hexdigest() == oid,
            'java-spi-replay-material-git-object')
        current = file_identity(ROOT/name)
        if current != {'sha256': digest(data), 'bytes': size}:
            require(name == CONTROLLER and current['sha256'] == CONTROLLER_DIGEST,
                'java-spi-replay-unreviewed-source-change')
            changed[name] = {'compiled': {'sha256': digest(data), 'bytes': size}, 'reader': current}
    require(position == len(raw) and set(changed) == {CONTROLLER}, 'java-spi-replay-reader-only-scope')
    return {'compiledSource': SOURCE, 'sdkFilesExact': 199, 'recipeFilesExact': 73,
        'materialFilesCompared': len(names), 'reviewedReaderCorrection': changed}


def validate_build(build):
    for name, row in pins().items():
        require(file_identity(build/name, 64*1024**2) == row, 'java-spi-replay-retained-identity')
    original = read_json(build/'package-inputs.json')
    for layer in read_json(build/'package-source.json')['layers']:
        name = layer['source'];safe(name);safe(layer['path'])
        require(name in original, 'java-spi-replay-layer-not-original')
        target = build/name
        if not target.exists():
            source = build/'package/layers'/layer['path']
            require(file_identity(source, 64*1024**2) == {
                'sha256': original[name]['digest'], 'bytes': original[name]['size']},
                'java-spi-replay-original-layer')
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as source_file, target.open('xb') as destination:
                while chunk := source_file.read(65536): destination.write(chunk)
    for name, row in original.items():
        safe(name)
        require(file_identity(build/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-spi-replay-original-package-inputs')
    marker = read_json(build/'BUILD-COMPLETE.json');observation = read_json(build/'build-observation.json')
    component = file_identity(build/'component.wasm', 64*1024**2)
    require(marker['packageAssembled'] is True and marker['componentDigest'] == component['sha256']
        == observation['componentDigest'] and observation['componentSize'] == component['bytes']
        and marker['observationDigest'] == file_identity(build/'build-observation.json')['sha256']
        and marker['sourceDigest'] == observation['source']['snapshotDigest']
        == file_identity(build/'source-inputs.json')['sha256'], 'java-spi-replay-original-observation')
    component_profile(build, 'java-spi-replay-component-profile')
    return {'component': component, 'originalPackageInputs': original, 'source': source_proof(build)}


def extract(raw, output):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'],
        'java-spi-replay-whole-archive-identity')
    expected = pins();build = fresh(output)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == len({row.filename for row in entries}) == 105
            and sum(row.file_size for row in entries) < 128*1024**2, 'java-spi-replay-archive-bound')
        for row in entries:
            safe(row.filename)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                and row.file_size <= 64*1024**2, 'java-spi-replay-member-type')
        require(archive.testzip() is None, 'java-spi-replay-crc')
        require({row.filename[len(PREFIX):] for row in entries if row.filename.startswith(PREFIX)} == set(expected),
            'java-spi-replay-selected-member-set')
        for name, row in expected.items():
            entry = archive.getinfo(PREFIX+name)
            require(entry.file_size == row['bytes'], 'java-spi-replay-member-size')
            data = archive.read(entry);require(digest(data) == row['sha256'], 'java-spi-replay-member-digest')
            target = build/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
    return validate_build(build)


def prepare(output):
    metadata = api('actions/artifacts/'+str(ARTIFACT['id']))
    require({k: metadata[k] for k in ARTIFACT} == ARTIFACT and not metadata['expired']
        and metadata['name'] == 'java-http-spi-'+SOURCE and metadata['workflow_run']['id'] == RUN
        and metadata['workflow_run']['head_sha'] == SOURCE, 'java-spi-replay-artifact-origin')
    job = api('actions/jobs/'+str(JOB))
    require(job['run_id'] == RUN and job['head_sha'] == SOURCE and job['status'] == 'completed'
        and job['conclusion'] == 'failure', 'java-spi-replay-failed-job-origin')
    token = os.environ.get('GH_TOKEN');require(bool(token), 'java-spi-replay-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer '+token})
    try: urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'java-spi-replay-redirect');url = error.headers['Location']
    else: raise ValueError('java-spi-replay-redirect-required')
    require(url.startswith('https://'), 'java-spi-replay-https')
    remote = Ranges(url, ARTIFACT['size_in_bytes']);raw = remote.read(ARTIFACT['size_in_bytes'])
    output = fresh(output);proof = extract(raw, output/'build')
    write_json(output/'retrieval.json', {'schemaVersion': 'latent.java.http.spi-prepared.v1',
        'artifact': ARTIFACT, 'run': RUN, 'job': JOB, 'originalOutcome': 'failure-after-first-guest-success',
        'build': proof, 'wholeArchiveSha256Verified': True, 'historicalReceiptRewritten': False})


def run(output, prepared, native):
    output = fresh(output);history = read_json(prepared/'retrieval.json')
    before = validate_build(prepared/'build');products = verify_prepared(native);identity = native_source(native)
    materials = {name: file_identity(ROOT/name) for name in (*MATERIALS, PINS, 'tools/replay_java_http_spi.py')}
    require(history['artifact'] == ARTIFACT and history['build'] == before, 'java-spi-replay-prepared-drift')
    binaries = native_products(native);deadline = time.monotonic()+600
    result = node_controls(prepared/'build', {n:binaries[n] for n in ('latent', 'latentd', 'capsule_authoring')},
        output/'node', deadline=deadline)
    require(result['status'] == 'passed' and len(result['cases']) == result['invocations'] == 6
        and result['authorityDenials'] == 2 and result['httpContacts'] == 4, 'java-spi-replay-incomplete-programme')
    require(before == validate_build(prepared/'build') and products == verify_prepared(native)
        and identity == native_source(native) and materials == {n:file_identity(ROOT/n) for n in materials}
        and time.monotonic() < deadline, 'java-spi-replay-final-source-or-products-drift')
    final = {'schemaVersion': 'latent.java.http.spi-node-replay.v1', 'status': 'passed',
        'originalBuild': history, 'native': products, 'nativeProductionSourceProof': identity,
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'materials': materials, 'invocations': 6, 'authorityDenials': 2, 'httpContacts': 4,
        'node': file_identity(output/'node/qualification.json'), 'guestComponentsCompiledByReplay': 0,
        'nativeProductsCompiledByReplay': 0, 'historicalReceiptRewritten': False,
        'defaultClientQualification': False, 'sameNodeCrossTenantHttpQualified': False,
        'full688Qualified': False, 'full741Qualified': False}
    write_json(output/'qualification.json', final);return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True);parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepared', type=Path);parser.add_argument('--native', type=Path)
    args = parser.parse_args()
    require(sys.platform == 'linux' and ROOT not in args.output.absolute().parents,
        'java-spi-replay-owned-linux-output')
    if args.prepare: prepare(args.output)
    else: run(args.output, args.prepared, args.native)
