"""Execute the original successful library build after a progress-file repair."""
from __future__ import annotations
import argparse
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import dotnet_published_http_node as node
from tools import dotnet_catalogue_free_build as staging
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_published_http import MATERIALS
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json
from tools.wait_runtime_native_products import SOURCE as NATIVE_SOURCE, RECEIPTS, native_products, verify_prepared

SOURCE='7e3de703bc7666cee9407ff15205b9d5809a9c20'
RUN=39474941546
JOB=118808360422
ARTIFACT={'id':12289203083,'size_in_bytes':13845247,
    'digest':'sha256:397df908000ca2aba133342450e3bb0be04ecfe0f9fd74c2d0fd9cd6126c8c3e'}
COMPONENT={'sha256':'sha256:38dc48243000189bf4e8afd6d28577a0755b48a630d4b339dc935d55b6e269dd','bytes':10579214}
PREFIX='published-http/'
WIT=frozenset(('wit/world.wit',*(f'wit/deps/{name}/package.wit' for name in (
    'activation-runtime','clock','http-v3','random'))))
WORKFLOW='.github/workflows/dotnet-published-http.yml'
NODE='tools/dotnet_published_http_node.py'
PROGRESS_OLD=b"write_json(output/'progress.json',record)"
PROGRESS_NEW=b"write_json(output/('progress-'+label+'.json'),record)"


def validate_origin(metadata,job):
    require(all(metadata.get(k)==v for k,v in ARTIFACT.items()) and metadata.get('expired') is False
        and metadata.get('workflow_run',{}).get('id')==RUN and metadata['workflow_run'].get('head_sha')==SOURCE
        and job.get('id')==JOB and job.get('run_id')==RUN and job.get('head_sha')==SOURCE
        and job.get('status')=='completed' and job.get('conclusion')=='failure',
        'published-dotnet-replay-exact-failed-programme-origin')


def unpack(raw,output):
    require(len(raw)==ARTIFACT['size_in_bytes'] and digest(raw)==ARTIFACT['digest'],
            'published-dotnet-replay-original-archive-sha256')
    rows=[];total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=archive.infolist()
        require(len(members)==356 and len({m.filename for m in members})==356,
                'published-dotnet-replay-fixed-original-members')
        for member in members:
            path=PurePosixPath(member.filename)
            require(member.orig_filename==member.filename and not path.is_absolute()
                and '..' not in path.parts and '\\' not in member.filename and ':' not in member.filename
                and path.as_posix()==member.filename and not member.is_dir()
                and stat.S_IFMT(member.external_attr>>16)!=stat.S_IFLNK and not member.flag_bits&1
                and 0<=member.file_size<=64*1024**2,'published-dotnet-replay-regular-public-member')
            total+=member.file_size
            require(total<=192*1024**2,'published-dotnet-replay-expanded-byte-bound')
            data=archive.read(member)
            require(len(data)==member.file_size,'published-dotnet-replay-member-crc-and-length')
            rows.append({'path':member.filename,'sha256':digest(data),'bytes':len(data)})
            if member.filename.startswith(PREFIX+'build/') or member.filename in (
                    PREFIX+'FAILED.json',PREFIX+'catalogue-free-source.json',PREFIX+'node/FAILED.json'):
                target=output.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as stream:stream.write(data)
    return {'members':rows,'expandedBytes':total,'archiveDigest':ARTIFACT['digest']}


def acquire(output):
    metadata=api(f'actions/artifacts/{ARTIFACT["id"]}');job=api(f'actions/jobs/{JOB}')
    validate_origin(metadata,job)
    token=os.environ.get('GH_TOKEN');require(bool(token),'published-dotnet-replay-explicit-actions-token')
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization':'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code==302,'published-dotnet-replay-redirect');url=error.headers['Location']
    else:raise ValueError('published-dotnet-replay-redirect-required')
    require(url.startswith('https://'),'published-dotnet-replay-public-https')
    remote=Ranges(url,ARTIFACT['size_in_bytes'])
    inventory=unpack(remote.read(ARTIFACT['size_in_bytes']),output)
    return output/PREFIX/'build',{'artifact':metadata,'job':job,'archive':inventory}


def verify_original(original,artifact,stage):
    require(original['status']=='failed' and original['stage']=='signed-library-and-extension-programme'
        and set(original['qualificationSources'])==set(MATERIALS),'published-dotnet-replay-original-qualification-stage')
    for name,expected in original['qualificationSources'].items():
        raw=subprocess.check_output(['git','show',SOURCE+':'+name],cwd=ROOT,timeout=15)
        require(expected=={'sha256':digest(raw),'bytes':len(raw)},'published-dotnet-replay-original-git-material')
        if name==NODE:
            current=read_file(ROOT/name)
            require(current.count(PROGRESS_NEW)==1 and current.replace(PROGRESS_NEW,PROGRESS_OLD)==raw,
                    'published-dotnet-replay-only-progress-filename-change')
        elif name!=WORKFLOW:
            require(file_identity(ROOT/name)==expected,'published-dotnet-replay-unchanged-build-input')
    old_native=original['nativeProducer']
    require(old_native['compiledSource']==NATIVE_SOURCE
        and old_native['producerReceipt']==RECEIPTS['native-products.json']
        and old_native['sourceSnapshot']==RECEIPTS['source-inputs.json'],
        'published-dotnet-replay-original-native-ancestry')
    require(staging.stage(ROOT,stage)==read_json(artifact.parent/'catalogue-free-source.json'),
            'published-dotnet-replay-exact-normal-compiler-recipe')
    source_inputs=read_json(artifact/'source-inputs.json')
    sdk_count=0
    for name,expected in source_inputs.items():
        if name.startswith('vendor/lsf/'):
            require({'digest':digest(read_file(ROOT/name.removeprefix('vendor/lsf/'))),
                'size':len(read_file(ROOT/name.removeprefix('vendor/lsf/')))}==expected,
                'published-dotnet-replay-current-captured-sdk-preimage')
            sdk_count+=1
    require(sdk_count>=60,'published-dotnet-replay-real-captured-sdk-closure')
    marker=read_json(artifact/'BUILD-COMPLETE.json');observation=read_json(artifact/'build-observation.json')
    require(marker==original['build'] and marker['packageAssembled'] is True
        and marker['observationDigest']==digest(read_file(artifact/'build-observation.json'))
        and marker['sourceDigest']==digest(read_file(artifact/'source-inputs.json'))
        and marker['componentDigest']==COMPONENT['sha256'] and file_identity(artifact/'component.wasm')==COMPONENT
        and observation['componentDigest']==COMPONENT['sha256'] and observation['componentSize']==COMPONENT['bytes']
        and any(row['stage']=='native-aot' and row['exitCode']==0 for row in marker['commands'])
        and all(row['exitCode']==0 for row in marker['commands']), 'published-dotnet-replay-authentic-successful-build')
    generated=read_json(artifact/'executable-input-outputs.json',32*1024**2)
    require(generated['approvalIdentity']==original['generatorApproval']['identity']
        and generated['compilerCommandSucceeded'] is True and original['generatorApproval']['unapprovedBuildRefusedBeforeCompile'] is True
        and file_identity(artifact/'executable-input-outputs.json',32*1024**2)==original['generatorOutputs'],
        'published-dotnet-replay-exact-generator-approval-and-output')
    restored=[]
    for name,expected in read_json(artifact/'package-inputs.json').items():
        target=artifact/name
        if not target.exists():
            require(name in WIT,'published-dotnet-replay-only-original-wit-restoration')
            raw=read_file(artifact/'package/layers'/name,256*1024)
            require({'digest':digest(raw),'size':len(raw)}==expected,'published-dotnet-replay-original-wit-layer')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);restored.append(name)
        raw=read_file(target,COMPONENT['bytes'] if name=='component.wasm' else 4*1024**2)
        require({'digest':digest(raw),'size':len(raw)}==expected,
                'published-dotnet-replay-original-package-input')
    return {'originalBuild':marker,'capturedSdkFiles':sdk_count,'restoredOriginalWit':restored,
        'component':COMPONENT,'compiledSource':SOURCE,'componentRecompiled':False}


def replay(native_input,output):
    output=output.resolve();native_input=native_input.resolve()
    require(ROOT not in output.parents and output not in ROOT.parents and native_input!=output
        and output not in native_input.parents and native_input not in output.parents,
        'published-dotnet-replay-separated-owned-output')
    output=fresh(output)
    retained=verify_prepared(native_input);native=native_products(native_input)
    record={'schemaVersion':'latent.dotnet.published-http.replay.v1','status':'incomplete',
        'compiledSource':SOURCE,'executionSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        'nativeProducer':retained,'componentRecompiled':False,'fullTicketQualification':False}
    execution_sources={name:file_identity(ROOT/name) for name in
        ('tools/replay_dotnet_published_http.py',WORKFLOW,*node.MATERIALS)}
    record['executionSources']=execution_sources
    stage='original-build-acquisition'
    try:
        artifact,record['origin']=acquire(output/'original')
        original=read_json(artifact.parent/'FAILED.json')
        record['originalBuildVerification']=verify_original(original,artifact,output/'verified-recipe')
        require(original['nativeProducer']==retained,'published-dotnet-replay-same-original-native-products')
        stage='signed-library-and-extension-programme'
        execution=node.run(artifact,native,output/'node')
        require(execution['status']=='passed' and len(execution['cases'])==20
            and len(execution['preEntryRefusals'])==2 and retained==verify_prepared(native_input)
            and execution_sources=={name:file_identity(ROOT/name) for name in execution_sources},
            'published-dotnet-replay-all-original-outcomes')
        record.update(status='passed',guestExecutions=20,preIoRefusals=2)
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();print(replay(args.native,args.output)['status'])
