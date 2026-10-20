"""Acquire only the two immutable compiler inputs, never historical native hosts."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None, ''}:sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import typescript_fetch_replay_inputs as original
from tools.go_entropy_replay_inputs import NoRedirect
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import fresh, read_file, read_json, write_json

KINDS = ('engine', 'splicer')


def metadata(kind, document):
    require(kind in KINDS, 'resource-runtime-compiler-closed-input-kind')
    identity, size, sha = original.ARTIFACTS[kind]
    original.artifact_metadata(document, identity, size, sha)
    require(document['workflow_run']['repository_id'] == document['workflow_run']['head_repository_id'] == 1337591365,
            'resource-runtime-compiler-input-repository')
    return {'artifact': identity, 'bytes': size, 'digest': 'sha256:'+sha,
            'run': original.RUN, 'source': original.SOURCE, 'workflowHead': original.RUN_HEAD}


def acquire(output: Path):
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and 0 < len(token) <= 4096, 'resource-runtime-compiler-read-credential')
    headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json'}
    result = {'schemaVersion': 'latent.typescript.resource-runtime-compiler.v1',
              'credentialsRetained': False, 'nativeHostsDownloaded': 0, 'inputs': {}}
    for kind in KINDS:
        identity, size, sha = original.ARTIFACTS[kind]
        endpoint = f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{identity}'
        with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
            raw_metadata = response.read(65537)
        require(len(raw_metadata) <= 65536, 'resource-runtime-compiler-metadata-bound')
        binding = metadata(kind, json.loads(raw_metadata))
        try:
            urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint+'/zip', headers=headers), timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'resource-runtime-compiler-download-redirect')
            location = error.headers['Location']
        else:
            raise ValueError('resource-runtime-compiler-download-redirect-required')
        url = urllib.parse.urlsplit(location)
        require(url.scheme == 'https' and url.username is None and url.hostname is not None
                and (url.hostname.endswith('.blob.core.windows.net') or url.hostname.endswith('.githubusercontent.com')),
                'resource-runtime-compiler-download-origin')
        with urllib.request.urlopen(location, timeout=90) as response:raw = response.read(size+1)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha,
                'resource-runtime-compiler-whole-archive')
        (output/('archive-'+kind+'.zip')).write_bytes(raw)
        directory = output/kind;directory.mkdir(mode=0o700)
        members = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for entry in original.members(kind, archive.infolist()):
                body = archive.read(entry)
                path = directory/entry.filename;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(body)
                members.append({'path': entry.filename, **file_identity(path, 192*1024**2)})
        result['inputs'][kind] = {**binding, 'wholeArchiveDigestVerified': True, 'members': members}
    write_json(output/'acquisition.json', result)
    verify(output)
    return result


def verify(directory: Path):
    record = read_json(directory/'acquisition.json')
    require(record.get('schemaVersion') == 'latent.typescript.resource-runtime-compiler.v1'
            and record.get('credentialsRetained') is False and record.get('nativeHostsDownloaded') == 0
            and set(record.get('inputs', {})) == set(KINDS), 'resource-runtime-compiler-receipt')
    for kind in KINDS:
        selected = record['inputs'][kind];identity, size, sha = original.ARTIFACTS[kind]
        require(all(selected.get(key) == value for key, value in {'artifact':identity, 'bytes':size,
                'digest':'sha256:'+sha, 'run':original.RUN, 'source':original.SOURCE,
                'workflowHead':original.RUN_HEAD, 'wholeArchiveDigestVerified':True}.items()),
                'resource-runtime-compiler-original-binding')
        rows = selected['members']
        require(type(rows) is list and 2 <= len(rows) <= 33 and len({r['path'] for r in rows}) == len(rows),
                'resource-runtime-compiler-member-inventory')
        raw = read_file(directory/('archive-'+kind+'.zip'), size+1)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha,
                'resource-runtime-compiler-original-archive-preimage')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            expected = [{'path':entry.filename, 'sha256':'sha256:'+hashlib.sha256(archive.read(entry)).hexdigest(),
                         'bytes':entry.file_size} for entry in original.members(kind, archive.infolist())]
        require(rows == expected, 'resource-runtime-compiler-receipt-cannot-rebind-archive-members')
        for row in rows:
            path = Path(row['path'])
            require(not path.is_absolute() and '..' not in path.parts and ':' not in row['path']
                    and '\\' not in row['path'] and set(row) == {'path', 'sha256', 'bytes'}
                    and file_identity(directory/kind/path, 192*1024**2) == {key:row[key] for key in ('sha256','bytes')},
                    'resource-runtime-compiler-member-identity')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();print(json.dumps(acquire(args.output)))
