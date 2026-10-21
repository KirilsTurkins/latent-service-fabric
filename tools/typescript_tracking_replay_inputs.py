"""Frozen successful tracking engine jobs; the cancelled boundary stays cancelled."""
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

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_http_installed_native_products as native
from tools.java_replay_materials import api, NoRedirect
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json
from tools.typescript_fetch_replay_inputs import members
from tools.typescript_guest.activation_engine import engine_input_paths
from tools.typescript_guest import import_profile, runtime_profile

RUN = 39540608310
HEAD = '927096bfbfb08a776411ab68b1e4d2c2e4ece7ea'
SOURCE = '5c38079b1de2e0bbfe437ad7003582460618742d'
PARENTS = ('fd641638c3b2aeff300c44557e0c5b31042d535a', HEAD)
SPECS = {
    'engine': (12320715918, 3304078, 'ac34daaf5a93e6f2274d74596a8b2047527cb788b1141e88c4168d80dd2f4353',
        119027954452, 'Patched SpiderMonkey intrinsic Promise library'),
    'splicer': (12319682631, 1548900, 'bf2c0f6b4f81b11d9ae4695f1b64e76ba96ea20f221647641786fc8c28a2d9c2',
        119027233855, 'Source-owned asynchronous import compiler'),
}
RECEIPTS = {
    'engine': (8756, '3a5dfd76b5afc197ecac79b1c08a5b941ac7757d2b179b6bcf15e550869ebad4'),
    'splicer': (5242, 'cf10e9a266280c874bd4440b72d792355bd96349fe64aae36aec9961ffc9a9f1'),
}


def owning(run, job, artifact, kind):
    identity, size, sha, job_id, name = SPECS[kind]
    require(run['id'] == RUN and run['head_sha'] == HEAD and run['event'] == 'pull_request'
        and run['head_branch'] == 'feat/typescript-runtime-accounting-20261021'
        and run['path'] == '.github/workflows/typescript-guest.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'cancelled', 'tracking-original-run')
    require(job['id'] == job_id and job['run_id'] == RUN and job['head_sha'] == HEAD
        and job['name'] == name and job['status'] == 'completed' and job['conclusion'] == 'success'
        and all(step['conclusion'] in ('success', 'skipped') for step in job['steps']),
        'tracking-successful-owning-job')
    require(artifact['id'] == identity and artifact['size_in_bytes'] == size
        and artifact['digest'] == 'sha256:'+sha and artifact['expired'] is False
        and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == HEAD
        and artifact['name'] == 'typescript-'+('fetch-engine-input' if kind == 'engine' else 'source-splicer-input')+'-'+SOURCE,
        'tracking-exact-artifact')


def unpack(raw, kind, destination):
    _identity, size, sha, _job, _name = SPECS[kind]
    require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, 'tracking-whole-archive')
    inventory = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        selected = members(kind, archive.infolist())
        require(sum(row.file_size for row in archive.infolist()) <= 32*1024**2
            and all(row.file_size <= 16*1024**2 for row in archive.infolist()), 'tracking-all-member-bound')
        require(archive.testzip() is None, 'tracking-all-member-crc')
        for entry in selected:
            value = archive.read(entry)
            path = destination/entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as target:
                target.write(value)
            inventory[entry.filename] = {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    return inventory


def compiler_inputs(directory):
    receipts = {}
    for kind, (size, sha) in RECEIPTS.items():
        raw = read_file(directory/kind/(kind+'-input.json'), 65536)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, 'tracking-frozen-receipt')
        receipts[kind] = raw
    engine = json.loads(receipts['engine'])
    inputs = {name: read_file(ROOT/name) for name in engine_input_paths(runtime_profile.IMPORT_PROFILE)}
    runtime_profile.validate_engine(engine, read_file(directory/'engine/engine.wasm', 16*1024**2), inputs,
        read_file(ROOT/'wit/platform/activation-runtime/package.wit'), profile=runtime_profile.IMPORT_PROFILE)
    raw = receipts['splicer']
    import_profile.validate_splicer(json.loads(raw), import_profile.splicer_files(directory/'splicer/splicer'), ROOT)
    require(engine['compilerSplicerInputDigest'] == 'sha256:'+hashlib.sha256(raw).hexdigest(),
        'tracking-engine-splicer-pair')


def native_inputs(directory):
    retained = native.verify_prepared(directory)
    return native.native_products(directory), retained


def prepare(output):
    output = fresh(output)
    commit = api('git/commits/'+SOURCE)
    require(commit['sha'] == SOURCE and tuple(row['sha'] for row in commit['parents']) == PARENTS,
        'tracking-tested-merge')
    run = api('actions/runs/'+str(RUN))
    token = os.environ.get('GH_TOKEN')
    require(isinstance(token, str) and 0 < len(token) <= 4096, 'tracking-read-token')
    records = {}
    for kind, (identity, size, _sha, job, _name) in SPECS.items():
        artifact = api('actions/artifacts/'+str(identity))
        owning(run, api('actions/jobs/'+str(job)), artifact, kind)
        request = urllib.request.Request(
            'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+str(identity)+'/zip',
            headers={'Authorization': 'Bearer '+token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'tracking-artifact-redirect')
            location = error.headers['Location']
        else:
            raise ValueError('tracking-artifact-redirect-required')
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'tracking-artifact-origin')
        with urllib.request.urlopen(location, timeout=90) as response:
            raw = response.read(size+1)
        records[kind] = {'artifact': identity, 'archiveBytes': size, 'archiveDigest': artifact['digest'],
            'members': unpack(raw, kind, output/kind), 'owningJob': job, 'owningConclusion': 'success'}
    compiler_inputs(output)
    retained = native.prepare(output/'native')
    value = {'profile': 'typescript-tracking-retirement-inputs-v1', 'source': SOURCE, 'head': HEAD,
        'run': RUN, 'originalRunConclusion': 'cancelled', 'boundaryQualified': False,
        'artifacts': records, 'native': retained, 'hostOrEngineRebuilt': False, 'credentialsRetained': False}
    write_json(output/'acquisition.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
