"""Exact captured C36 component/package inputs; never compile a replacement guest."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import stat
import time
import urllib.error
import urllib.request
import zipfile

from tools.java_replay_materials import api, NoRedirect, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory
from tools.qualify_c_timed_runtime import build_evidence
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

MANIFEST = 'tools/data/audit-c36-component-02478.json'
MANIFEST_SHA256 = '263186eeedefa06f2893b5f169a2bed3398fc715c65e5c2aa57b62332577cb9e'


def pins():
    raw = read_file(ROOT / MANIFEST, 32768)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, 'audit-c36-fixed-original-input-manifest')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'latent.audit.frozen-c36-component.v1'
            and len(value['files']) == 80 and value['archiveMembers'] == 518
            and value['archiveExpandedBytes'] == 7890292, 'audit-c36-closed-capture')
    for name in value['files']:
        path = PurePosixPath(name)
        require(str(path) == name and not path.is_absolute() and '..' not in path.parts
                and '\\' not in name and ':' not in name, 'audit-c36-fixed-safe-member')
    return value


def validate_origin(run, job, artifact):
    value = pins()
    require(run['id'] == value['run'] and run['head_sha'] == value['source']
        and run['head_branch'] == value['branch'] and run['path'] == value['workflow']
        and run['event'] == 'push' and run['status'] == 'completed' and run['conclusion'] == 'success'
        and job['id'] == value['job'] and job['run_id'] == value['run'] and job['head_sha'] == value['source']
        and job['name'] == value['jobName'] and job['status'] == 'completed' and job['conclusion'] == 'success'
        and all(artifact.get(name) == item for name, item in value['artifact'].items())
        and not artifact['expired'] and artifact['workflow_run']['id'] == value['run']
        and artifact['workflow_run']['head_sha'] == value['source'], 'audit-c36-actual-success-origin')
    return value


def extract(raw, output):
    value = pins()
    require(len(raw) == value['artifact']['size_in_bytes']
            and 'sha256:' + hashlib.sha256(raw).hexdigest() == value['artifact']['digest'],
            'audit-c36-original-whole-archive')
    deadline = time.monotonic() + 60
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        require(len(rows) == len({row.filename for row in rows}) == value['archiveMembers']
                and sum(row.file_size for row in rows) == value['archiveExpandedBytes'],
                'audit-c36-original-archive-count-and-bytes')
        for row in rows:
            path = PurePosixPath(row.filename)
            require(str(path) == row.filename and not path.is_absolute() and '..' not in path.parts
                and '\\' not in row.filename and ':' not in row.filename and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                and row.file_size <= 4 * 1024**2, 'audit-c36-archive-path-type-and-byte-bound')
        selected = {row.filename.removeprefix(value['prefix']) for row in rows
                    if row.filename.startswith(value['prefix'])}
        require(selected == set(value['files']), 'audit-c36-exact-original-build-members')
        for name, identity in value['files'].items():
            require(time.monotonic() < deadline, 'audit-c36-extraction-deadline')
            payload = archive.read(value['prefix'] + name)
            require(len(payload) == identity['bytes']
                    and 'sha256:' + hashlib.sha256(payload).hexdigest() == identity['sha256'],
                    'audit-c36-exact-original-build-bytes')
            destination = output / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open('xb') as target:
                target.write(payload)
            destination.chmod(0o600)


def verify_prepared(prepared):
    value = pins()
    build = prepared / 'build'
    actual = inventory(build, maximum_files=128, maximum_bytes=16 * 1024**2,
                       deadline=time.monotonic() + 60)
    require({row['path']: {'sha256': row['sha256'], 'bytes': row['bytes']} for row in actual['files']}
            == value['files'], 'audit-c36-retained-original-build-drift')
    evidence = build_evidence(build, read_file(build / 'source-inputs.json', 16 * 1024**2))
    require(evidence['component'] == value['files']['component.wasm'], 'audit-c36-captured-component-identity')
    return {'schemaVersion': 'latent.audit.captured-c36-component.v1', 'compiledSource': value['source'],
        'producerRun': value['run'], 'producerJob': value['job'], 'artifact': value['artifact'],
        'component': evidence['component'], 'package': evidence['package'], 'originalBuildFiles': 80,
        'guestSourceRecompiled': False, 'originalNormalReceiptRewritten': False,
        'freshSignedQualificationClaimed': False}


def prepare(output):
    value = pins()
    artifact = api(f'actions/artifacts/{value["artifact"]["id"]}')
    validate_origin(api(f'actions/runs/{value["run"]}'), api(f'actions/jobs/{value["job"]}'), artifact)
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'audit-c36-explicit-actions-token')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'audit-c36-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('audit-c36-redirect-required')
    require(url.startswith('https://'), 'audit-c36-https')
    with urllib.request.urlopen(url, timeout=30) as response:
        require(response.status == 200, 'audit-c36-archive-response')
        raw = response.read(artifact['size_in_bytes'] + 1)
    output = fresh(output)
    extract(raw, fresh(output / 'build'))
    result = verify_prepared(output)
    write_json(output / 'retrieval.json', result)
    return result
