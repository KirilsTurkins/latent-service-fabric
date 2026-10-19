"""Fixed artifact acquisition for one unchanged-component Go entropy replay."""
from __future__ import annotations

import io
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_operator_process import require
from tools.rust_capsule_project import fresh, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ARTIFACT = 12212440772
MAX_REQUESTS = 512
PROGRESS = {'stage': 'metadata', 'rangeRequests': 0, 'networkBytes': 0, 'completedMembers': 0}

TESTED = '42a2dadf1cd77b3dda65ec4720a4ce973c5e4813'
COMPANIONS = ('word-count', 'shipping', 'http-status', 'recovery')
PUBLIC = frozenset({'BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
    'recipe-inputs.json', 'package-inputs.json', 'package-source.json', 'capsule.json',
    'contracts.json', 'wit-lock.json', 'compatibility-report.json', 'deployment.json', 'component.wasm'})
NATIVE = frozenset({'latent', 'latentd', 'examples-package', 'examples-capsule_contracts', 'examples-capsule_authoring'})


def selected(name: str):
    if '\\' in name or name.startswith('/') or any(p in {'', '.', '..'} for p in name.split('/')):
        return False
    normal = 'go-capsule-dependencies/'
    if name in {normal + 'qualification.json', normal + 'source-inputs.json', normal + 'node/workflow.json'}:
        return True
    if name.startswith(normal + 'native-binaries/'):
        return name.removeprefix(normal + 'native-binaries/') in NATIVE
    for label in COMPANIONS:
        prefix = normal + 'builds/' + label + '/'
        if name.startswith(prefix):
            suffix = name.removeprefix(prefix)
            return suffix in PUBLIC or re.fullmatch(r'wit/(?:[a-z0-9-]+/){0,3}[a-z0-9_.-]+\.wit', suffix) is not None
    prefix = 'go-standard-entropy/build/'
    if name.startswith(prefix):
        return name.removeprefix(prefix) in PUBLIC
    return name in {'go-standard-entropy/node/controls/go-entropy-' + mode + '.json'
                    for mode in ('baseline', 'read-one', 'read-wide')}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Remote(io.RawIOBase):
    def __init__(self, url: str, size: int, *, maximum_requests=MAX_REQUESTS):
        require(type(maximum_requests) is int and 1 <= maximum_requests <= 640,
                'entropy-replay-artifact-request-bound')
        self.url, self.size, self.position = url, size, 0
        self.maximum_requests = maximum_requests
        self.requests, self.network_bytes = 0, 0

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(0 <= self.position <= self.size, 'entropy-replay-artifact-range-seek')
        return self.position

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        require(0 <= count <= 8 * 1024**2, 'entropy-replay-artifact-single-range-bound')
        if not count: return b''
        self.requests += 1
        self.network_bytes += count
        PROGRESS.update(rangeRequests=self.requests, networkBytes=self.network_bytes)
        require(self.requests <= self.maximum_requests and self.network_bytes <= 128 * 1024**2, 'entropy-replay-artifact-total-range-bound')
        end = self.position + count - 1
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(response.status == 206 and response.headers['Content-Range'] ==
                    f'bytes {self.position}-{end}/{self.size}', 'entropy-replay-artifact-server-range')
            raw = response.read(count + 1)
        require(len(raw) == count, 'entropy-replay-artifact-range-length')
        self.position += count
        return raw


def acquire(output: Path, *, include_normal_greeting=False):
    """No full archive, compiler closure, private source tree or keys are copied."""
    require(type(include_normal_greeting) is bool, 'entropy-replay-artifact-greeting-selector')
    output = fresh(output)
    credential = os.environ.get('GH_TOKEN')
    require(type(credential) is str and 0 < len(credential) <= 4096, 'entropy-replay-artifact-read-credential')
    endpoint = f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}'
    headers = {'Authorization': 'Bearer ' + credential, 'Accept': 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
        require(response.status == 200, 'entropy-replay-artifact-metadata-status')
        raw = response.read(65537)
    require(len(raw) <= 65536, 'entropy-replay-artifact-metadata-size')
    metadata = json.loads(raw)
    require(metadata['id'] == ARTIFACT and metadata['workflow_run']['head_sha'] == TESTED
            and metadata['workflow_run']['id'] == 39295191090 and not metadata['expired']
            and type(metadata['size_in_bytes']) is int and 0 < metadata['size_in_bytes'] <= 2 * 1024**3,
            'entropy-replay-artifact-original-identity')
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint + '/zip', headers=headers), timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'entropy-replay-artifact-download-redirect')
        signed_url = error.headers['Location']
    else:
        raise ValueError('entropy-replay-artifact-download-must-redirect')
    parsed = urllib.parse.urlsplit(signed_url)
    require(parsed.scheme == 'https' and parsed.hostname is not None and parsed.username is None
            and (parsed.hostname.endswith('.blob.core.windows.net')
                 or parsed.hostname.endswith('.githubusercontent.com')), 'entropy-replay-artifact-download-origin')
    del credential, headers
    PROGRESS['stage'] = 'fixed-member-index'
    remote = Remote(signed_url, metadata['size_in_bytes'],
                    maximum_requests=640 if include_normal_greeting else MAX_REQUESTS)
    copied, total = [], 0
    with zipfile.ZipFile(remote) as archive:
        all_names = archive.namelist()
        require(len(all_names) <= 65536 and len(all_names) == len(set(all_names)), 'entropy-replay-artifact-member-index')
        def normal_greeting(name):
            prefix = 'go-capsule-dependencies/builds/greeting/'
            suffix = name.removeprefix(prefix)
            return include_normal_greeting and name.startswith(prefix) and (suffix in PUBLIC
                or re.fullmatch(r'wit/(?:[a-z0-9-]+/){0,3}[a-z0-9_.-]+\.wit', suffix) is not None)
        names = [name for name in all_names if selected(name) or normal_greeting(name)]
        require(24 <= len(names) <= 128, 'entropy-replay-artifact-selected-member-count')
        PROGRESS.update(stage='fixed-members', selectedMembers=len(names))
        for name in names:
            item = archive.getinfo(name)
            require(not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16)
                    and not item.flag_bits & 1 and 0 < item.file_size <= 192 * 1024**2,
                    'entropy-replay-artifact-selected-file-size')
            total += item.file_size
            require(total <= 384 * 1024**2, 'entropy-replay-artifact-selected-total-size')
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open('xb') as target:
                written = 0
                while data := source.read(1024 * 1024):
                    written += len(data)
                    require(written <= item.file_size, 'entropy-replay-artifact-decompression-bound')
                    target.write(data)
            require(written == item.file_size, 'entropy-replay-artifact-selected-file-length')
            destination.chmod(0o700 if '/native-binaries/' in name else 0o600)
            copied.append({'path': name, 'size': written})
            PROGRESS['completedMembers'] = len(copied)
    receipt = {'qualification': False, 'artifactId': ARTIFACT, 'testedSource': TESTED,
        'selected': copied, 'networkBytes': remote.network_bytes, 'rangeRequests': remote.requests,
        'completeArchiveDownloaded': False, 'credentialsRetained': False,
        'normalGreetingIncluded': include_normal_greeting}
    write_json(output / 'acquisition.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-normal-greeting', action='store_true')
    arguments = parser.parse_args()
    try:
        observed = acquire(arguments.output, include_normal_greeting=arguments.include_normal_greeting)
    except Exception as error:
        # urllib errors can contain an expiring signed URL. Never print one.
        guard = error.args[0] if isinstance(error, RuntimeError) and len(error.args) == 1 \
            and isinstance(error.args[0], str) and re.fullmatch(r'entropy-replay-artifact-[a-z-]{1,96}', error.args[0]) else 'other'
        failure = {'status': 'failed', 'errorCategory': type(error).__name__, 'guardReason': guard,
                   'progress': dict(PROGRESS), 'credentialOrSignedUrlRetained': False}
        write_json(arguments.output / 'acquisition-failure.json', failure)
        print(json.dumps(failure))
        raise SystemExit(1)
    print(json.dumps({'status': 'acquired', 'members': len(observed['selected']),
                      'networkBytes': observed['networkBytes']}))
