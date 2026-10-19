"""Retrieve only two authenticated historical build tools for fresh refusals."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, fresh, write_json

REPO = 'KirilsTurkins/latent-service-fabric'
HEAD = 'b53969d95763c60b29a5b14a06879689dbdb061e'
RUN, JOB, ARTIFACT = 39290090984, 118188191208, 12208056916
SIZE = 521738500
ARTIFACT_DIGEST = 'sha256:7541404f209ccf84b10a2b5eb59402546d55ebe31567e2e201f1ba1370b537c1'
RECEIPT_DIGEST = 'sha256:0f4e2c24b505f6e0fad8206d767df858a214bcd90fd50fc27d010461600f622b'
SOURCE_DIGEST = 'sha256:2d79ec09341f1961081b142f2c0a57e6f9e2dc99223cd773cc8dc069205baa71'
PREFIX = '_temp/typescript-capsule-dependencies/'
TOOLS = {
    'examples/capsule_contracts': {'sha256': 'sha256:a0ea59c420231a5f4a2e614762e930a883a42ef663afbfc2b172d509c2606b88', 'bytes': 7224720},
    'examples/package': {'sha256': 'sha256:f826023c756212d9ec907faf23cf5f9802eac127310e74cd13a1e39a0d4cffa5', 'bytes': 17726192},
}


def api(path):
    raw = subprocess.check_output(['gh', 'api', f'repos/{REPO}/' + path], timeout=30)
    require(len(raw) <= 4 * 1024 * 1024, 'refusal-replay-api-bound')
    return json.loads(raw)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Ranges(io.RawIOBase):
    def __init__(self, url, size):
        require(urlsplit(url).scheme == 'https' and 0 < size <= SIZE, 'refusal-replay-fixed-range-source')
        self.url, self.size, self.position = url, size, 0
        self.transferred, self.requests = 0, 0

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        require(whence in (0, 1, 2), 'refusal-replay-seek-kind')
        position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        require(0 <= position <= self.size, 'refusal-replay-seek-bound')
        self.position = position
        return position

    def read(self, count=-1):
        count = min(count if count >= 0 else self.size, self.size - self.position)
        require(0 <= count <= 8 * 1024 * 1024, 'refusal-replay-range-bound')
        if not count:
            return b''
        self.transferred += count
        self.requests += 1
        require(self.requests <= 4096 and self.transferred <= 2 * self.size, 'refusal-replay-total-range-bound')
        start, end = self.position, self.position + count - 1
        try:
            request = urllib.request.Request(self.url, headers={'Range': f'bytes={start}-{end}'})
            with urllib.request.urlopen(request, timeout=30) as response:
                require(response.status == 206 and response.headers.get('Content-Range')
                        == f'bytes {start}-{end}/{self.size}', 'refusal-replay-range-response')
                raw = response.read(count + 1)
        except (urllib.error.URLError, OSError):
            raise ValueError('refusal-replay-range-unavailable') from None
        require(len(raw) == count, 'refusal-replay-range-length')
        self.position += count
        return raw


def member(archive, name, maximum):
    entries = [row for row in archive.infolist() if row.filename == name]
    require(len(entries) == 1, 'refusal-replay-exact-member')
    row = entries[0]
    mode = stat.S_IFMT(row.external_attr >> 16)
    require(not row.is_dir() and not row.flag_bits & 1 and mode in (0, stat.S_IFREG)
            and 0 < row.file_size <= maximum and 0 < row.compress_size <= 32 * 1024 * 1024,
            'refusal-replay-member-type-or-bound')
    with archive.open(row) as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) == row.file_size, 'refusal-replay-member-length')
    return raw


def checked_receipt(raw):
    require(digest(raw) == RECEIPT_DIGEST, 'refusal-replay-original-receipt-digest')
    receipt = json.loads(raw)
    require(receipt['schemaVersion'] == 'latent.typescript-capsule.qualification.v1'
            and receipt['status'] == receipt['node']['status'] == 'passed'
            and receipt['sourceIdentityDigest'] == SOURCE_DIGEST
            and 'applicationDependencies' in receipt
            and all(receipt['binaries'].get(name) == identity for name, identity in TOOLS.items()),
            'refusal-replay-original-qualified-tools')
    return receipt


def prepare(output):
    require(sys.platform == 'linux', 'refusal-replay-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'refusal-replay-owned-output-outside-source')
    output = fresh(output)
    job = api(f'actions/jobs/{JOB}')
    require(job['run_id'] == RUN and job['head_sha'] == HEAD and job['status'] == 'completed'
            and all(any(row['number'] == number and row['conclusion'] == 'success'
                        for row in job['steps']) for number in (20, 23)), 'refusal-replay-original-completed-baseline')
    metadata = api(f'actions/artifacts/{ARTIFACT}')
    require(metadata['id'] == ARTIFACT and metadata['digest'] == ARTIFACT_DIGEST
            and metadata['size_in_bytes'] == SIZE and metadata['expired'] is False
            and metadata['workflow_run']['id'] == RUN and metadata['workflow_run']['head_sha'] == HEAD,
            'refusal-replay-fixed-artifact')
    token = subprocess.check_output(['gh', 'auth', 'token'], text=True, timeout=30).strip()
    request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/actions/artifacts/{ARTIFACT}/zip',
                                    headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'refusal-replay-artifact-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('refusal-replay-artifact-redirect-required')
    remote = Ranges(url, SIZE)
    with zipfile.ZipFile(remote) as archive:
        require(len(archive.infolist()) <= 65536, 'refusal-replay-member-count')
        raw = member(archive, PREFIX + 'qualification.json', 1024 * 1024)
        checked_receipt(raw)
        for name, identity in TOOLS.items():
            raw = member(archive, PREFIX + 'native-binaries/' + name.replace('/', '-'), identity['bytes'])
            require(len(raw) == identity['bytes'] and digest(raw) == identity['sha256'],
                    'refusal-replay-native-tool-digest')
            target = output / name.rpartition('/')[2]
            with target.open('xb') as stream:
                stream.write(raw)
            target.chmod(0o700)
    result = {'schemaVersion': 'latent.typescript.refusal-native-inputs.v1', 'status': 'passed',
        'originalCompiledSource': {'head': HEAD, 'run': RUN, 'job': JOB},
        'artifact': {'id': ARTIFACT, 'digest': ARTIFACT_DIGEST, 'size': SIZE},
        'originalNormalQualificationDigest': RECEIPT_DIGEST,
        'originalSourceIdentityDigest': SOURCE_DIGEST, 'tools': TOOLS,
        'rangeRequests': remote.requests, 'networkBytes': remote.transferred,
        'nativeCompilationPerformed': False, 'runtimeHostUsed': False,
        'currentCompilerSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    write_json(output / 'retrieval.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'status': prepare(args.output.resolve())['status']}))
