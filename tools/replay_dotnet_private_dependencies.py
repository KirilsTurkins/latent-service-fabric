"""Explicit fixed-source private NuGet diagnostic; no native programme rebuild."""
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
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_private_dependencies import PRODUCTS, COMPANIONS, prepared_inputs
from tools.qualify_rust_capsules import inputs
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_json, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ORIGINAL_HEAD = '03a3f74598f2abfd0224169ae2871818f6c8419d'
ORIGINAL_TESTED = '0e46e59358bb4bae16169690041daacbf113555a'
ORIGINAL_RUN = 39287260436
ORIGINAL_JOB = 118177684118
ARTIFACTS = {'products': (12206326792, 1436916086,
    'sha256:e0b7127a34c4e8578d71fc0b8ed92a157827f8782ef643c3525f967a1757f382')}
MAX_DOCUMENT = 4 * 1024**2
BUILD_FILES = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
               'recipe-inputs.json', 'package-inputs.json', 'package-source.json', 'deployment.json')

def safe_name(name):
    require(isinstance(name, str) and bool(name), 'replay-artifact-member-path')
    path = PurePosixPath(name)
    require(bool(path.parts) and '\\' not in name
            and not path.is_absolute() and '..' not in path.parts
            and str(path) == name and ':' not in name, 'replay-artifact-member-path')
    return path


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
        require(whence in (0, 1, 2), 'replay-zip-seek-kind')
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(0 <= self.position <= self.size, 'replay-zip-seek-bound')
        return self.position

    def read(self, count=-1):
        if count == -1:
            count = self.size - self.position
        require(0 <= count <= 8 * 1024**2, 'replay-range-byte-bound')
        count = min(count, self.size - self.position)
        if not count:
            return b''
        self.requests += 1
        self.transferred += count
        require(self.requests <= 4096 and self.transferred <= 2 * self.size, 'replay-total-range-bound')
        end = self.position + count - 1
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(response.status == 206 and response.headers['Content-Range']
                    == f'bytes {self.position}-{end}/{self.size}', 'replay-range-response')
            raw = response.read(count + 1)
        require(len(raw) == count, 'replay-range-length')
        self.position += count
        return raw


def api(path):
    raw = subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], timeout=30)
    require(len(raw) <= MAX_DOCUMENT, 'replay-api-byte-bound')
    return json.loads(raw)


class Artifact:
    def __init__(self, kind):
        artifact, size, expected_digest = ARTIFACTS[kind]
        self.metadata = api(f'actions/artifacts/{artifact}')
        run = self.metadata['workflow_run']
        require(self.metadata['id'] == artifact and self.metadata['size_in_bytes'] == size
                and self.metadata['digest'] == expected_digest and not self.metadata['expired'] and run['id'] == ORIGINAL_RUN
                and run['head_sha'] == ORIGINAL_HEAD, 'replay-artifact-source-binding')
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'replay-explicit-actions-read-token-required')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact}/zip',
            headers={'Authorization': 'Bearer ' + token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'replay-artifact-redirect')
            url = error.headers['Location']
        else:
            raise ValueError('replay-artifact-redirect-required')
        require(url.startswith('https://'), 'replay-artifact-https-required')
        self.remote = Ranges(url, size)
        self.archive = zipfile.ZipFile(self.remote)
        names = self.archive.namelist()
        require(len(names) <= 20000 and len(names) == len(set(names)), 'replay-artifact-entry-bound')
        self.selected = {}

    def extract(self, name, output, maximum=MAX_DOCUMENT):
        safe_name(name)
        row = self.archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in {0, stat.S_IFREG}, 'replay-member-type-or-byte-bound')
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        hasher, size = hashlib.sha256(), 0
        with self.archive.open(row) as source, output.open('xb') as target:
            while raw := source.read(1024 * 1024):
                size += len(raw)
                require(size <= maximum, 'replay-member-expanded-bound')
                hasher.update(raw)
                target.write(raw)
        require(size == row.file_size, 'replay-member-size-mismatch')
        output.chmod(0o600)
        self.selected[name] = {'sha256': 'sha256:' + hasher.hexdigest(), 'bytes': size}
        return output

    def summary(self):
        return {'id': self.metadata['id'], 'digest': self.metadata['digest'],
                'selected': self.selected, 'networkBytes': self.remote.transferred}


def retrieve_build(artifact, template, prepared, expected):
    require(template in COMPANIONS, 'private-replay-fixed-companion-only')
    output = prepared / 'builds' / template
    output.mkdir(mode=0o700, parents=True)
    prefix = 'dotnet-capsule-dependencies/builds/' + template + '/'
    for name in BUILD_FILES:
        artifact.extract(prefix + name, output / name)
    require(read_json(output / 'BUILD-COMPLETE.json') == expected, 'private-replay-original-build-marker')
    layers = read_json(output / 'package-source.json')['layers']
    require(1 <= len(layers) <= 32, 'private-replay-package-layer-count')
    allowed = {'component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json', 'compatibility-report.json',
               'wit/world.wit', 'wit/deps/clock/package.wit', 'wit/deps/http-v2/package.wit'}
    observed = {'package-source.json': (output / 'package-source.json').read_bytes()}
    for layer in layers:
        name = layer['source']
        require(name in allowed and layer['path'] == name and name not in observed,
                'private-replay-fixed-package-layer')
        artifact.extract(prefix + name, output / name, 64*1024**2 if name == 'component.wasm' else MAX_DOCUMENT)
        observed[name] = (output / name).read_bytes()
    require(inventory(observed) == (output / 'package-inputs.json').read_bytes()
            and digest(observed['component.wasm']) == expected['componentDigest']
            and digest((output / 'build-observation.json').read_bytes()) == expected['observationDigest']
            and digest((output / 'source-inputs.json').read_bytes()) == expected['sourceDigest'],
            'private-replay-original-package-input-identity')


def prepare(output):
    require(sys.platform == 'linux', 'private-replay-linux-required')
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'private-replay-output-outside-source')
    job = api(f'actions/jobs/{ORIGINAL_JOB}')
    require(job['run_id'] == ORIGINAL_RUN and job['head_sha'] == ORIGINAL_HEAD
            and job['conclusion'] == 'failure' and any(row['number'] == 29 and row['conclusion'] == 'success'
                for row in job['steps']), 'private-replay-original-completed-baseline')
    commit = api('git/commits/' + ORIGINAL_TESTED)
    require(commit['sha'] == ORIGINAL_TESTED and ORIGINAL_HEAD in [p['sha'] for p in commit['parents']],
            'private-replay-official-tested-parent')
    artifact = Artifact('products')
    prefix = 'dotnet-capsule-dependencies/'
    for name in ('qualification.json', 'source-inputs.json', 'source-inputs-after.json'):
        artifact.extract(prefix + name, output / name)
    receipt = read_json(output / 'qualification.json')
    require(receipt['schemaVersion'] == 'latent.dotnet-capsule.qualification.v1'
            and receipt['status'] == receipt['node']['status'] == 'passed'
            and set(receipt['binaries']) == set(PRODUCTS), 'private-replay-original-qualification')
    source = (output / 'source-inputs.json').read_bytes()
    require(read_json(output / 'source-inputs.json') == inputs('dotnet')
            and source == (output / 'source-inputs-after.json').read_bytes()
            and digest(source) == receipt['sourceIdentityDigest'], 'private-replay-current-source-match')
    for name in PRODUCTS:
        relative = 'native-binaries/' + name.replace('/', '-')
        target = output / relative
        artifact.extract(prefix + relative, target, 512 * 1024**2)
        require(file_identity(target, 512*1024**2) == receipt['binaries'][name],
                'private-replay-original-native-identity')
        target.chmod(0o700)
    for template in COMPANIONS:
        retrieve_build(artifact, template, output, receipt['builds'][template])
    prepared_inputs(output)
    record = {'schemaVersion': 'latent.dotnet.private-replay-inputs.v1', 'status': 'passed',
        'compiledSource': {'head': ORIGINAL_HEAD, 'testedMerge': ORIGINAL_TESTED, 'tree': commit['tree']['sha'],
                           'run': ORIGINAL_RUN, 'job': ORIGINAL_JOB},
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'strictPreparedSourceMatch': True, 'sourceIdentityDigest': receipt['sourceIdentityDigest'],
        'nativeProducts': receipt['binaries'], 'artifact': artifact.summary(),
        'normalQualificationRecreated': False, 'nativeProductsCompiled': False,
        'fullTicketQualification': False}
    write_json(output / 'retrieval.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': prepare(args.output.resolve())['status']}))
