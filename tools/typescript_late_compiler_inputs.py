"""Only the two immutable current tracking compiler products; no native host."""
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

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import typescript_tracking_replay_inputs as original
from tools.java_replay_materials import api, NoRedirect
from tools.phase2_operator_process import require
from tools.rust_capsule_project import fresh, read_file, read_json, write_json


def verify(directory):
    record = read_json(directory/'acquisition.json')
    require(record['profile'] == 'typescript-current-late-compiler-inputs-v1'
        and record['source'] == original.SOURCE and record['head'] == original.HEAD
        and record['run'] == original.RUN and record['originalRunConclusion'] == 'cancelled'
        and record['boundaryQualified'] is record['hostOrEngineRebuilt'] is record['credentialsRetained'] is False
        and set(record['artifacts']) == set(original.SPECS), 'resource-ts-late-current-compiler-binding')
    for kind,(identity,size,sha,job,_name) in original.SPECS.items():
        selected = record['artifacts'][kind]
        require(selected['artifact'] == identity and selected['archiveBytes'] == size
            and selected['archiveDigest'] == 'sha256:'+sha and selected['owningJob'] == job
            and selected['owningConclusion'] == 'success', 'resource-ts-late-successful-compiler-owner')
        raw = read_file(directory/('archive-'+kind+'.zip'),size+1)
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha,
            'resource-ts-late-whole-compiler-archive')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(archive.testzip() is None,'resource-ts-late-compiler-all-crc')
            members = original.members(kind,archive.infolist())
            expected = {row.filename:{'bytes':row.file_size,
                'sha256':hashlib.sha256(archive.read(row)).hexdigest()} for row in members}
            require(selected['members'] == expected,'resource-ts-late-compiler-original-members')
            for name,row in expected.items():
                body = read_file(directory/kind/name,16*1024**2)
                require(len(body) == row['bytes'] and hashlib.sha256(body).hexdigest() == row['sha256'],
                    'resource-ts-late-compiler-member-preimage')
    original.compiler_inputs(directory)
    return record


def prepare(output):
    output = fresh(output)
    commit = api('git/commits/'+original.SOURCE)
    require(commit['sha'] == original.SOURCE
        and tuple(row['sha'] for row in commit['parents']) == original.PARENTS,'resource-ts-late-compiler-tested-merge')
    run = api('actions/runs/'+str(original.RUN))
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and 0 < len(token) <= 4096,'resource-ts-late-compiler-read-token')
    records = {}
    for kind,(identity,size,_sha,job,_name) in original.SPECS.items():
        artifact = api('actions/artifacts/'+str(identity))
        original.owning(run,api('actions/jobs/'+str(job)),artifact,kind)
        request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+str(identity)+'/zip',
            headers={'Authorization':'Bearer '+token})
        try:urllib.request.build_opener(NoRedirect).open(request,timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302,'resource-ts-late-compiler-download-redirect')
            location = error.headers['Location']
        else:raise ValueError('resource-ts-late-compiler-redirect-required')
        url = urllib.parse.urlsplit(location)
        require(url.scheme == 'https' and url.username is None and url.hostname is not None
            and (url.hostname.endswith('.blob.core.windows.net') or url.hostname.endswith('.githubusercontent.com')),
            'resource-ts-late-compiler-download-origin')
        with urllib.request.urlopen(location,timeout=90) as response:raw = response.read(size+1)
        (output/('archive-'+kind+'.zip')).write_bytes(raw)
        records[kind] = {'artifact':identity,'archiveBytes':size,'archiveDigest':artifact['digest'],
            'members':original.unpack(raw,kind,output/kind),'owningJob':job,'owningConclusion':'success'}
    value = {'profile':'typescript-current-late-compiler-inputs-v1','source':original.SOURCE,'head':original.HEAD,
        'run':original.RUN,'originalRunConclusion':'cancelled','boundaryQualified':False,
        'artifacts':records,'hostOrEngineRebuilt':False,'credentialsRetained':False}
    write_json(output/'acquisition.json',value)
    require(verify(output) == value,'resource-ts-late-final-current-compiler-inputs')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output)
