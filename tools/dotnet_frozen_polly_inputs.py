"""Acquire one exact historical Polly diagnostic artifact; never run its guest."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
REPOSITORY_ID = 1337591365
RUN = 41857057877
JOB = 126721225730
ARTIFACT = 13349547940
HEAD = 'bc53f0d03a8fe376405b7ef76e5678393b8d858b'
CHECKOUT = 'cdd94651216c2239be89b00719de46cf69264207'
ARTIFACT_NAME = 'dotnet-published-tasks-' + CHECKOUT
ARCHIVE_BYTES = 4176666
ARCHIVE_HASH = '32c150e10819e319487eb06046d245c3d3f40abe4c954fdc4df209009956e9f3'
COMPONENT = 'dotnet-published-tasks/build/component.wasm'
COMPONENT_BYTES = 7542795
COMPONENT_HASH = '3ab0ae8b54c5ed0469b3f9ea105fd566f308e314bdf3aeeb4529b9ed4085f20a'
RECEIPT = 'dotnet-published-tasks/qualified.json'
RECEIPT_HASH = 'a16fc9f051c676dca58bd3b1a151b4b3a3253d631f3201a5188f7fbe20440159'
PREFIX = 'https://api.github.com/repos/' + REPOSITORY


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def metadata(url, headers, deadline):
    require(time.monotonic() < deadline, 'acquisition-deadline')
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        require(response.status == 200, 'metadata-status')
        raw = response.read(1024 * 1024 + 1)
    require(len(raw) <= 1024 * 1024 and time.monotonic() < deadline, 'metadata-bound')
    return json.loads(raw)


def verify_metadata(run, job, artifact):
    require(run['id'] == RUN and run['event'] == 'pull_request' and run['head_sha'] == HEAD
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and run['repository']['id'] == REPOSITORY_ID
            and run['head_repository']['id'] == REPOSITORY_ID, 'original-run')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == HEAD
            and job['status'] == 'completed' and job['conclusion'] == 'success'
            and job['name'] == 'Published Polly default retry and timer factories', 'original-job')
    origin = artifact['workflow_run']
    require(artifact['id'] == ARTIFACT and artifact['name'] == ARTIFACT_NAME
            and artifact['size_in_bytes'] == ARCHIVE_BYTES and not artifact['expired']
            and artifact['digest'] == 'sha256:' + ARCHIVE_HASH
            and origin['id'] == RUN and origin['head_sha'] == HEAD
            and origin['repository_id'] == origin['head_repository_id'] == REPOSITORY_ID,
            'original-artifact')


def unpack(raw, output):
    require(len(raw) == ARCHIVE_BYTES and digest(raw) == ARCHIVE_HASH, 'archive-identity')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        names = [row.filename for row in rows]
        require(len(rows) == 200 and len(set(names)) == 200
                and sum(row.file_size for row in rows) == 18281466
                and max(row.file_size for row in rows) == COMPONENT_BYTES, 'archive-index')
        for row in rows:
            name = row.filename
            require(not row.is_dir() and not stat.S_ISLNK(row.external_attr >> 16)
                    and not row.flag_bits & 1 and '\\' not in name and not name.startswith('/')
                    and all(part not in ('', '.', '..') for part in name.split('/')),
                    'archive-member')
        require(archive.testzip() is None, 'archive-crc')
        component = archive.read(COMPONENT)
        receipt = archive.read(RECEIPT)
    require(len(component) == COMPONENT_BYTES and digest(component) == COMPONENT_HASH,
            'component-identity')
    require(len(receipt) == 38769 and digest(receipt) == RECEIPT_HASH, 'receipt-identity')
    record = json.loads(receipt)
    require(record['status'] == 'passed' and record['source']['head'] == CHECKOUT
            and record['component'] == {'sha256':'sha256:' + COMPONENT_HASH, 'bytes':COMPONENT_BYTES}
            and record['build']['componentDigest'] == 'sha256:' + COMPONENT_HASH,
            'receipt-binding')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'original.wasm').write_bytes(component)
    (output / 'original-qualified.json').write_bytes(receipt)
    result = {'schemaVersion':'latent.dotnet.frozen-polly.acquisition.v1',
              'originalRun':RUN,'originalJob':JOB,'originalArtifact':ARTIFACT,
              'originalHead':HEAD,'originalCheckout':CHECKOUT,
              'archiveSha256':'sha256:' + ARCHIVE_HASH,'archiveBytes':ARCHIVE_BYTES,
              'componentSha256':'sha256:' + COMPONENT_HASH,'receiptSha256':'sha256:' + RECEIPT_HASH,
              'completeArchiveCrcChecked':True,'guestExecution':False,'credentialsRetained':False}
    (output / 'acquisition.json').write_text(json.dumps(result, indent=2) + '\n',encoding='utf-8')
    return result


def acquire(output):
    credential = os.environ.get('GH_TOKEN')
    require(type(credential) is str and 0 < len(credential) <= 4096, 'credential-required')
    deadline = time.monotonic() + 180
    headers = {'Authorization':'Bearer ' + credential,'Accept':'application/vnd.github+json',
               'X-GitHub-Api-Version':'2022-11-28'}
    run = metadata(PREFIX + '/actions/runs/' + str(RUN), headers, deadline)
    job = metadata(PREFIX + '/actions/jobs/' + str(JOB), headers, deadline)
    artifact = metadata(PREFIX + '/actions/artifacts/' + str(ARTIFACT), headers, deadline)
    verify_metadata(run, job, artifact)
    request = urllib.request.Request(PREFIX + '/actions/artifacts/' + str(ARTIFACT) + '/zip',headers=headers)
    try:
        urllib.request.build_opener(NoRedirect).open(request,timeout=20)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'download-redirect')
        signed_url = error.headers['Location']
    else:
        raise ValueError('download-must-redirect')
    parsed = urllib.parse.urlsplit(signed_url)
    require(parsed.scheme == 'https' and parsed.hostname is not None and parsed.username is None
            and parsed.password is None and parsed.port in (None,443)
            and (parsed.hostname.endswith('.blob.core.windows.net')
                 or parsed.hostname.endswith('.githubusercontent.com')), 'download-origin')
    del credential, headers
    chunks=[];total=0
    with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(signed_url),timeout=20) as response:
        require(response.status == 200, 'download-status')
        while True:
            require(time.monotonic() < deadline, 'acquisition-deadline')
            chunk=response.read(min(65536,ARCHIVE_BYTES + 1 - total))
            if not chunk: break
            total += len(chunk)
            require(total <= ARCHIVE_BYTES, 'download-size')
            chunks.append(chunk)
    require(time.monotonic() < deadline, 'acquisition-deadline')
    return unpack(b''.join(chunks),output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        acquire(args.output)
    except Exception as error:
        # Never expose credentials or expiring signed URLs via urllib exceptions.
        print('acquisition failed: ' + type(error).__name__,file=sys.stderr)
        sys.exit(1)
    print('original artifact and receipt authenticated; no guest executed')