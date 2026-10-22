"""Fixed failed d928 public component: restore bytes, never compile or relabel."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

from tools import c_thread_runtime_fixture as fixture
from tools.c_guest import threading
from tools.build_process import run_bounded_result
from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_c_thread_runtime import build_evidence
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_json, snapshot, write_json
from tools.transaction_guest_project import packaging_arguments

SOURCE = 'd9283fd957fce5999a8302aeb4dc811921d83622'
RUN, JOB = 39689531112, 119531984383
ARTIFACT = {'id': 12387414112, 'size_in_bytes': 1550711,
    'digest': 'sha256:7e230488e7969e49e9f44943dea4e720540787c878147eee0bc750509d6cb424'}
COMPONENT = {'sha256': 'sha256:e8138c513867431a9032c52efb3c4de86a910df8d43bf6503bc25200e42929da', 'bytes': 1850511}
WIT = ('wit/world.wit', 'wit/deps/activation-runtime/package.wit', 'wit/deps/native-runtime/package.wit')


def origin(run, job, artifact):
    require(run['id'] == RUN and run['head_sha'] == SOURCE
        and run['head_branch'] == 'feat/c-thread-runtime-consumer-20261021'
        and run['event'] == 'push' and run['path'] == '.github/workflows/c-thread-runtime.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'failure'
        and run['repository']['id'] == run['head_repository']['id'] == 1337591365,
        'c-prefix-original-failed-run')
    require(job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
        and job['status'] == 'completed' and job['conclusion'] == 'failure'
        and [s['name'] for s in job['steps'] if s['conclusion'] == 'failure'] == [
            'Compile one ordinary C project and execute all seventeen original cases'],
        'c-prefix-original-failed-job')
    require(all(artifact[k] == value for k, value in ARTIFACT.items())
        and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN
        and artifact['workflow_run']['head_sha'] == SOURCE
        and artifact['name'] == 'c-thread-runtime-' + SOURCE,
        'c-prefix-original-artifact')


def extract(raw, output):
    require(type(raw) is bytes and len(raw) == ARTIFACT['size_in_bytes']
        and digest(raw) == ARTIFACT['digest'], 'c-prefix-whole-archive-identity')
    output = fresh(output)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        require(len(infos) == len({row.filename for row in infos}) == 82
            and sum(row.file_size for row in infos) == 5831341, 'c-prefix-original-whole-archive-shape')
        for row in infos:
            path = PurePosixPath(row.filename)
            require(not row.is_dir() and not path.is_absolute() and '..' not in path.parts
                and re.fullmatch(r'[A-Za-z0-9_./-]{1,512}', row.filename)
                and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                and 0 <= row.file_size <= 4 * 1024**2, 'c-prefix-original-safe-member')
        require(archive.testzip() is None, 'c-prefix-all-original-crcs')
        for row in infos:
            target = output / row.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(archive.read(row))
    return output


def git_bytes(names):
    names = sorted(set(names))
    require(0 < len(names) <= 256 and all(type(n) is str
        and re.fullmatch(r'[A-Za-z0-9_./-]{1,256}', n)
        and '..' not in PurePosixPath(n).parts for n in names), 'c-prefix-source-path-bound')
    raw = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT,
        input=''.join(SOURCE+':'+n+'\n' for n in names).encode(), stdout=subprocess.PIPE,
        check=True, timeout=60).stdout
    require(len(raw) <= 16 * 1024**2, 'c-prefix-source-byte-bound')
    result, at = {}, 0
    for name in names:
        end = raw.index(b'\n', at); oid, kind, size = raw[at:end].decode().split()
        size = int(size); at = end + 1
        require(kind == 'blob' and 0 <= size <= 4 * 1024**2 and at+size < len(raw), 'c-prefix-source-frame')
        value = raw[at:at+size]
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+value).hexdigest() == oid
            and raw[at+size:at+size+1] == b'\n', 'c-prefix-source-git-object')
        result[name] = value; at += size + 1
    require(at == len(raw), 'c-prefix-source-exact-response')
    return result


def public_wit(raw, expected):
    require(type(raw) is bytes and {'digest': digest(raw), 'size': len(raw)} == expected,
        'c-prefix-normal-compiler-staged-wit-original-package-binding')


def validate(contents):
    failed = read_json(contents / 'FAILED.json')
    require(failed['status'] == 'failed' and failed['stage'] == 'signed-seventeen-case-c-thread-programme'
        and failed['qualification'] is False and failed['producer']['source'] ==
            '7b6365ee39dea9770591a931b96711965f8a1aaf', 'c-prefix-no-original-pass-relabel')
    build = contents / 'build'; recipe = read_json(build / 'recipe-inputs.json')
    require(len(failed['materials']) == 99 and len(recipe) == 57, 'c-prefix-original-source-counts')
    originals = git_bytes([*failed['materials'], *recipe])
    for name, value in failed['materials'].items():
        raw = originals[name]
        require(value == {'sha256': digest(raw), 'bytes': len(raw)}
            and (ROOT / name).read_bytes() == raw, 'c-prefix-original-executed-source-and-current-exact')
    for name, value in recipe.items():
        raw = originals[name]
        require(value == {'digest': digest(raw), 'size': len(raw)}
            and (ROOT / name).read_bytes() == raw, 'c-prefix-original-recipe-and-current-exact')
    package = read_json(build / 'package-inputs.json')
    require(len(package) == 11 and {name for name in package if not (build/name).exists()} == set(WIT),
        'c-prefix-only-three-public-wit-bytes-missing')
    with tempfile.TemporaryDirectory(prefix='lsf-c-prefix-source-') as temp:
        app = fixture.prepare(Path(temp) / 'application')
        source = inventory(snapshot(app))
        require(source == (build/'source-inputs.json').read_bytes()
            and len(json.loads(source)) == 63, 'c-prefix-original-captured-application-source')
        staged = threading.stage(app/'wit', fixture.WORLD, Path(temp)/'staged-wit', app/'vendor/lsf/wit/platform')
        for name in WIT:
            raw = (staged / name.removeprefix('wit/')).read_bytes()
            public_wit(raw, package[name])
            target = build/name; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as out: out.write(raw)
        evidence = build_evidence(build, source)
        arguments = packaging_arguments(snapshot(app))
    require(evidence == failed['build'] and evidence['component'] == COMPONENT,
        'c-prefix-original-build-package-observation-provenance')
    proof = {'sourceRevision': SOURCE, 'originalRun': RUN, 'originalJob': JOB,
        'originalQualification': 'failed', 'component': COMPONENT, 'capturedSourceRows': 63,
        'recipeRows': 57, 'executedGitInputs': 99, 'restoredPublicWit': list(WIT),
        'restoration': 'unchanged captured application plus exact normal compiler WIT staging; original package digests',
        'originalBuildObservationRewritten': False, 'originalComponentRecompiled': False,
        'normalPackageEnvelopeRecreationRequired': True, 'packagingArguments': list(arguments), 'qualification': False}
    write_json(contents/'restoration.json', proof)
    return build, proof


def acquire(output):
    origin(api(f'actions/runs/{RUN}'), api(f'actions/jobs/{JOB}'), api(f'actions/artifacts/{ARTIFACT["id"]}'))
    result = run_bounded_result(['gh', 'api', 'repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+
        str(ARTIFACT['id'])+'/zip'], ROOT, os.environ, 90, 2 * 1024**2)
    require(result.returncode == 0, 'c-prefix-original-acquisition-failed')
    output = fresh(output)
    (output/'artifact.zip').write_bytes(result.stdout)
    return validate(extract(result.stdout, output/'contents'))
