"""Authenticate one failed GC producer's completed component, without compilation."""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile

from tools import java_checkpoint_gc_fixture as fixture
from tools.java_replay_materials import NoRedirect, Ranges, REPOSITORY, api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_checkpoint_gc import MATERIALS, build_evidence
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

SOURCE = 'a5c4385300f26c3a883b50d77a03e0719d918873'
RUN, JOB = 39960502389, 120437000727
ARTIFACT = {'id': 12505280538, 'size_in_bytes': 1164680,
    'digest': 'sha256:a5d716168294867fa5656254be644fb9a8008762648d071f2ddc349ba403aca3'}
PINS = 'tools/fixtures/java-checkpoint-gc-retained-a5c.json'
PIN_IDENTITY = {'bytes': 18816,
    'sha256': 'sha256:347fbd183693580c9854829c290ae76d253987b0f4bd585240fd72f3e5e13da8'}
# Only the corrected generated-C reader and the runtime-only workflow change.
# No captured Java, compiler, recipe, native reader or node programme may drift.
CURRENT_DIFFERENCES = {'tools/qualify_java_checkpoint_gc.py': {'bytes': 13749, 'sha256': 'sha256:2111697405ea1704e1749564701c29552a4a97522dca08fc9b658e2bfb256769'}, '.github/workflows/java-checkpoint-gc.yml': {'bytes': 8836, 'sha256': 'sha256:43edcb7cabbd02c3843befecba6845a946f6c4b5ca2f6110824ce09e58cfc0e8'}}
LIBRARY_URL = ('https://repo.maven.apache.org/maven2/org/apache/commons/'
    'commons-lang3/3.14.0/commons-lang3-3.14.0.jar')
LIBRARY_IDENTITY = {'bytes': 657952, 'sha256': fixture.JAR}
RESOURCE_MEMBERS = {
    'resources/objects/110438863bad37c28f906bf87016e38c7a8c758ba321e09d11dc5a2363a8e79e':
        'META-INF/maven/org.apache.commons/commons-lang3/pom.xml',
    'resources/objects/fd89b9f3d9988cfc74c3635ff31d008e261dc008804aeb344e1218362d83b20d':
        'META-INF/maven/org.apache.commons/commons-lang3/pom.properties'}
WITS = ('wit/deps/activation-runtime/package.wit', 'wit/deps/clock/package.wit', 'wit/world.wit')


def safe(name):
    require(type(name) is str and name not in ('', '.') and PurePosixPath(name).as_posix() == name
        and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
        and '\\' not in name and ':' not in name, 'java-gc-retained-safe-name')


def pins():
    require(file_identity(ROOT/PINS) == PIN_IDENTITY, 'java-gc-retained-pin-source')
    rows = read_json(ROOT/PINS)
    require(len(rows) == 106 and sum(r['bytes'] for r in rows.values()) == 6526395,
        'java-gc-retained-whole-inventory')
    for name, row in rows.items():
        safe(name)
        require(set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int
            and 0 <= row['bytes'] <= 4*1024**2, 'java-gc-retained-member-bound')
    return rows


def extract(raw, output):
    require(len(raw) == ARTIFACT['size_in_bytes'] and digest(raw) == ARTIFACT['digest'],
        'java-gc-retained-whole-archive-identity')
    rows = pins()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == len({e.filename for e in entries}) == len(rows)
            and {e.filename for e in entries} == rows.keys(), 'java-gc-retained-exact-members')
        for entry in entries:
            safe(entry.filename)
            require(not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                and entry.file_size == rows[entry.filename]['bytes']
                and entry.compress_size <= entry.file_size+65536, 'java-gc-retained-regular-size')
        output = fresh(output)
        for entry in entries:
            data = archive.read(entry)  # Original ZIP CRC checked before copying.
            require(digest(data) == rows[entry.filename]['sha256'], 'java-gc-retained-member-identity')
            target = output/entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:stream.write(data)
    return output/'java-gc-roots'


def git_preimages(rows):
    require(len(rows) <= 400, 'java-gc-retained-source-count-bound')
    for name in rows:safe(name)
    raw = subprocess.check_output(['git', 'ls-tree', '-rz', SOURCE, '--', *sorted(rows)], cwd=ROOT, timeout=30)
    require(len(raw) < 1024**2, 'java-gc-retained-tree-bound')
    entries = []
    for item in raw.rstrip(b'\0').split(b'\0'):
        metadata, name = item.split(b'\t');mode, kind, oid = metadata.decode().split();name = name.decode()
        require(mode in ('100644', '100755') and kind == 'blob' and name in rows,
            'java-gc-retained-original-regular-source')
        entries.append((name, oid))
    require(len(entries) == len(rows) and {n for n, _ in entries} == rows.keys(),
        'java-gc-retained-original-source-complete')
    batch = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT,
        input=''.join(oid+'\n' for _, oid in entries).encode(), timeout=30)
    require(len(batch) <= 20*1024**2, 'java-gc-retained-source-bytes-bound')
    position = 0
    for name, oid in entries:
        end = batch.index(b'\n', position);header = batch[position:end].decode().split();size = int(header[2])
        require(header[:2] == [oid, 'blob'] and 0 < size <= 4*1024**2, 'java-gc-retained-blob-bound')
        data = batch[end+1:end+1+size];position = end+size+2
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data, usedforsecurity=False).hexdigest() == oid
            and rows[name] == {'digest': digest(data), 'size': size}, 'java-gc-retained-git-preimage')
    require(position == len(batch), 'java-gc-retained-source-framing')


def source_proof(root):
    failed = read_json(root/'FAILED.json')
    require(failed['source'] == SOURCE and failed['status'] == 'failed'
        and failed['stage'] == 'one-fresh-offline-target-component'
        and not failed['garbageCollectionObserved'] and 'node' not in failed
        and set(failed['materials']) == set(MATERIALS) and len(MATERIALS) == 100,
        'java-gc-retained-original-failed-programme')
    source = read_json(root/'build/source-inputs.json');recipe = read_json(root/'build/recipe-inputs.json')
    sdk = {name[len('vendor/lsf/'):]: row for name, row in source.items() if name.startswith('vendor/lsf/')}
    require(len(sdk) == 206 and len(recipe) == 74 and len(source) == 218,
        'java-gc-retained-compiled-input-counts')
    rows = {}
    def add(name, row):
        require(name not in rows or rows[name] == row, 'java-gc-retained-overlapping-inputs')
        rows[name] = row
    for name, row in (*sdk.items(), *recipe.items()):add(name, row)
    add(fixture.SOURCE, source['src/dev/latent/app/Capsule.java'])
    compiled = dict(rows)
    for name, row in failed['materials'].items():add(name, {'digest': row['sha256'], 'size': row['bytes']})
    git_preimages(rows)
    changed = current_preimages(rows, compiled)
    return {'producerSource': SOURCE, 'producerJobConclusion': 'failure', 'sdkFiles': 206,
        'recipeFiles': 74, 'originalMaterialFiles': 100, 'gitPreimages': len(rows),
        'compiledInputsEqualCurrent': True, 'controllerDifferences': changed,
        'currentComponentCompilationClaimed': False}


def current_preimages(rows, compiled):
    changed = {}
    for name, row in rows.items():
        path = ROOT/name
        require(not any(p.is_symlink() for p in (path, *path.parents))
            and path.resolve(strict=True).is_relative_to(ROOT.resolve()), 'java-gc-retained-source-escape')
        current = file_identity(path, 4*1024**2)
        if current != {'sha256': row['digest'], 'bytes': row['size']}:
            require(name not in compiled and CURRENT_DIFFERENCES.get(name) == current,
                'java-gc-retained-unreviewed-source-change')
            changed[name] = {'producer': row, 'consumer': current}
    require(changed.keys() == CURRENT_DIFFERENCES.keys(), 'java-gc-retained-exact-controller-changes')
    return changed


def recover_library(path=None):
    if path is None:
        request = urllib.request.Request(LIBRARY_URL)
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            require(response.status == 200 and response.geturl() == LIBRARY_URL,
                'java-gc-retained-original-library-origin')
            raw = response.read(LIBRARY_IDENTITY['bytes']+1)
    else:raw = read_file(path, LIBRARY_IDENTITY['bytes'])
    require({'bytes': len(raw), 'sha256': digest(raw)} == LIBRARY_IDENTITY,
        'java-gc-retained-original-library-identity')
    return raw


def recover_package(root, scratch, library):
    build = root/'build';expected = read_json(build/'package-inputs.json')
    source = read_json(build/'package-source.json')
    require(len(expected) == 12 and len(source['layers']) == 11
        and {r['source'] for r in source['layers']} | {'package-source.json'} == expected.keys(),
        'java-gc-retained-original-package-shape')
    missing = {name for name in expected if not (build/name).exists()}
    require(missing == {*WITS, *RESOURCE_MEMBERS}, 'java-gc-retained-exact-missing-static-layers')
    project = fixture.project(scratch/'static-source-project')  # Pure source generation, no compiler/resolver.
    restored = {name: read_file(project/name, 4096) for name in WITS}
    with zipfile.ZipFile(io.BytesIO(library)) as archive:
        for name, member in RESOURCE_MEMBERS.items():
            require(sum(e.filename == member for e in archive.infolist()) == 1,
                'java-gc-retained-resource-member-unique')
            entry = archive.getinfo(member)
            require(entry.file_size == expected[name]['size'] <= 32768
                and not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG),
                'java-gc-retained-library-resource-bound')
            restored[name] = archive.read(entry)
    for name, data in restored.items():
        require(expected[name] == {'digest': digest(data), 'size': len(data)},
            'java-gc-retained-reconstructed-original-input')
        target = build/name;target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:stream.write(data)
    for name, row in expected.items():
        safe(name)
        require(file_identity(build/name) == {'sha256': row['digest'], 'bytes': row['size']},
            'java-gc-retained-all-original-package-inputs')
    return {'reconstructedOriginalInputs': {n: expected[n] for n in sorted(restored)},
        'staticWitSource': 'unchanged maintained fixture.project, no build or resolution',
        'resourceLibrary': {'url': LIBRARY_URL, **LIBRARY_IDENTITY},
        'originalPackageInputs': expected, 'compilerInvocations': 0}


def validate(root, scratch, library):
    bridge = source_proof(root)
    controls = read_json(root/'controls/controls.json');failed = read_json(root/'FAILED.json')
    require(controls == failed['controls'] and controls['status'] == 'reference-and-actual-plugin-model-passed'
        and controls['reference'] == [{'mode': n, 'result': v} for n, v in fixture.EXPECTED.items()]
        and all(r['exitCode'] == 0 for r in controls['referenceCommands'])
        and controls['referenceCollector']['flags'] == list(fixture.REFERENCE_FLAGS)
        and controls['referenceCollector']['gcModeCollectionCountIncreaseMinimum'] == 2
        and controls['componentExecutionPerformed'] is False and not controls['garbageCollectionObserved'],
        'java-gc-retained-original-reference-not-runtime-evidence')
    package = recover_package(root, scratch, library)
    build = build_evidence(root/'build')
    require(build['classpath'] == failed['capture']['selected']
        and controls['selectedJar']['sha256'] == build['classpath']['artifacts'][0]['selectedDigest']
        and controls['originalJar']['sha256'] == fixture.JAR, 'java-gc-retained-same-original-library')
    return {'sourceBridge': bridge, 'packageRecovery': package, 'build': build,
        'originalControls': controls, 'originalRuntimeProgrammePassed': False}


def prepare(output, *, archive_path=None, library_path=None):
    if archive_path is None:
        meta = api('actions/artifacts/'+str(ARTIFACT['id']));job = api('actions/jobs/'+str(JOB))
        require({k: meta[k] for k in ARTIFACT} == ARTIFACT and not meta['expired']
            and meta['name'] == 'java-checkpoint-gc-'+SOURCE and meta['workflow_run']['id'] == RUN
            and meta['workflow_run']['head_sha'] == SOURCE, 'java-gc-retained-artifact-origin')
        require(job['run_id'] == RUN and job['head_sha'] == SOURCE and job['status'] == 'completed'
            and job['conclusion'] == 'failure', 'java-gc-retained-failed-job-origin')
        token = os.environ.get('GH_TOKEN');require(bool(token), 'java-gc-retained-token')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
            headers={'Authorization': 'Bearer '+token})
        try:urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'java-gc-retained-redirect');url = error.headers['Location']
        else:raise ValueError('java-gc-retained-redirect-required')
        require(url.startswith('https://'), 'java-gc-retained-https')
        remote = Ranges(url, ARTIFACT['size_in_bytes']);raw = remote.read(ARTIFACT['size_in_bytes'])
    else:raw = read_file(archive_path, ARTIFACT['size_in_bytes'])
    output = fresh(output)
    root = extract(raw, output/'original')
    proof = validate(root, output, recover_library(library_path))
    write_json(output/'retrieval.json', {'schemaVersion': 'lsf.java.gc.retained-component.v1',
        'artifact': ARTIFACT, 'run': RUN, 'job': JOB, 'producerSource': SOURCE,
        'originalConclusion': 'failure', 'originalRuntimeProgrammeExecuted': False,
        'wholeArchiveSha256And106CrcMembersVerified': True, 'historicalReceiptRewritten': False,
        'localArchiveReuse': archive_path is not None, **proof})
    return root/'build', proof
