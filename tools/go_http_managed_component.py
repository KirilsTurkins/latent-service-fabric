"""Restore one authenticated normal v5 build for a reader-only signed replay.

The producer failed its observation reader after construction. Its failed result
is retained; only its original successful build is reused, never qualification.
"""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import PurePosixPath
import stat
import subprocess
import zipfile

from tools.go_http_tenant_fixture import project
from tools.go_guest.activation import MANAGED_PROFILE
from tools.java_replay_materials import api, REPOSITORY
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh

SOURCE='a357a9ec3e7f8f2b672ee4a5c9c78b9326d240b7'
RUN=39472403895
JOB=118799553945
ARTIFACT={'id':12289211025,'size_in_bytes':3695655,
    'digest':'sha256:5f0d0ae9fe7a606a0bafbcf810f4eb4f3578b93c4330476e5f84061b683a0ee6'}
PREFIX='go-http-tenant-catalogue/'
FILES=('BUILD-COMPLETE.json','application-dependencies.json','bindings.json','build-observation.json',
    'capsule.json','deployment.json','compatibility-context.json','compatibility-reachability.json',
    'compatibility-inspection.json','compatibility-report.json','compiler-containment.json','contracts.json',
    'diagnostic-files.json','go-module-build-inputs.json','go-runtime-transformations.json',
    'package-inputs.json','package-source.json','source-inputs.json','recipe-inputs.json',
    'standard-runtime-selection.json','surface.json','wit-lock.json','component.wasm')


def identity(raw):return {'sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def preflight(raw):
    require(type(raw) is bytes and identity(raw)=={'sha256':ARTIFACT['digest'],'bytes':ARTIFACT['size_in_bytes']},
        'go-http-managed-fixed-original-archive')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist()
        require(len(entries)==182 and len({entry.filename for entry in entries})==182
            and sum(entry.file_size for entry in entries)<=32*1024**2,'go-http-managed-original-archive-envelope')
        for entry in entries:
            name=PurePosixPath(entry.filename)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in entry.filename
                and 0<=entry.file_size<=16*1024**2 and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG),
                'go-http-managed-original-member-shape')
        require(archive.testzip() is None,'go-http-managed-original-crc')
        names=[PREFIX+'build/'+name for name in FILES]+[PREFIX+'FAILED.json',PREFIX+'catalogue-free-compiler/BUILD-SOURCE-INVENTORY.json']
        require(set(names)<=set(archive.namelist()),'go-http-managed-original-build-members')
        return {name:archive.read(name) for name in names}


def validate_inputs(files):
    get=lambda name:json.loads(files[PREFIX+name])
    original=get('FAILED.json');marker=get('build/BUILD-COMPLETE.json');observed=get('build/build-observation.json')
    require(original['status']=='failed' and original['stage']=='signed-same-cell-two-tenant-ordinary-http'
        and original['errorCategory']=='RuntimeError' and original['runtimeProfile']==MANAGED_PROFILE
        and [(row['stage'],row['exitCode']) for row in original['commands']]==[('capture',0),('compile',0)],
        'go-http-managed-original-failure-not-qualification')
    for name,expected in original['sourceMaterials'].items():
        raw=subprocess.check_output(['git','show',SOURCE+':'+name],cwd=ROOT,timeout=30)
        require(identity(raw)==expected,'go-http-managed-original-executed-source')
    for name,expected in original['build'].items():
        require(identity(files[PREFIX+'build/'+name])==expected,'go-http-managed-original-build-identity')
    require(marker['packageAssembled'] is True and marker['observationDigest']==identity(files[PREFIX+'build/build-observation.json'])['sha256']
        and marker['sourceDigest']==identity(files[PREFIX+'build/source-inputs.json'])['sha256']
        and marker['componentDigest']==observed['componentDigest']==identity(files[PREFIX+'build/component.wasm'])['sha256']
        and observed['parameters']['runtime']==MANAGED_PROFILE
        and len(marker['commands'])==22 and all(row['exitCode']==0 for row in marker['commands'])
        and {'component-build','component-validate','package','inspect'}<=set(row['stage'] for row in marker['commands']),
        'go-http-managed-complete-normal-v5-build')
    staged=get('catalogue-free-compiler/BUILD-SOURCE-INVENTORY.json')
    require(staged==original['catalogueFreeCompiler'] and len(staged['files'])==91
        and staged['optionalReferenceDataPresent'] is False,'go-http-managed-original-normal-stage')
    for name,row in staged['files'].items():
        actual=file_identity(ROOT/name)
        require(row=={'digest':actual['sha256'],'size':actual['bytes']},'go-http-managed-current-compiler-recipe-drift')
    inputs=get('build/source-inputs.json');sdk={name:row for name,row in inputs.items() if name.startswith('vendor/lsf/sdk/go-guest/')}
    require(len(sdk)==60,'go-http-managed-original-captured-sdk-closure')
    for name,row in sdk.items():
        actual=file_identity(ROOT/name.removeprefix('vendor/lsf/'))
        require(row=={'digest':actual['sha256'],'size':actual['bytes']},'go-http-managed-current-sdk-drift')
    return original


def restore(output):
    run=api('actions/runs/'+str(RUN));jobs=api('actions/runs/'+str(RUN)+'/jobs?per_page=100')
    require(run['head_sha']==SOURCE and run['status']=='completed' and run['conclusion']=='failure'
        and run['path']=='.github/workflows/go-http-managed-accounting.yml'
        and len(jobs['jobs'])==1 and jobs['jobs'][0]['id']==JOB
        and jobs['jobs'][0]['status']=='completed' and jobs['jobs'][0]['conclusion']=='failure',
        'go-http-managed-original-failed-run-identity')
    artifact=api('actions/artifacts/'+str(ARTIFACT['id']))
    require(all(artifact.get(key)==value for key,value in ARTIFACT.items())
        and artifact['workflow_run']['id']==RUN and artifact['workflow_run']['head_sha']==SOURCE
        and artifact['expired'] is False,'go-http-managed-original-artifact-api-identity')
    raw=subprocess.check_output(['gh','api','repos/'+REPOSITORY+'/actions/artifacts/'+str(ARTIFACT['id'])+'/zip'],timeout=60)
    files=preflight(raw);original=validate_inputs(files)
    output=fresh(output)
    for name in FILES:(output/name).write_bytes(files[PREFIX+'build/'+name])
    # Only missing WIT source assets are restored through the exact ordinary
    # fixture creator. No componentization, dependency fetch or metadata rewrite.
    app,_=project(output.parent/'restored-fixture',output.parent/'restored-private',
        'outside.example.test/http-library/tenant-catalogue-free',runtime_profile=MANAGED_PROFILE)
    inputs=json.loads((output/'source-inputs.json').read_bytes())
    for name in ('src/main.go','src/tenant.go'):
        actual=file_identity(app/name)
        require(inputs[name]=={'digest':actual['sha256'],'size':actual['bytes']},'go-http-managed-original-fixture-source-drift')
    package=json.loads((output/'package-inputs.json').read_bytes())
    restored={}
    for name,row in package.items():
        if name.startswith('wit/'):
            path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((app/name).read_bytes())
            restored[name]=file_identity(path)
        actual=file_identity(output/name)
        require(row=={'digest':actual['sha256'],'size':actual['bytes']},'go-http-managed-original-package-input-drift')
    require(len(restored)==5,'go-http-managed-all-original-wit-assets-restored')
    (output.parent/'original-FAILED.json').write_bytes(files[PREFIX+'FAILED.json'])
    return {'producerSource':SOURCE,'run':RUN,'job':JOB,'artifact':dict(ARTIFACT),
        'originalProgrammeStatus':'failed','onlyOriginalSuccessfulConstructionReused':True,
        'componentCompilationPerformed':False,'nativeCompilationPerformed':False,
        'currentNormalRecipeInputsEqual':91,'currentCapturedSdkInputsEqual':60,
        'restoredOriginalWitInputs':restored,'originalBuild':original['build']}
