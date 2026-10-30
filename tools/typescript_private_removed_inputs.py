"""Fixed completed guest packages from one explicitly cancelled producer job."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.java_replay_materials import api, git_source_identity, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

FIXTURE = ROOT/'tools/tests/fixtures/typescript_private_removed_inputs.json'
FIXTURE_SHA256 = '581863dbabb0821ad5602b3cbca8a7dc8d1bba846ec9b7f3efb8b2118910337c'
FIXTURE_BYTES = 15088
SOURCE = 'a8cd4fbb71d7766e886ab518542ca398237debb6'
MAX_EXPANDED = 64*1024**2
MAX_TRANSFER = 128*1024**2
MAX_REQUESTS = 512


class BoundedRanges(Ranges):
    """Charge every attempt; retry only Azure ServerBusy within one deadline."""
    def read(self, count=-1):
        if count == -1:
            count = self.size-self.position
        require(0 <= count <= 8*1024**2, 'java-replay-range-bound')
        count = min(count,self.size-self.position)
        if not count:
            return b''
        expires = time.monotonic()+30
        for attempt in range(3):
            require(self.requests < MAX_REQUESTS and count <= MAX_TRANSFER-self.transferred,
                'ts-private-removed-selected-acquisition-bound')
            remaining = expires-time.monotonic()
            delay = (0,2,8)[attempt]
            require(remaining > delay, 'ts-private-removed-range-deadline')
            if delay:
                time.sleep(delay)
                remaining = expires-time.monotonic()
                require(remaining > 0, 'ts-private-removed-range-deadline')
            # A refused/partial remote attempt consumes the SAME original
            # requested-byte/request ceilings; no refund on HTTP failure.
            self.requests += 1
            self.transferred += count
            end = self.position+count-1
            request = urllib.request.Request(self.url,
                headers={'Range':f'bytes={self.position}-{end}'})
            try:
                with urllib.request.urlopen(request,timeout=remaining) as response:
                    require(response.status == 206 and response.headers['Content-Range'] ==
                        f'bytes {self.position}-{end}/{self.size}', 'java-replay-range-response')
                    raw = response.read(count+1)
            except urllib.error.HTTPError as error:
                busy = error.code == 503 and ((error.headers or {}).get('x-ms-error-code') == 'ServerBusy'
                    or error.reason == 'Egress is over the account limit.')
                if not busy or attempt == 2:
                    raise
                error.close()
                continue
            require(time.monotonic() < expires, 'ts-private-removed-range-deadline')
            require(len(raw) == count, 'java-replay-range-length')
            self.position += count
            return raw


def fixture():
    raw = FIXTURE.read_bytes()
    require(len(raw) == FIXTURE_BYTES and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256,
        'ts-private-removed-fixed-input-contract')
    value = json.loads(raw)
    require(value['source'] == SOURCE and len(value['members']) == 72 and
        sum(row['bytes'] for row in value['members'].values()) <= MAX_EXPANDED,
        'ts-private-removed-fixed-members')
    return value


def origin(artifact, job, run):
    value = fixture(); expected = value['artifact']
    require(artifact['id'] == expected['id'] and artifact['size_in_bytes'] == expected['bytes']
        and artifact['digest'] == 'sha256:'+expected['sha256'] and not artifact['expired']
        and artifact['workflow_run']['id'] == value['run']
        and artifact['workflow_run']['head_sha'] == SOURCE,
        'ts-private-removed-official-artifact')
    require(job['id'] == value['job'] and job['run_id'] == value['run']
        and job['head_sha'] == SOURCE and job['head_branch'] == 'development'
        and job['name'] == 'TypeScript guest value and ownership boundary'
        and job['status'] == 'completed' and job['conclusion'] == 'cancelled'
        and run['id'] == value['run'] and run['head_sha'] == SOURCE
        and run['head_branch'] == 'development' and run['event'] == 'push'
        and run['path'] == '.github/workflows/typescript-guest.yml'
        and run['status'] == 'completed' and run['conclusion'] in ('cancelled','failure'),
        'ts-private-removed-cancelled-producer-not-qualified')


def preflight(archive):
    value = fixture(); rows = archive.infolist(); names = [row.filename for row in rows]
    require(len(names) == len(set(names)) <= 10000, 'ts-private-removed-archive-index')
    selected = {}; compressed = 0
    for name, expected in value['members'].items():
        path = PurePosixPath(name)
        require(path.as_posix() == name and not path.is_absolute() and
            all(part not in ('','.','..') for part in name.split('/')) and
            ':' not in name and '\\' not in name, 'ts-private-removed-regular-member-path')
        row = archive.getinfo(value['zipPrefix']+name)
        require(row.file_size == expected['bytes'] and
            0 <= row.compress_size <= expected['bytes']+65536 and not row.is_dir() and
            not row.flag_bits & 1 and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
            'ts-private-removed-fixed-member-preflight')
        compressed += row.compress_size
        # Reserve eight MiB of the original128MiB transfer bound for the
        # central index and per-member headers before opening any payload.
        require(compressed <= 120*1024**2, 'ts-private-removed-compressed-acquisition-bound')
        selected[name] = row
    return selected


def reconstruct(root):
    """One missing public static WIT; its package-inventory hash stays exact."""
    proof = {}
    for name, row in fixture()['reconstructed'].items():
        raw = subprocess.check_output(['git','show',SOURCE+':'+row['gitPath']],cwd=ROOT,timeout=30)
        require(len(raw) == row['identity']['bytes'] and
            'sha256:'+hashlib.sha256(raw).hexdigest() == row['identity']['sha256'],
            'ts-private-removed-original-static-layer')
        path = root/name; path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with path.open('xb') as target: target.write(raw)
        proof[name] = dict(source=SOURCE,gitPath=row['gitPath'],identity=row['identity'],
            artifactMemberAbsent=True,componentRebuilt=False)
    return proof


def historical(value, capture, qualification, snapshot):
    require(capture['status'] == 'passed' and capture['nonce'] == fixture()['nonce'] and
        capture['peerPhysicallyReaped'] and capture['originalPackagesUnavailableBeforeBuild'],
        'ts-private-removed-original-capture')
    rows = []
    for label in ('0','0-rebuild','1'):
        node = value[label]; private = node['capturedNpmPrivate']
        require(node['status'] == 'passed' and node['language'] == 'typescript'
            and node['source'] == snapshot['runtime']
            and node['binaries'] == {'cli':qualification['binaries']['latent'],
                'node':qualification['binaries']['latentd']}
            and len(node['invocations']) == 30 and all(r['processReaped'] for r in node['invocations'])
            and private['status'] == 'passed' and len(private['cases']) == 3
            and all(r['actualSignedTarget'] and r['freshState'] for r in private['cases'])
            and private['nonce'] == capture['nonce'] and private['removed'] is False
            and private['version'] == ('1.1.0' if label == '1' else '1.0.0')
            and private['condition'] == ('default' if label == '1' else 'enabled')
            and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
            'ts-private-removed-original-completed-node')
        rows.append(dict(label=label,source=SOURCE,status='passed',invocations=30,privateCases=3,
            runtimeHostSource=SOURCE,physicallyReaped=True,newHostExecutionClaimed=False))
    return rows


def original_deployment(directory, marker):
    deployment = read_json(directory/'deployment.json'); manifest = read_json(directory/'capsule.json')
    require(deployment['metadata']['tenant'] == manifest['metadata']['tenant'] == 'examples'
        and deployment['spec']['service'] == manifest['metadata']['name']
        and deployment['spec']['release'] == marker['componentDigest']
        and deployment['spec']['grants'] == [], 'ts-private-removed-original-deployment-association')


def verify_prepared(root):
    root = Path(root).resolve(strict=True); value = fixture()
    materials = {**value['members'],**{n:r['identity'] for n,r in value['reconstructed'].items()}}
    require(all(file_identity(root/name,MAX_EXPANDED) == row for name,row in materials.items()),
        'ts-private-removed-exact-input-bytes')
    prefix = root/'typescript-capsule-dependencies'
    qualification = read_json(prefix/'qualification.json'); snapshot = read_json(prefix/'source-inputs.json')
    require(qualification['status'] == 'passed' and
        (prefix/'source-inputs.json').read_bytes() == (prefix/'source-inputs-after.json').read_bytes()
        and file_identity(prefix/'source-inputs.json')['sha256'] == qualification['sourceIdentityDigest']
        and snapshot['runtime'] == git_source_identity(SOURCE),
        'ts-private-removed-original-source-not-current-tree')
    capture = read_json(root/'npm-private-dependencies/capture.json')
    nodes = {label:read_json(root/'npm-private-dependencies'/('node-'+label)/'workflow.json')
        for label in value['priorLabels']}
    prior = historical(nodes,capture,qualification,snapshot)
    builds = {}
    for template,name in value['buildDirectories'].items():
        directory = root/name; marker = read_json(directory/'BUILD-COMPLETE.json')
        require(marker['formatVersion'] == 1 and marker['packageAssembled'] and
            file_identity(directory/'build-observation.json')['sha256'] == marker['observationDigest'] and
            file_identity(directory/'source-inputs.json',4*1024**2)['sha256'] == marker['sourceDigest'] and
            file_identity(directory/'component.wasm',MAX_EXPANDED)['sha256'] == marker['componentDigest'],
            'ts-private-removed-completed-build-association')
        if template != 'greeting':
            require(marker == qualification['builds'][template], 'ts-private-removed-original-companion')
        package = read_json(directory/'package-source.json'); inventory = read_json(directory/'package-inputs.json')
        names = ['package-source.json',*(row['source'] for row in package['layers'])]
        require(set(inventory) == set(names) and all(
            file_identity(directory/n,MAX_EXPANDED) == {'sha256':r['digest'],'bytes':r['size']}
            for n,r in inventory.items()), 'ts-private-removed-original-package-layers')
        original_deployment(directory,marker)
        builds[template] = directory
    return builds,dict(guestSource=SOURCE,producerRun=value['run'],producerJob=value['job'],
        producerCancelled=True,wholeProducerQualified=False,wholeArchiveDigestVerified=False,
        members=materials,historicalCompletedNodes=prior,staticLayerReconstruction=value['reconstructed'])


def prepare(output):
    value = fixture(); artifact = api('actions/artifacts/'+str(value['artifact']['id']))
    job = api('actions/jobs/'+str(value['job'])); run = api('actions/runs/'+str(value['run']))
    origin(artifact,job,run); output = fresh(output)
    token = os.environ.get('GH_TOKEN'); require(bool(token), 'ts-private-removed-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization':'Bearer '+token})
    try: urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'ts-private-removed-download-redirect'); url = error.headers['Location']
    else: raise ValueError('ts-private-removed-download-redirect-required')
    require(url.startswith('https://'), 'ts-private-removed-download-https')
    remote = BoundedRanges(url,artifact['size_in_bytes'])
    with zipfile.ZipFile(remote) as archive:
        selected = preflight(archive)
        for name,row in selected.items():
            path = output/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with archive.open(row) as source,path.open('xb') as target:
                count = 0
                while raw := source.read(1024**2):
                    count += len(raw); require(count <= row.file_size, 'ts-private-removed-extract-bound')
                    target.write(raw)
            require(count == row.file_size and file_identity(path,MAX_EXPANDED) == value['members'][name],
                'ts-private-removed-selected-member-hash-and-crc')
    require(remote.transferred <= MAX_TRANSFER and remote.requests <= MAX_REQUESTS,
        'ts-private-removed-selected-acquisition-bound')
    recovery = reconstruct(output); _,proof = verify_prepared(output)
    record = {**proof,'schemaVersion':'lsf.typescript-private-removed-acquisition.v1',
        'archive':artifact['id'],'officialArchiveDigest':artifact['digest'],'selectedMembersCrcVerified':72,
        'rangeBytes':remote.transferred,'rangeRequests':remote.requests,'staticLayerReconstruction':recovery}
    write_json(output/'retrieval.json',record); return record


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output)
