"""Fixed-aa56 component replay; fresh signing/node work, never guest/native compilation."""
from __future__ import annotations
import argparse
import hashlib
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

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_http_phases import MATERIALS, component_profile, native_source
from tools.java_http_phase_fixture import SOURCE as APP_SOURCE, WORLD as APP_WORLD
from tools.java_http_phase_node import run as phase_controls
from tools.java_http_tenant_node import run as tenant_controls
from tools.wait_runtime_native_products import verify_prepared as verify_native, native_products
from tools.rust_capsule_project import ROOT, digest, fresh, read_json, write_json

SOURCE = 'aa56bdebad8c12f20acce4ec4ecfeca73cf554be'
TESTED = '370e0653078715807ae538de437a36aa6a05a68f'
RUN, JOB = 39481897196, 118832292958
ARTIFACT = {'id': 12290889682, 'size_in_bytes': 2970741,
    'digest': 'sha256:f7cea4de68616aa1d6f9b6e76d0e5d786f04388b28fe25dc0891f18e99d45190'}
PINS = 'tools/fixtures/java-http-phase-prepared-aa56.json'
PREFIX = 'java-http-phases/campaign/build/'
CHANGES = {
    'tools/java_http_phase_node.py': 'sha256:3842a061ebcbbb44f06ef7092dcc5650a6f3b1071da7dd9800e99110a6173044',
    'tools/java_http_tenant_node.py': 'sha256:276bfbea12fc54471450d0142394440cc68b1838856a80bc62a3b3bf7192652c'}


def pins():
    value = read_json(ROOT/PINS)
    require(type(value) is dict and len(value) == 55 and sum(v['bytes'] for v in value.values()) < 128*1024**2,
        'java-phase-replay-pin-count')
    for name, row in value.items():
        safe(name)
        require(type(row['bytes']) is int and 0 < row['bytes'] <= 64*1024**2,
            'java-phase-replay-file-bound')
    return value


def safe(name):
    require(type(name) is str, 'java-phase-replay-path')
    p = PurePosixPath(name)
    require(p.as_posix() == name and not p.is_absolute()
        and '..' not in p.parts and '\\' not in name, 'java-phase-replay-path')
    return p


def verify_files(build):
    expected = pins()
    for name, row in expected.items():
        require(file_identity(build/name, 64*1024**2) == row, 'java-phase-replay-retained-identity')
    return expected


def restore_layers(build):
    """Restore only declared original inputs from identical authenticated package layers."""
    expected = read_json(build/'package-inputs.json');source = read_json(build/'package-source.json')
    for layer in source['layers']:
        name = layer['source'];safe(name);safe(layer['path'])
        require(name in expected, 'java-phase-replay-layer-not-original')
        target = build/name
        if not target.exists():
            original = build/'package/layers'/layer['path']
            require(file_identity(original, 64*1024**2) == {
                'sha256': expected[name]['digest'], 'bytes': expected[name]['size']},
                'java-phase-replay-layer-original-identity')
            target.parent.mkdir(parents=True, exist_ok=True)
            with original.open('rb') as source_file, target.open('xb') as output:
                while chunk := source_file.read(65536): output.write(chunk)
    for name, row in expected.items():
        safe(name)
        require(file_identity(build/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-phase-replay-original-package-inputs')
    return expected


def source_proof(build):
    snapshot = read_json(build/'source-inputs.json')
    vendor = {name[len('vendor/lsf/'):]: row for name, row in snapshot.items()
        if name.startswith('vendor/lsf/')}
    require(len(vendor) == 199, 'java-phase-replay-original-sdk-source-count')
    for name, row in vendor.items():
        safe(name)
        require(file_identity(ROOT/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-phase-replay-captured-sdk-source-drift')
    for original, current in [('src/dev/latent/app/Capsule.java', APP_SOURCE), ('wit/world.wit', APP_WORLD)]:
        row = snapshot[original]
        require(file_identity(ROOT/current, 4*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-phase-replay-original-application-source-drift')
    recipe = read_json(build/'recipe-inputs.json')
    for name, row in recipe.items():
        safe(name)
        require(file_identity(ROOT/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-phase-replay-current-compilation-recipe-drift')
    names = list(dict.fromkeys(MATERIALS));require(len(names) < 256, 'java-phase-replay-source-count')
    entries = subprocess.check_output(['git', 'ls-tree', '-rz', TESTED, '--', *names], cwd=ROOT, timeout=30)
    require(len(entries) < 1024**2, 'java-phase-replay-source-tree-bound')
    rows = []
    for entry in entries.rstrip(b'\0').split(b'\0'):
        meta, name = entry.split(b'\t');mode, kind, oid = meta.decode().split();name = name.decode()
        require(mode in ('100644', '100755') and kind == 'blob' and name in names,
            'java-phase-replay-source-regular')
        rows.append((name, oid))
    require(len(rows) == len(names) and {n for n, _ in rows} == set(names), 'java-phase-replay-source-complete')
    raw = subprocess.check_output(['git', 'cat-file', '--batch'], input=''.join(o+'\n' for _, o in rows).encode(),
        cwd=ROOT, timeout=30);require(len(raw) < 16*1024**2, 'java-phase-replay-source-batch-bound')
    position = 0;changed = {}
    for name, oid in rows:
        line = raw.index(b'\n', position);header = raw[position:line].decode().split();size = int(header[2])
        require(header[:2] == [oid, 'blob'] and 0 < size <= 4*1024**2, 'java-phase-replay-source-header')
        data = raw[line+1:line+1+size];position = line+size+2
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data, usedforsecurity=False).hexdigest() == oid,
            'java-phase-replay-source-object')
        current = file_identity(ROOT/name, 4*1024**2)
        if current['sha256'] != digest(data):
            require(CHANGES.get(name) == current['sha256'], 'java-phase-replay-unreviewed-source-change')
            changed[name] = {'compiled': {'sha256': digest(data), 'bytes': size}, 'fixture': current,
                'scope': 'explicit-operator-and-node-component-input-ceilings-only'}
    require(position == len(raw) and set(changed) == set(CHANGES), 'java-phase-replay-source-change-scope')
    return {'compiledFeature': SOURCE, 'compiledTestedSource': TESTED, 'recipeFilesExact': len(recipe), 'capturedSdkFilesExact': len(vendor),
        'fixtureAndCompilerMaterialsCompared': len(names), 'reviewedControllerChanges': changed,
        'compiledRecipeBytesEqualCurrent': True}


def validate_build(build):
    verify_files(build);original = restore_layers(build)
    marker = read_json(build/'BUILD-COMPLETE.json');observation = read_json(build/'build-observation.json')
    component = file_identity(build/'component.wasm', 64*1024**2)
    require(marker['packageAssembled'] is True and marker['componentDigest'] == component['sha256']
        == observation['componentDigest'] and observation['componentSize'] == component['bytes']
        and marker['observationDigest'] == file_identity(build/'build-observation.json')['sha256']
        and marker['sourceDigest'] == observation['source']['snapshotDigest']
        == file_identity(build/'source-inputs.json')['sha256'], 'java-phase-replay-build-observation')
    component_profile(build)
    return {'component': component, 'originalPackageInputs': original, 'source': source_proof(build)}


def extract(raw, output):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'],
        'java-phase-replay-archive-identity')
    expected = pins();build = fresh(output)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist();require(len(entries) == 67 and len({x.filename for x in entries}) == 67,
            'java-phase-replay-archive-member-count')
        for info in entries:
            safe(info.filename)
            require(not info.is_dir() and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                and info.file_size <= 64*1024**2, 'java-phase-replay-member-type')
        require({x.filename[len(PREFIX):] for x in entries if x.filename.startswith(PREFIX)} == set(expected),
            'java-phase-replay-selected-member-set')
        for name, row in expected.items():
            info = archive.getinfo(PREFIX+name);require(info.file_size == row['bytes'], 'java-phase-replay-member-size')
            data = archive.read(info);require(digest(data) == row['sha256'], 'java-phase-replay-member-digest')
            target = build/name;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(data)
    return validate_build(build)


def prepare(output):
    meta = api('actions/artifacts/'+str(ARTIFACT['id']))
    require({k: meta[k] for k in ARTIFACT} == ARTIFACT and not meta['expired']
        and meta['name'] == 'java-http-phases-'+TESTED
        and meta['workflow_run']['id'] == RUN and meta['workflow_run']['head_sha'] == SOURCE,
        'java-phase-replay-artifact-origin')
    job = api('actions/jobs/'+str(JOB))
    require(job['run_id'] == RUN and job['head_sha'] == SOURCE and job['status'] == 'completed'
        and job['conclusion'] == 'failure', 'java-phase-replay-original-failure-origin')
    token = os.environ.get('GH_TOKEN');require(bool(token), 'java-phase-replay-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer '+token})
    try: urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'java-phase-replay-redirect');url = error.headers['Location']
    else: raise ValueError('java-phase-replay-redirect-required')
    require(url.startswith('https://'), 'java-phase-replay-https')
    remote = Ranges(url, ARTIFACT['size_in_bytes']);raw = remote.read(ARTIFACT['size_in_bytes'])
    output = fresh(output);proof = extract(raw, output/'build')
    write_json(output/'retrieval.json', {'schemaVersion': 'latent.java.http.phase-prepared.v1',
        'artifact': ARTIFACT, 'run': RUN, 'job': JOB, 'originalOutcome': 'failed-before-publication',
        'build': proof, 'wholeArchiveSha256Verified': True, 'historicalReceiptRewritten': False})


def run(output, prepared, native):
    output = fresh(output);history = read_json(prepared/'retrieval.json')
    before = validate_build(prepared/'build');native_before = verify_native(native);native_identity = native_source(native)
    current = {name: file_identity(ROOT/name) for name in (*MATERIALS, PINS, 'tools/replay_java_http_phases.py')}
    require(history['artifact'] == ARTIFACT and history['build'] == before, 'java-phase-replay-prepared-drift')
    deadline = time.monotonic()+900;binaries = native_products(native)
    clients = phase_controls(prepared/'build', {n:binaries[n] for n in ('latent','latentd','capsule_authoring')},
        output/'node', deadline=deadline)
    require(clients['status'] == 'passed' and len(clients['cases']) == 16, 'java-phase-replay-original-client-cases')
    tenants = tenant_controls(prepared/'build', {n:binaries[n] for n in ('latent','latentd','capsule_authoring')},
        output/'tenants', deadline=deadline)
    require(tenants['status'] == 'passed' and len(tenants['cases']) == tenants['invocations'] == 12
        and tenants['httpContacts'] == 10, 'java-phase-replay-original-tenant-cases')
    require(before == validate_build(prepared/'build') and native_before == verify_native(native)
        and native_identity == native_source(native) and current == {n:file_identity(ROOT/n) for n in current}
        and time.monotonic() < deadline, 'java-phase-replay-final-material-drift')
    result = {'schemaVersion': 'latent.java.http.phase-node-replay.v1', 'status': 'passed',
        'originalBuild': history, 'native': native_before, 'nativeProductionSourceProof': native_identity,
        'fixtureSource': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'guestComponentsCompiledByReplay': 0, 'nativeProductsCompiledByReplay': 0,
        'freshOrdinarySigning': True, 'historicalReceiptRewritten': False,
        'node': file_identity(output/'node/qualification.json'), 'tenants': file_identity(output/'tenants/qualification.json'),
        'outcomes': 30, 'httpContacts': 23, 'materials': current, 'full688Qualified': False}
    write_json(output/'qualification.json', result);return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true');parser.add_argument('--prepared', type=Path)
    parser.add_argument('--native', type=Path);args = parser.parse_args()
    require(sys.platform == 'linux' and ROOT not in args.output.absolute().parents, 'java-phase-replay-owned-linux-output')
    if args.prepare: prepare(args.output)
    else: run(args.output, args.prepared, args.native)
