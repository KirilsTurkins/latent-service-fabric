"""Acquire one immutable, normally packaged TypeScript resource-limit component."""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_replay_materials import api, NoRedirect, REPOSITORY
from tools.phase2_operator_process import require
from tools.qualify_typescript_fetch_runtime import build_evidence
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import fresh, read_file, read_json, write_json

SOURCE = '63224663df622426a8a657355fb6ccc6294215ee'
RUN = 39561770610
JOB = 119094482153
ARTIFACT = 12328935407
ARCHIVE_BYTES = 8806047
ARCHIVE_SHA = '544655acf815a0fe85a0da4174fb4cca948fcfa119c08088d1ab4b229f816313'
COMPONENT = {'bytes': 12410038,
    'sha256': 'sha256:27c0a75bf794e49ba6062b9ec09129cfc51ac78b6274c43959cc7e8ecb46e693'}
PREFIX = 'runtime-limits/build/'


def provenance(run, job, artifact):
    require(run['id'] == RUN and run['head_sha'] == SOURCE and run['event'] == 'push'
        and run['head_branch'] == 'feat/typescript-tracking-limits-20261021'
        and run['path'] == '.github/workflows/typescript-tracking-limits.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'success', 'tracking-component-run')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['name'] == 'Signed independent task queue native timer and memory boundaries'
        and job['status'] == 'completed' and job['conclusion'] == 'success'
        and job['steps'] and all(row['conclusion'] == 'success' for row in job['steps']),
        'tracking-component-owning-job')
    require(artifact['id'] == ARTIFACT and artifact['expired'] is False
        and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == SOURCE
        and artifact['name'] == 'typescript-tracking-limits-'+SOURCE
        and artifact['size_in_bytes'] == ARCHIVE_BYTES and artifact['digest'] == 'sha256:'+ARCHIVE_SHA,
        'tracking-component-artifact')


def unpack(raw, destination):
    require(len(raw) == ARCHIVE_BYTES and hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA,
        'tracking-component-whole-archive')
    selected = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 327 and len({r.filename.casefold() for r in entries}) == len(entries)
            and sum(r.file_size for r in entries) == 27493657, 'tracking-component-members')
        for entry in entries:
            path = PurePosixPath(entry.filename)
            require(not path.is_absolute() and str(path) == entry.filename
                and all(part not in ('', '.', '..') for part in path.parts)
                and ':' not in entry.filename and '\\' not in entry.filename and not entry.is_dir()
                and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                and 0 <= entry.file_size <= 16*1024**2, 'tracking-component-member')
        require(archive.testzip() is None, 'tracking-component-all-crc')
        for entry in entries:
            if not entry.filename.startswith(PREFIX):
                continue
            name = entry.filename[len(PREFIX):]
            value = archive.read(entry)
            if destination is not None:
                target = destination/name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output:
                    output.write(value)
            selected[name] = {'bytes': len(value), 'sha256': 'sha256:'+hashlib.sha256(value).hexdigest()}
    if destination is not None:
        validate_build(destination)
    return selected


def validate_build(directory):
    require(build_evidence(directory)['component'] == COMPONENT, 'tracking-component-final-bytes')
    complete = read_json(directory/'BUILD-COMPLETE.json')
    require(len(complete['commands']) == 26 and all(row['exitCode'] == 0 for row in complete['commands']),
        'tracking-component-original-build')


def package_sources(directory, members, *, restore=False):
    """Restore omitted WIT sources only from byte-identical archived layers."""
    declaration = read_json(directory/'package-source.json')
    inputs = read_json(directory/'package-inputs.json')
    restored = {}
    require(type(declaration.get('layers')) is list and len(declaration['layers']) <= 32,
        'tracking-component-package-source-count')
    for layer in declaration['layers']:
        name = layer['source']
        require(name == layer['path'] and type(name) is str and ':' not in name
            and '\\' not in name and not PurePosixPath(name).is_absolute()
            and not any(p in ('','..','.') for p in PurePosixPath(name).parts),
            'tracking-component-package-source-path')
        if name in members:
            require(file_identity(directory/name,16*1024**2) == members[name],
                'tracking-component-original-package-source')
            continue
        archive_name = 'package/layers/'+name
        require(name.startswith('wit/') and archive_name in members
            and members[archive_name]['bytes'] <= 1024**2,
            'tracking-component-only-authenticated-wit-restoration')
        identity = members[archive_name]
        require(inputs[name] == {'digest':identity['sha256'],'size':identity['bytes']}
            and file_identity(directory/archive_name,1024**2) == identity,
            'tracking-component-package-layer-source-identity')
        target = directory/name
        if restore:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as output:output.write(read_file(directory/archive_name,1024**2))
        require(file_identity(target,1024**2) == identity,'tracking-component-restored-source-preimage')
        require(name not in restored,'tracking-component-duplicate-source')
        restored[name] = identity
    require(len(restored) == 5 and sum(row['bytes'] for row in restored.values()) <= 1024**2,
        'tracking-component-exact-original-five-wit-sources')
    return restored


def record(members, restored):
    return {'profile': 'typescript-tracking-component-reuse-v1', 'source': SOURCE,
        'run': RUN, 'job': JOB, 'artifact': ARTIFACT, 'archiveBytes': ARCHIVE_BYTES,
        'archiveDigest': 'sha256:'+ARCHIVE_SHA, 'crcMembers': 327, 'members': members,
        'component': COMPONENT, 'restoredOriginalPackageSources':restored,
        'compilerOrEngineRebuilt': False, 'credentialsRetained': False,
        'newHostAccountingQualified': False}


def verify_prepared(directory):
    expected = unpack(read_file(directory/'original-artifact.zip', ARCHIVE_BYTES), None)
    for name, identity in expected.items():
        require(file_identity(directory/'build'/name, 16*1024**2) == identity,
            'tracking-component-retained-member')
    validate_build(directory/'build')
    value = record(expected,package_sources(directory/'build',expected))
    require(read_json(directory/'acquisition.json') == value, 'tracking-component-retained-receipt')
    return value


def prepare(output):
    output = fresh(output)
    run, job, artifact = (api(path) for path in ('actions/runs/'+str(RUN),
        'actions/jobs/'+str(JOB), 'actions/artifacts/'+str(ARTIFACT)))
    provenance(run, job, artifact)
    token = os.environ.get('GH_TOKEN')
    require(isinstance(token, str) and 0 < len(token) <= 4096, 'tracking-component-read-token')
    request = urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+
        '/actions/artifacts/'+str(ARTIFACT)+'/zip', headers={'Authorization': 'Bearer '+token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'tracking-component-redirect')
        location = error.headers['Location']
    else:
        raise ValueError('tracking-component-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
        and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
        'tracking-component-origin')
    with urllib.request.urlopen(location, timeout=90) as response:
        raw = response.read(ARCHIVE_BYTES+1)
    members = unpack(raw, output/'build')
    with (output/'original-artifact.zip').open('xb') as target:
        target.write(raw)
    restored = package_sources(output/'build',members,restore=True)
    value = record(members,restored)
    write_json(output/'acquisition.json', value)
    require(verify_prepared(output) == value, 'tracking-component-final-recheck')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
