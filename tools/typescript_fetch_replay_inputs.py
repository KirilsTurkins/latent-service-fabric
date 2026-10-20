"""Fixed authenticated original import compiler and explicitly historical host."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
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

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

SOURCE = '0754391a20027a539f1d5b7c0426719a4bd6c3c1'
RUN_HEAD = 'aea63cc6b3f7a72f3ec0e8ea92bf2d94e565d479'
MERGE_PARENTS = ('cb3eef93d76f7657e76386280ac48925409aa0a8', RUN_HEAD)
RUN = 39276911555
ARTIFACTS = {
    'engine': (12199029178, 3303664, 'c5039a0466ef3a4627abda643049ec15aa21567fe06d82333630d6c3fbab60cd'),
    'splicer': (12197927520, 1548899, '176d5ed3506f8b55efd45e995b00320374ec181466f2424edd685b7794978775'),
    'native': (12203281146, 65368141, 'b4826eb3352fab57a5d4c553d575c7c077522aa3857b4ff970fecf386c048906'),
}
QUALIFICATION = 'sha256:265e623fd6fc1ec9a68dd56e4d468f9c1a85826a7cc12cab5a214a494b7c9823'
PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')


def artifact_metadata(metadata, identity, size, sha):
    require(metadata['id'] == identity and metadata['size_in_bytes'] == size
            and metadata['digest'] == 'sha256:'+sha and not metadata['expired']
            and metadata['workflow_run']['id'] == RUN
            and metadata['workflow_run']['head_sha'] == RUN_HEAD, 'fetch-replay-owning-artifact')


def members(kind, entries):
    names = [entry.filename for entry in entries]
    require(len(names) == len(set(names)) <= 64, 'fetch-replay-unique-bounded-index')
    if kind == 'engine':
        selected = {'engine.wasm', 'engine-input.json'}
    elif kind == 'native':
        selected = {'qualification.json', 'source-inputs.json', 'source-inputs-after.json',
                    *('native-binaries/'+name.replace('/', '-') for name in PRODUCTS)}
    else:
        selected = {'splicer-input.json', *(name for name in names if name.startswith('splicer/'))}
    require(selected <= set(names) and 2 <= len(selected) <= 33, 'fetch-replay-exact-members')
    total, result = 0, []
    for entry in entries:
        if entry.filename not in selected:
            continue
        path = PurePosixPath(entry.filename)
        require(not path.is_absolute() and str(path) == entry.filename
                and all(part not in {'', '.', '..'} for part in entry.filename.split('/'))
                and ':' not in entry.filename and '\\' not in entry.filename
                and not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16)
                and not entry.flag_bits & 1 and 0 < entry.file_size <= 192*1024**2,
                'fetch-replay-member-shape')
        total += entry.file_size
        require(total <= 320*1024**2, 'fetch-replay-expanded-bound')
        result.append(entry)
    return result


def acquire(output):
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and 0 < len(token) <= 4096, 'fetch-replay-read-credential')
    receipts = {}
    headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json'}
    commit_url = f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/commits/{SOURCE}'
    with urllib.request.urlopen(urllib.request.Request(commit_url, headers=headers), timeout=30) as response:
        commit_raw = response.read(65537)
    require(len(commit_raw) <= 65536, 'fetch-replay-commit-bound')
    commit = json.loads(commit_raw)
    require(commit['sha'] == SOURCE and tuple(row['sha'] for row in commit['parents']) == MERGE_PARENTS,
            'fetch-replay-exact-tested-merge')
    for kind, (identity, size, sha) in ARTIFACTS.items():
        endpoint = f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{identity}'
        headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json'}
        with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
            metadata_raw = response.read(65537)
        require(len(metadata_raw) <= 65536, 'fetch-replay-metadata-bound')
        metadata = json.loads(metadata_raw)
        artifact_metadata(metadata, identity, size, sha)
        from tools.go_entropy_replay_inputs import NoRedirect
        try:
            urllib.request.build_opener(NoRedirect).open(
                urllib.request.Request(endpoint+'/zip', headers=headers), timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'fetch-replay-download-redirect')
            location = error.headers['Location']
        else:
            raise ValueError('fetch-replay-download-redirect-required')
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
                and (parsed.hostname.endswith('.blob.core.windows.net')
                     or parsed.hostname.endswith('.githubusercontent.com')), 'fetch-replay-download-origin')
        with urllib.request.urlopen(location, timeout=90) as response:
            raw = response.read(size+1)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, 'fetch-replay-whole-archive')
        destination = output/kind
        destination.mkdir(mode=0o700)
        inventory = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for entry in members(kind, archive.infolist()):
                value = archive.read(entry)
                require(len(value) == entry.file_size, 'fetch-replay-exact-member-size')
                path = destination/entry.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
                path.chmod(0o700 if entry.filename.startswith('native-binaries/') else 0o600)
                inventory.append({'path': entry.filename, 'digest': digest(value), 'bytes': len(value)})
        receipts[kind] = {'artifactId': identity, 'archiveDigest': 'sha256:'+sha,
                          'archiveBytes': size, 'members': inventory}
    selected, identity = native_inputs(output/'native')
    record = {'originalSource': SOURCE, 'workflowHead': RUN_HEAD, 'testedMergeParents': list(MERGE_PARENTS),
              'originalRun': RUN, 'artifacts': receipts,
              'historicalNative': identity, 'credentialsRetained': False,
              'normalReceiptRewritten': False, 'currentHostQualification': False}
    write_json(output/'acquisition.json', record)
    return record


def native_inputs(directory):
    require(digest(read_file(directory/'qualification.json')) == QUALIFICATION,
            'fetch-replay-original-normal-preimage')
    receipt = read_json(directory/'qualification.json')
    source = read_file(directory/'source-inputs.json')
    require(receipt['status'] == 'passed' and source == read_file(directory/'source-inputs-after.json')
            and digest(source) == receipt['sourceIdentityDigest'], 'fetch-replay-original-source-proof')
    binaries = {name.split('/')[-1]: directory/'native-binaries'/name.replace('/', '-') for name in PRODUCTS}
    original = {name: file_identity(binaries[name.split('/')[-1]], 192*1024**2) for name in PRODUCTS}
    require(original == receipt['binaries'], 'fetch-replay-original-five-binaries')
    return binaries, {'source': SOURCE, 'workflowHead': RUN_HEAD, 'runId': RUN, 'artifact': ARTIFACTS['native'][0],
        'qualification': file_identity(directory/'qualification.json'), 'sourceInputs': file_identity(directory/'source-inputs.json'),
        'binaries': original, 'historical': True, 'currentNormalReceiptFabricated': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output)))
