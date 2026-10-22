"""Authenticate the immutable five-call diagnostic guest; never rebuild or qualify."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

from tools.build_process import run_bounded_result
from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.qualify_c_thread_runtime import build_evidence
from tools.rust_capsule_project import ROOT, digest, fresh, read_json, write_json

SOURCE='f7ba4962be60365bdf9061cc1cacbabfc7c169d0'
RUN,JOB=39695554239,119551926292
ARTIFACT={'id':12391505627,'size_in_bytes':1696526,
    'digest':'sha256:e41251d21290594b11df86013a5706e0a38bf4872834f734505bd0cd975b1690'}
COMPONENT={'sha256':'sha256:0ce1a0c2a713145770dc438c3751ad2b4fe50a3df418a8dda1245358fd867c75','bytes':1855137}
MODES=('application-error','minimal-pthread')


def origin(run,job,artifact):
    require(run['id']==RUN and run['head_sha']==SOURCE
        and run['head_branch']=='diag/c-thread-minimal-20261022' and run['event']=='push'
        and run['path']=='.github/workflows/c-thread-minimal-diagnostic.yml'
        and run['repository']['id']==run['head_repository']['id']==1337591365
        and run['status']=='completed' and run['conclusion']=='success',
        'c-typed-original-diagnostic-run-not-runtime-qualification')
    require(job['id']==JOB and job['run_id']==RUN and job['head_sha']==SOURCE
        and job['status']=='completed' and job['conclusion']=='success'
        and all(s['conclusion']=='success' for s in job['steps']), 'c-typed-original-diagnostic-job')
    require(all(artifact[key]==value for key,value in ARTIFACT.items())
        and artifact['expired']is False and artifact['workflow_run']['id']==RUN
        and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['name']=='c-thread-minimal-'+SOURCE, 'c-typed-original-diagnostic-artifact')


def extract(raw,output):
    require(type(raw)is bytes and len(raw)==ARTIFACT['size_in_bytes']
        and digest(raw)==ARTIFACT['digest'],'c-typed-original-whole-archive-identity')
    output=fresh(output)
    with zipfile.ZipFile(io.BytesIO(raw))as archive:
        infos=archive.infolist()
        require(len(infos)==len({row.filename for row in infos})==179
            and sum(row.file_size for row in infos)==6316665,'c-typed-original-whole-archive-shape')
        for row in infos:
            path=PurePosixPath(row.filename)
            require(not row.is_dir() and not path.is_absolute() and '..'not in path.parts
                and re.fullmatch(r'[A-Za-z0-9_./-]{1,512}',row.filename)
                and stat.S_IFMT(row.external_attr>>16)in(0,stat.S_IFREG)
                and 0<=row.file_size<=4*1024**2,'c-typed-original-safe-member')
        require(archive.testzip()is None,'c-typed-original-all-member-crcs')
        for row in infos:
            path=output/row.filename;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb')as stream:stream.write(archive.read(row))
    return output


def git_bytes(names):
    names=sorted(set(names))
    require(0<len(names)<=256 and all(type(n)is str
        and re.fullmatch(r'[A-Za-z0-9_./-]{1,256}',n)
        and '..'not in PurePosixPath(n).parts for n in names),'c-typed-original-source-path-bound')
    raw=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,
        input=''.join(SOURCE+':'+n+'\n'for n in names).encode(),stdout=subprocess.PIPE,
        check=True,timeout=60).stdout
    require(len(raw)<=16*1024**2,'c-typed-original-git-object-byte-bound')
    at=0;answer={}
    for name in names:
        end=raw.index(b'\n',at);oid,kind,size=raw[at:end].decode().split();size=int(size);at=end+1
        require(kind=='blob' and 0<=size<=4*1024**2 and at+size<len(raw),'c-typed-original-git-frame')
        value=raw[at:at+size]
        require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+value).hexdigest()==oid
            and raw[at+size:at+size+1]==b'\n','c-typed-original-git-blob-identity')
        answer[name]=value;at+=size+1
    require(at==len(raw),'c-typed-original-git-exact-response')
    return answer


def validate(contents):
    observed=read_json(contents/'diagnostic.json');build=contents/'build'
    require(observed['schemaVersion']=='latent.c.thread-minimal.diagnostic.v1'
        and observed['status']=='observed' and observed['qualification']is False
        and observed['diagnosticOnly']is True and observed['full17ProgrammeQualified']is False
        and observed['nativeProductsRebuilt']is False and type(observed['guestComponentsCompiled'])is int
        and observed['guestComponentsCompiled']==1,'c-typed-original-diagnostic-remains-unqualified')
    source=read_json(build/'source-inputs.json');recipe=read_json(build/'recipe-inputs.json')
    require(len(source)==63 and len(recipe)==57 and len(observed['materials'])==104,
        'c-typed-original-source-and-recipe-counts')
    original=git_bytes([*recipe,*observed['materials']])
    for name,row in observed['materials'].items():
        raw=original[name]
        require(row=={'sha256':digest(raw),'bytes':len(raw)},'c-typed-original-executed-git-source')
    for name,row in recipe.items():
        raw=original[name]
        require(row=={'digest':digest(raw),'size':len(raw)},'c-typed-original-compiler-recipe')
    # Those compiler helpers are not executed by this continuation. Their
    # original Git identities stay frozen; current reader/tool inputs are bound
    # separately. No source regeneration or current-source equivalence claim.
    package=read_json(build/'package-inputs.json')
    require(len(package)==11,'c-typed-all-original-package-inputs')
    for name,row in package.items():
        raw=(build/name).read_bytes()
        require(row=={'digest':digest(raw),'size':len(raw)},'c-typed-original-package-input-byte-identity')
    for name in('src/main.c','wit/world.wit'):
        raw=(contents/'application'/name).read_bytes()
        require(source[name]=={'digest':digest(raw),'size':len(raw)},'c-typed-original-public-source-binding')
    evidence=build_evidence(build,(build/'source-inputs.json').read_bytes())
    require(evidence==observed['build'] and evidence['component']==COMPONENT
        and observed['nativeOrigin']['compiledSource']=='7b6365ee39dea9770591a931b96711965f8a1aaf',
        'c-typed-original-build-and-native-provenance')
    proof={'schemaVersion':'latent.c.thread-minimal.reuse.v1','sourceRevision':SOURCE,
        'run':RUN,'job':JOB,'artifact':ARTIFACT,'component':COMPONENT,'archiveMembers':179,
        'capturedSourceRows':63,'recipeRows':57,'executedGitInputs':104,'packageInputs':11,
        'originalQualification':False,'originalBuildObservationRewritten':False,
        'guestRecompiled':False,'sourceRegenerated':False,'witReconstructed':False,
        'currentCompilerSourceEqualityClaimed':False,'qualification':False}
    write_json(contents/'reuse.json',proof)
    return build,proof


def acquire(output):
    origin(api(f'actions/runs/{RUN}'),api(f'actions/jobs/{JOB}'),api(f'actions/artifacts/{ARTIFACT["id"]}'))
    result=run_bounded_result(['gh','api','repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+
        str(ARTIFACT['id'])+'/zip'],ROOT,os.environ,90,2*1024**2)
    require(result.returncode==0,'c-typed-original-acquisition-failed')
    output=fresh(output);(output/'artifact.zip').write_bytes(result.stdout)
    return validate(extract(result.stdout,output/'contents'))
