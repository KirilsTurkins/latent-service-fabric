"""Fixed e97 host acquisition for the explicit .NET task diagnostic lane only."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import digest as identity_digest
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ORIGINAL = '03a3f74598f2abfd0224169ae2871818f6c8419d'
ORIGINAL_TESTED = '0e46e59358bb4bae16169690041daacbf113555a'
HOST_SOURCE = 'e97d44ddc744c9bd738d9b3b7a7d8b7234133e36'
HOST_BINARY = {'sha256': 'sha256:1ade67dfc9c461068ac7680a397f310eaf31e0e97b671a4dafd16ad710e1d050', 'bytes': 184227152}
HOST_IDENTITY = {'sha256': 'sha256:db1b074b88c12884ac449bb873357759ab3807bcce79135c1ec45e705e84e92a',
    'files': 3168, 'bytes': 23911170, 'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
HELPERS = {
    'latent': {'sha256': 'sha256:3b799d5afec30ada02c382797bfae9e1445a675ba0b838a0681b9cf826aa0ddc', 'bytes': 68801608},
    'package': {'sha256': 'sha256:f826023c756212d9ec907faf23cf5f9802eac127310e74cd13a1e39a0d4cffa5', 'bytes': 17726192},
    'capsule_contracts': {'sha256': 'sha256:a0ea59c420231a5f4a2e614762e930a883a42ef663afbfc2b172d509c2606b88', 'bytes': 7224720},
    'capsule_authoring': {'sha256': 'sha256:d560fb7003732efca6477e29bf51aa0510103b903a68a9c71b0a4c49caf1ee43', 'bytes': 23847032},
}
SOURCE_SHA = 'sha256:8c4a67079973d4dde66e89f273b18eec8d619f07a4c08aceb1ae4a2cf224ebcf'
QUALIFICATION_SHA = 'sha256:a844856c87fae01a5cd21ab74cbc5c2a87746d60938763ee8063d0582df0a7b2'
SPECS = {
    'rust': (12207589449, 66891464,
        'sha256:546b5fc4f2dc2d9646150ac2964fc397fdd1c20a93ec68000bec39fbfb945cb6',
        39293312298, 118199288801, '6ffab636e647f93bfa12fda12a0383316f8dce8d'),
    'helpers': (12206326792, 1436916086,
        'sha256:e0b7127a34c4e8578d71fc0b8ed92a157827f8782ef643c3525f967a1757f382',
        39287260436, 118177684118, ORIGINAL),
    'host': (12220651992, 40105690,
        'sha256:a138d432358bda73357e0d887310c3cb97e1c8d1065f664c526870a2c3c52e8a',
        39320463437, 118292873857, HOST_SOURCE),
}
PREFIX = 'dotnet-capsule-dependencies/'
ALLOWED = {
    'helpers': {PREFIX + name: 1024**2 for name in
        ('qualification.json', 'source-inputs.json', 'source-inputs-after.json')}
        | {'native-binaries/' + ('latent' if name == 'latent' else 'examples-' + name): 256*1024**2
           for name in HELPERS},
    'host': {'go-entropy-retained/current-host.json': 1024**2,
             'go-entropy-retained/current-latentd': 256*1024**2},
}


def api(path):
    raw = subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], timeout=30)
    require(len(raw) <= 4*1024**2, 'rust-replay-api-bound')
    return json.loads(raw)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Ranges(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.position, self.transferred, self.requests = url, size, 0, 0, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        require(whence in (0, 1, 2), 'rust-replay-seek-kind')
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(0 <= self.position <= self.size, 'rust-replay-seek-bound')
        return self.position

    def read(self, count=-1):
        if count == -1:
            count = self.size-self.position
        require(0 <= count <= 8*1024**2, 'rust-replay-range-bound')
        count = min(count, self.size-self.position)
        if not count:
            return b''
        self.requests += 1
        self.transferred += count
        require(self.requests <= 4096 and self.transferred <= 2*self.size, 'rust-replay-transfer-bound')
        end = self.position + count - 1
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(response.status == 206 and response.headers['Content-Range'] ==
                    f'bytes {self.position}-{end}/{self.size}', 'rust-replay-range-response')
            raw = response.read(count+1)
        require(len(raw) == count, 'rust-replay-range-length')
        self.position += count
        return raw


class Artifact:
    def __init__(self, kind):
        self.kind = kind
        identifier, size, checksum, run, job, source = SPECS[kind]
        self.metadata = api(f'actions/artifacts/{identifier}')
        data = self.metadata
        require(data['id'] == identifier and data['size_in_bytes'] == size and data['digest'] == checksum
                and not data['expired'] and data['workflow_run']['id'] == run
                and data['workflow_run']['head_sha'] == source, 'rust-replay-artifact-origin')
        observed = api(f'actions/jobs/{job}')
        require(observed['head_sha'] == source and observed['run_id'] == run
                and observed['status'] == 'completed'
                and observed['conclusion'] == ('success' if kind in {'host', 'rust'} else 'failure'),
                'rust-replay-job-origin')
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'rust-replay-explicit-actions-token')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{identifier}/zip',
            headers={'Authorization': 'Bearer ' + token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'rust-replay-redirect')
            url = error.headers['Location']
        else:
            raise ValueError('rust-replay-redirect-required')
        require(url.startswith('https://'), 'rust-replay-https')
        self.remote = Ranges(url, size)
        self.archive = zipfile.ZipFile(self.remote)
        names = self.archive.namelist()
        require(len(names) <= 20000 and len(names) == len(set(names)), 'rust-replay-member-bound')
        self.selected = {}

    def extract(self, name, destination):
        maximum = ALLOWED[self.kind].get(name)
        path = PurePosixPath(name)
        require(maximum is not None and str(path) == name and not path.is_absolute()
                and '..' not in path.parts and '\\' not in name, 'rust-replay-fixed-member-only')
        row = self.archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'rust-replay-member-type')
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.archive.open(row) as source, destination.open('xb') as target:
            count = 0
            while raw := source.read(1024**2):
                count += len(raw)
                require(count <= maximum, 'rust-replay-expanded-bound')
                target.write(raw)
        require(count == row.file_size, 'rust-replay-expanded-length')
        destination.chmod(0o600)
        self.selected[name] = file_identity(destination, maximum)

    def summary(self):
        return {'artifact': self.metadata['id'], 'archiveDigest': self.metadata['digest'],
                'selected': self.selected, 'rangeBytes': self.remote.transferred,
                'rangeRequests': self.remote.requests, 'wholeArchiveRetained': False}


def git_source_identity(revision):
    """The exact frozen explicit native inputs, never the current checkout."""
    raw = subprocess.check_output(['git', 'ls-tree', '-rz', revision, '--', 'Cargo.toml', 'Cargo.lock',
        'rust-toolchain.toml', '.cargo/config.toml', 'apps', 'crates', 'sdk/rust',
        'tools/optimization-workloads'], cwd=ROOT, timeout=30)
    require(len(raw) < 4*1024**2, 'rust-replay-native-tree-bound')
    entries = []
    for item in raw.rstrip(b'\0').split(b'\0'):
        metadata, name = item.split(b'\t')
        mode, kind, oid = metadata.decode('ascii').split()
        require(mode in ('100644', '100755') and kind == 'blob', 'rust-replay-native-regular-source')
        entries.append((name.decode('utf-8'), oid))
    require(0 < len(entries) <= 16384, 'rust-replay-native-file-bound')
    data = subprocess.run(['git', 'cat-file', '--batch'], input=''.join(oid+'\n' for _,oid in entries).encode(),
        stdout=subprocess.PIPE, check=True, cwd=ROOT, timeout=60).stdout
    require(len(data) <= 128*1024**2, 'rust-replay-native-byte-bound')
    rows, position = [], 0
    for name, oid in entries:
        line, start = data.index(b'\n', position), position
        header = data[start:line].decode('ascii').split()
        require(len(header) == 3 and header[:2] == [oid, 'blob'], 'rust-replay-Git-blob-header')
        size = int(header[2]); position = line+1
        require(0 <= size <= 128*1024**2 and position+size < len(data), 'rust-replay-Git-blob-bound')
        payload = data[position:position+size]
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+payload).hexdigest() == oid,
                'rust-replay-Git-blob-identity')
        rows.append({'path': name, 'sha256': 'sha256:'+hashlib.sha256(payload).hexdigest(), 'bytes': size})
        position += size+1
    require(position == len(data), 'rust-replay-Git-batch-trailing')
    rows.sort(key=lambda row: row['path'])
    return {'sha256': identity_digest(rows), 'files': len(rows), 'bytes': sum(row['bytes'] for row in rows),
        'scope': HOST_IDENTITY['scope'], 'hermetic': False, 'implicitCompilerInputs': 'not-attested'}


def validate_host(root):
    info = read_json(root/'current-host.json')
    require(info['compiledSource'] == HOST_SOURCE and info['sourceIdentity'] == HOST_IDENTITY
            and info['binary'] == HOST_BINARY and info['features'] == [] and info['ordinaryDefaults'] is True
            and info['profile'] == {'opt_level': '0', 'debuginfo': 0, 'debug_assertions': True,
                                   'overflow_checks': True, 'test': False}
            and file_identity(root/'latentd', 256*1024**2) == HOST_BINARY,
            'rust-replay-host-profile-or-product')
    require(git_source_identity(HOST_SOURCE) == HOST_IDENTITY, 'rust-replay-frozen-host-source')


def retrieve_host(output):
    """Root Rust lane can use this exact e97 acquisition without helper products."""
    output = fresh(output)
    artifact = Artifact('host')
    artifact.extract('go-entropy-retained/current-host.json', output/'current-host.json')
    artifact.extract('go-entropy-retained/current-latentd', output/'latentd')
    validate_host(output)
    (output/'latentd').chmod(0o700)
    result = {'compiledSource': HOST_SOURCE, 'compiledTree': api('git/commits/'+HOST_SOURCE)['tree']['sha'],
        'sourceIdentity': HOST_IDENTITY, 'binary': HOST_BINARY, 'features': [], 'ordinaryDefaults': True,
        'origin': artifact.summary(), 'currentDevelopmentCompilationClaimed': False}
    write_json(output/'host-retrieval.json', result)
    return result

