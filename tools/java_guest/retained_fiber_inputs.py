"""Fixed successful public Java component; data-only staging, no compiler or SDK."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import PurePosixPath
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from tools.rust_capsule_project import read_file

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
HEAD = '9871d6b54520bc2bd4fcd920f2d59d9ee0efd995'
TREE = 'cf936ae4f48c2e581978c05088eb16599da0ded3'
RUN, JOB, ARTIFACT = 40231419998, 121283781554, 12612853018
ARCHIVE = {'bytes': 2578267, 'sha256': '70304aae3dd82275536dcacc05a7960ef13b70de18b5ea6681c6c1e6e76c62a0'}
FILES = {
    'FIBERS-COMPILE.json': {'bytes': 278426, 'sha256': 'c10b0902e1aa8dd9bf285bc03b9ed8236f7558de127a513d912a6c76806a3dbc'},
    'build/component.wasm': {'bytes': 10282099, 'sha256': 'd6336d4667db6a01d4f6fd18dfb53850b0d27a7ab96d828660b98dfeb64f469c'},
    'src/Capsule.java': {'bytes': 12668, 'sha256': '6a2f7a5a13b3295761b0f18989e47cc7ff106a7c9546c559492247fcd36430c8'},
    'wit/service.wit': {'bytes': 340, 'sha256': '14c7bb47a7634153b4dcf39473a31f7f87f971f8c90a602b378be498dc938236'},
}


def need(value, reason):
    if not value:
        raise ValueError('java-retained-input-' + reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def metadata(run, job, artifact):
    need(run.get('id') == RUN and run.get('head_sha') == HEAD
        and run.get('head_commit', {}).get('tree_id') == TREE
        and run.get('head_branch') == 'feat/java-llvm-ssa-consumer-20261025'
        and run.get('run_attempt') == 1 and run.get('event') == 'workflow_dispatch'
        and run.get('path') == '.github/workflows/java-guest-feasibility.yml'
        and run.get('status') == 'completed' and run.get('conclusion') == 'success', 'run')
    steps = job.get('steps')
    need(job.get('id') == JOB and job.get('run_id') == RUN and job.get('head_sha') == HEAD
        and job.get('name') == 'Fixed public Java fiber assembly inputs only'
        and job.get('status') == 'completed' and job.get('conclusion') == 'success'
        and type(steps) is list and steps and all(s.get('status') == 'completed'
            and s.get('conclusion') in ('success', 'skipped') for s in steps), 'job')
    for name in ('Install the same prerequisites for the separately admitted private-scalar backend',
                 'Compile the unchanged public C with the independently qualified backend',
                 'Retain only fixed public assembly evidence and original failure'):
        need(sum(s.get('name') == name and s.get('conclusion') == 'success'
                 for s in steps) == 1, 'selected-steps')
    need(artifact.get('id') == ARTIFACT and artifact.get('expired') is False
        and artifact.get('workflow_run', {}).get('id') == RUN
        and artifact.get('workflow_run', {}).get('head_sha') == HEAD
        and artifact.get('name') == 'java-public-fiber-assembly-' + HEAD
        and artifact.get('size_in_bytes') == ARCHIVE['bytes']
        and artifact.get('digest') == 'sha256:' + ARCHIVE['sha256'], 'artifact')


def decode(raw):
    need(identity(raw) == ARCHIVE, 'whole-archive')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        need(len(entries) == 133 and sum(i.file_size for i in entries) == 27383087, 'archive-bounds')
        names = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            need(item.filename not in names and not path.is_absolute()
                and str(path) == item.filename and '..' not in path.parts
                and '\\' not in item.filename and ':' not in item.filename
                and not item.flag_bits & 1 and stat.S_ISREG(item.external_attr >> 16), 'member-kind')
            names.add(item.filename)
        need(archive.testzip() is None, 'all-crcs')
        result = {name: archive.read('java-activation-fibers/' + name) for name in FILES}
    need({name: identity(value) for name, value in result.items()} == FILES, 'four-inputs')
    record = json.loads(result['FIBERS-COMPILE.json'])
    need(record.get('profile') == 'teavm-activation-fibers-v1'
        and record.get('fixture') == 'threads' and record.get('status') == 'component-built-unqualified'
        and record.get('qualification') == 'pending' and record.get('nodeExecution') == 'not-run'
        and record.get('componentDigest') == 'sha256:' + FILES['build/component.wasm']['sha256']
        and record.get('sourceDigest') == 'sha256:' + FILES['src/Capsule.java']['sha256'], 'compile-only-record')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def response(request, deadline, maximum):
    need(time.monotonic() < deadline, 'deadline')
    with urllib.request.build_opener(NoRedirect).open(request,
            timeout=min(30, deadline - time.monotonic())) as source:
        raw = bytearray()
        while block := source.read1(min(65536, maximum + 1 - len(raw))):
            raw.extend(block)
            need(len(raw) <= maximum and time.monotonic() < deadline, 'response-bound')
    need(time.monotonic() < deadline, 'deadline')
    return bytes(raw)


def acquire(output, deadline, token):
    """One fixed archive; GitHub token is never sent to signed blob storage."""
    deadline = min(deadline, time.monotonic() + 120)
    need(0 < len(token) <= 4096, 'token')
    base = 'https://api.github.com/repos/' + REPOSITORY + '/'
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    values = [json.loads(response(urllib.request.Request(base + path, headers=headers), deadline, 4 * 1024**2))
        for path in (f'actions/runs/{RUN}', f'actions/jobs/{JOB}', f'actions/artifacts/{ARTIFACT}')]
    metadata(*values)
    try:
        with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(
                base + f'actions/artifacts/{ARTIFACT}/zip', headers=headers),
                timeout=min(30, deadline - time.monotonic())):
            raise ValueError('java-retained-input-redirect-required')
    except urllib.error.HTTPError as error:
        try:
            need(error.code == 302, 'redirect')
            location = error.headers['Location']
        finally:
            error.close()
    url = urllib.parse.urlsplit(location)
    need(url.scheme == 'https' and url.username is None and url.password is None
        and url.port in (None, 443) and url.hostname is not None
        and (url.hostname.endswith('.blob.core.windows.net')
             or url.hostname.endswith('.githubusercontent.com')), 'blob-origin')
    raw = response(urllib.request.Request(location), deadline, ARCHIVE['bytes'])
    files = decode(raw)
    archive = output / 'public-component.zip'
    archive.write_bytes(raw)
    stage(output, files)
    return dict(zip(('run', 'job', 'artifact'), values))


def stage(output, files):
    need({name: identity(raw) for name, raw in files.items()} == FILES, 'staged-inputs')
    for name, raw in files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as target:
            target.write(raw)


def recheck(output):
    need({name: identity(read_file(output / name, row['bytes']))
          for name, row in FILES.items()} == FILES, 'final-inputs')
    need(identity(read_file(output / 'public-component.zip', ARCHIVE['bytes'])) == ARCHIVE,
         'final-archive')
