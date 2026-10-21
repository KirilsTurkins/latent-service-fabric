"""Authenticate the fixed aa56 Java component; never compile or relabel it."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import PurePosixPath
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_http_phase_fixture import SOURCE as APP_SOURCE, WORLD as APP_WORLD
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_http_phases import component_profile
from tools.rust_capsule_project import ROOT, digest, fresh, read_json, write_json

SOURCE = 'aa56bdebad8c12f20acce4ec4ecfeca73cf554be'
TESTED = '370e0653078715807ae538de437a36aa6a05a68f'
RUN, JOB = 39481897196, 118832292958
ARTIFACT = {'id': 12290889682, 'size_in_bytes': 2970741,
    'digest': 'sha256:f7cea4de68616aa1d6f9b6e76d0e5d786f04388b28fe25dc0891f18e99d45190'}
PREFIX = 'java-http-phases/campaign/build/'
PINS = 'tools/fixtures/java-http-phase-prepared-aa56.json'
PIN_IDENTITY = {'sha256': 'sha256:3cb19e71edcafa43c34aefcb40e4dcf45e919c7988c446c661c133c270fb6fab', 'bytes': 8541}
# Exact reviewed differences from the historical compiler, not an equivalence
# or current-compilation claim. Every other captured SDK/recipe byte must match.
CURRENT_DIFFERENCES = {
    'Cargo.toml': 'sha256:4ee28537862de19fe3141bebdbe5a9890bcea53ff55cce33e9c31687dbbfe199',
    'tools/toolchain.toml': 'sha256:c1687cb481790783cca91b8423a676754ff8c3432e34b436c23df4f605a7f236',
    'sdk/java-guest/resources/conformance/ImmutableResourceModelControl.java':
        'sha256:6cf730ea3b53acd619fd6b1db58a908616607cdd820cf8e43067833082b9c51c',
    'tools/java_guest/resources.py': 'sha256:77389b62f5f820e03a81ef852105ab122087c381954d06283f79b7da394918c1',
    'sdk/profile/transaction-requirements-v1.json': 'sha256:9bb389824b6a2d3015727b5c17de25a51505339d0a4f6cf46199ffe520881cd5',
    'wit/host-abi-phase3-v7.json': 'sha256:c9c88ebe54f6a3e931c15943b87b01fe553a5420f403ed8bc15fe41c137687cf',
    'wit/host-abi-phase4-v1.json': 'sha256:e8d67cb2ca7f696296a28684d59f6663788888e8e0c06f2aafe1eab34f4f0403'}


def safe(name):
    require(type(name) is str and name not in ('', '.') and PurePosixPath(name).as_posix() == name
        and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
        and '\\' not in name and ':' not in name, 'java-retained-safe-relative-file')


def pins():
    require(file_identity(ROOT/PINS) == PIN_IDENTITY, 'java-retained-fixed-pin-source')
    value = read_json(ROOT/PINS)
    require(type(value) is dict and len(value) == 55, 'java-retained-pin-count')
    for name, row in value.items():
        safe(name)
        require(set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int
            and 0 < row['bytes'] <= 64*1024**2, 'java-retained-pin-bound')
    require(sum(row['bytes'] for row in value.values()) < 128*1024**2, 'java-retained-total-bound')
    return value


def git_preimages(rows):
    require(len(rows) == 271, 'java-retained-complete-compiler-source-count')
    for name in rows:safe(name)
    raw = subprocess.check_output(['git', 'ls-tree', '-rz', SOURCE, '--', *rows], cwd=ROOT, timeout=30)
    require(len(raw) < 1024**2, 'java-retained-source-tree-bound')
    entries = []
    for item in raw.rstrip(b'\0').split(b'\0'):
        metadata, name = item.split(b'\t');mode, kind, oid = metadata.decode().split();name = name.decode()
        require(mode in ('100644', '100755') and kind == 'blob' and name in rows,
            'java-retained-source-regular')
        entries.append((name, oid))
    require(len(entries) == len(rows) and {n for n, _ in entries} == rows.keys(), 'java-retained-source-complete')
    batch = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT,
        input=''.join(oid+'\n' for _, oid in entries).encode(), timeout=30)
    require(len(batch) < 16*1024**2, 'java-retained-source-batch-bound')
    position = 0
    for name, oid in entries:
        end = batch.index(b'\n', position);header = batch[position:end].decode().split();size = int(header[2])
        require(header[:2] == [oid, 'blob'] and 0 < size <= 4*1024**2, 'java-retained-source-header')
        data = batch[end+1:end+1+size];position = end+size+2
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data, usedforsecurity=False).hexdigest() == oid
            and rows[name] == {'digest': digest(data), 'size': size}, 'java-retained-original-compiler-source')
    require(position == len(batch), 'java-retained-source-framing')


def source_proof(build):
    snapshot = read_json(build/'source-inputs.json');recipe = read_json(build/'recipe-inputs.json')
    sdk = {name[len('vendor/lsf/'):]: row for name, row in snapshot.items() if name.startswith('vendor/lsf/')}
    require(len(sdk) == 199 and len(recipe) == 73, 'java-retained-original-source-inventories')
    require(all(sdk[name] == recipe[name] for name in sdk.keys() & recipe.keys()),
        'java-retained-overlapping-source-identity')
    rows = {**sdk, **recipe}
    for source, destination in (('src/dev/latent/app/Capsule.java', APP_SOURCE), ('wit/world.wit', APP_WORLD)):
        rows[destination] = snapshot[source]
    git_preimages(rows)
    changed = {}
    for name, row in rows.items():
        path = ROOT/name
        require(not any(p.is_symlink() for p in (path, *path.parents))
            and path.resolve(strict=True).is_relative_to(ROOT.resolve()), 'java-retained-current-source-escape')
        current = file_identity(path, 4*1024**2)
        if current != {'sha256': row['digest'], 'bytes': row['size']}:
            require(CURRENT_DIFFERENCES.get(name) == current['sha256'], 'java-retained-unreviewed-source-drift')
            changed[name] = {'compiled': row, 'current': current}
    require(changed.keys() == CURRENT_DIFFERENCES.keys(), 'java-retained-exact-reviewed-differences')
    return {'compiledSource': SOURCE, 'compiledTestedSource': TESTED, 'capturedSdkFiles': 199,
        'compiledRecipeFiles': 73, 'originalGitPreimagesVerified': len(rows), 'differences': changed,
        'currentComponentCompilationClaimed': False, 'compiledRecipeBytesEqualCurrent': False,
        'scope': 'historical component; reviewed .7 manifest/version and unexecuted resource-control differences'}


def validate(build):
    for name, row in pins().items():
        require(file_identity(build/name, 64*1024**2) == row, 'java-retained-file-identity')
    expected = read_json(build/'package-inputs.json');source = read_json(build/'package-source.json')
    require(len(expected) == 19 and len(source['layers']) == 18, 'java-retained-original-package-shape')
    for layer in source['layers']:
        name = layer['source'];safe(name);safe(layer['path'])
        require(name in expected, 'java-retained-original-package-layer')
        target = build/name
        if not target.exists():
            original = build/'package/layers'/layer['path']
            require(file_identity(original, 64*1024**2) == {
                'sha256': expected[name]['digest'], 'bytes': expected[name]['size']}, 'java-retained-original-layer-identity')
            target.parent.mkdir(parents=True, exist_ok=True)
            with original.open('rb') as source_file, target.open('xb') as destination:
                while chunk := source_file.read(65536):destination.write(chunk)
    for name, row in expected.items():
        safe(name)
        require(file_identity(build/name, 64*1024**2) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-retained-all-original-package-inputs')
    marker = read_json(build/'BUILD-COMPLETE.json');observation = read_json(build/'build-observation.json')
    component = file_identity(build/'component.wasm', 64*1024**2)
    require(marker['packageAssembled'] is True and marker['componentDigest'] == component['sha256']
        == observation['componentDigest'] and observation['componentSize'] == component['bytes']
        and marker['observationDigest'] == file_identity(build/'build-observation.json')['sha256']
        and marker['sourceDigest'] == observation['source']['snapshotDigest']
        == file_identity(build/'source-inputs.json')['sha256'], 'java-retained-build-observation')
    component_profile(build)
    return {'component': component, 'originalPackageInputs': expected, 'source': source_proof(build)}


def extract(raw, output):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'], 'java-retained-archive-identity')
    expected = pins();build = fresh(output)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == len({x.filename for x in entries}) == 67, 'java-retained-archive-member-count')
        for entry in entries:
            safe(entry.filename)
            require(not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                and entry.file_size <= 64*1024**2, 'java-retained-archive-regular-file')
        require({e.filename[len(PREFIX):] for e in entries if e.filename.startswith(PREFIX)} == expected.keys(),
            'java-retained-fixed-selected-members')
        for name, row in expected.items():
            entry = archive.getinfo(PREFIX+name)
            require(entry.file_size == row['bytes'], 'java-retained-member-size')
            data = archive.read(entry);require(digest(data) == row['sha256'], 'java-retained-member-digest')
            path = build/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
    return validate(build)


def prepare(output):
    meta = api('actions/artifacts/'+str(ARTIFACT['id']));job = api('actions/jobs/'+str(JOB))
    require({k: meta[k] for k in ARTIFACT} == ARTIFACT and not meta['expired']
        and meta['name'] == 'java-http-phases-'+TESTED and meta['workflow_run']['id'] == RUN
        and meta['workflow_run']['head_sha'] == SOURCE, 'java-retained-artifact-origin')
    require(job['run_id'] == RUN and job['head_sha'] == SOURCE and job['status'] == 'completed'
        and job['conclusion'] == 'failure', 'java-retained-original-failure-origin')
    token = os.environ.get('GH_TOKEN');require(bool(token), 'java-retained-explicit-retrieval-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'java-retained-redirect');url = error.headers['Location']
    else:raise ValueError('java-retained-redirect-required')
    require(url.startswith('https://'), 'java-retained-https')
    remote = Ranges(url, ARTIFACT['size_in_bytes']);raw = remote.read(ARTIFACT['size_in_bytes'])
    output = fresh(output);proof = extract(raw, output/'build')
    write_json(output/'retrieval.json', {'schemaVersion': 'latent.java.http.retained-component.v1',
        'artifact': ARTIFACT, 'run': RUN, 'job': JOB, 'originalOutcome': 'failed-before-publication',
        'build': proof, 'wholeArchiveSha256Verified': True, 'historicalReceiptRewritten': False})


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
