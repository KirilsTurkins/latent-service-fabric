"""Diagnostic-only fresh resource greeting with authenticated historical products."""
import argparse
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import java_replay_materials as historical, dotnet_byte_host_acquisition as host
from tools.java_capsule_project import create
from tools.native_runtime.verify import relative
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_resources import MATERIALS, campaign
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

PRODUCTION='c6f42ad68701ce28906534b40c92d60ed67559ee'
COMPILED='79d13eaa7da45882ad278c6d3ce09a971d111310'
ARTIFACT=12243715960
DIGEST='sha256:538e248483f8afef0bc155f045b80e20dd8e4c7d5442f2087c839c31a972ea59'
BYTES=4280819
RUN=39374983147
JOB=118471006015


def source():
    paths=sorted(set(MATERIALS)|{'sdk/java-guest','wit','schemas'})
    result=subprocess.run(['git','diff','--exit-code',PRODUCTION,'--',*paths],cwd=ROOT,capture_output=True,timeout=30)
    require(result.returncode==0 and not result.stdout, 'java-resources-current-production-drift')
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,timeout=30),
        'java-resources-clean-diagnostic-source')
    diagnostic=('tools/replay_java_resources.py','tools/java_replay_materials.py',
        'tools/dotnet_byte_host_acquisition.py','tools/dotnet_task_replay_acquisition.py')
    return {'productionSource':PRODUCTION,'fixtureSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        'currentProductionInputsEqual':True,'materials':{path:file_identity(ROOT/path) for path in sorted(set(MATERIALS))},
        'diagnosticMaterials':{path:file_identity(ROOT/path) for path in diagnostic}}


def companions_archive():
    artifact=historical.api(f'actions/artifacts/{ARTIFACT}')
    job=historical.api(f'actions/jobs/{JOB}')
    require(artifact['id']==ARTIFACT and not artifact['expired'] and artifact['size_in_bytes']==BYTES
        and artifact['digest']==DIGEST and artifact['workflow_run']['id']==RUN
        and artifact['workflow_run']['head_sha']==COMPILED and job['run_id']==RUN
        and job['head_sha']==COMPILED and job['status']=='completed' and job['conclusion']=='failure', 'java-resources-fixed-companion-origin')
    raw=subprocess.check_output(['gh','api','repos/'+historical.REPOSITORY+f'/actions/artifacts/{ARTIFACT}/zip'],timeout=180)
    return decode_companions(raw)


def decode_companions(raw):
    require(len(raw)==BYTES and digest(raw)==DIGEST, 'java-resources-companion-ZIP-digest')
    selected={}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows=archive.infolist()
        require(len(rows)==len(set(archive.namelist()))==710 and sum(row.file_size for row in rows)==19175097,
            'java-resources-companion-ZIP-bound')
        for row in rows:
            relative(row.filename)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr>>16) in (0,stat.S_IFREG)
                and 0<=row.file_size<=8*1024**2, 'java-resources-companion-regular-member')
            data=archive.read(row)
            if row.filename=='java-filesystem-replay/node/workflow.json':
                node=json.loads(data)
                require(node['status']=='passed' and node['language']=='java' and len(node['invocations'])==41
                    and all(r['processReaped'] and r['response']['outcomeKnown'] for r in node['invocations'])
                    and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                    'java-resources-original-actual-node-required')
                selected['originalNode']=file_identity_bytes(data)
            for name in TEMPLATES:
                if name=='greeting': continue
                prefix='java-filesystem-replay/builds/'+name+'/'
                if row.filename.startswith(prefix):
                    leaf=row.filename[len(prefix):]
                    if '/' not in leaf and (leaf.endswith('.json') or leaf=='component.wasm'):
                        selected[name+'/'+leaf]=data
    require('originalNode' in selected and all(name+'/component.wasm' in selected for name in TEMPLATES if name!='greeting'),
        'java-resources-four-original-companions')
    return selected


def file_identity_bytes(data): return {'sha256':digest(data),'bytes':len(data)}


def restore_companion(root,name,selected):
    app=create(root/'source',name); files=snapshot(app)
    output=root/'build'; output.mkdir()
    for path,raw in selected.items():
        if path.startswith(name+'/'): (output/path[len(name)+1:]).write_bytes(raw)
    require(read_file(output/'source-inputs.json')==inventory(files), 'java-resources-original-companion-source-drift')
    marker=read_json(output/'BUILD-COMPLETE.json')
    require(marker['componentDigest']==digest(read_file(output/'component.wasm',64*1024**2))
        and marker['sourceDigest']==digest(read_file(output/'source-inputs.json'))
        and marker['observationDigest']==digest(read_file(output/'build-observation.json')),
        'java-resources-original-companion-observation')
    for path,identity in read_json(output/'package-inputs.json').items():
        relative(path)
        target=output/path
        if not target.exists():
            source_name='vendor/lsf/wit/platform/http-v2/package.wit' if path=='wit/deps/http-v2/package.wit' else path
            require(path.startswith('wit/') and source_name in files, 'java-resources-unavailable-package-layer')
            require(json.loads(read_file(output/'source-inputs.json'))[source_name]==
                {'digest':digest(files[source_name]),'size':len(files[source_name])}, 'java-resources-unobserved-WIT-layer')
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(files[source_name])
        data=read_file(target,64*1024**2)
        require(identity=={'digest':digest(data),'size':len(data)}, 'java-resources-original-companion-layer-drift')
    identity=package_identity(output,marker)
    return output,{'marker':marker,'signerInputs':identity,'applicationSourceEqual':True,'recompiled':False}


def prepare(output):
    source(); output=fresh(output)
    artifact=historical.Artifact('helpers')
    for name in ('qualification.json','source-inputs.json','source-inputs-after.json'):
        artifact.extract(historical.PREFIX+name,output/name)
    require(file_identity(output/'qualification.json')['sha256']==historical.QUALIFICATION_SHA
        and file_identity(output/'source-inputs.json')['sha256']==historical.SOURCE_SHA
        and read_file(output/'source-inputs.json',16*1024**2)==read_file(output/'source-inputs-after.json',16*1024**2),
        'java-resources-original-helper-observation')
    q=read_json(output/'qualification.json'); products=output/'native'; products.mkdir()
    for name,identity in historical.HELPERS.items():
        original='latent' if name=='latent' else 'examples/'+name
        require(q['binaries'][original]==identity, 'java-resources-original-helper-binding')
        artifact.extract(historical.PREFIX+'native-binaries/'+original.replace('/','-'),products/name)
        require(file_identity(products/name,256*1024**2)==identity,'java-resources-original-helper-bytes')
        (products/name).chmod(0o700)
    host_record=host.retrieve(output/'selected-host')
    selected=companions_archive(); companions={}; restored={}
    for name in TEMPLATES:
        if name=='greeting': continue
        root=output/'companions'/name; root.mkdir(parents=True)
        companions[name],restored[name]=restore_companion(root,name,selected)
    record={'schemaVersion':'latent.java.resources.replay-materials.v1','helpersSource':historical.ORIGINAL,
        'helpersOriginalDotnetReceipt':file_identity(output/'qualification.json'), 'helperOrigin':artifact.summary(),
        'helpers':historical.HELPERS,'selectedHost':host_record,'companionSource':COMPILED,'companionRun':RUN,
        'companionJob':JOB,'companionOriginalJobConclusion':'failure','companionArtifact':ARTIFACT,
        'companionArchiveDigest':DIGEST,'originalJavaNode':selected['originalNode'],'companions':restored,
        'normalJavaReceiptFabricated':False,'nativeTupleFabricated':False,'nativeRebuilt':False}
    write_json(output/'retrieval.json',record)
    return record


def verify(prepared):
    record=read_json(prepared/'retrieval.json')
    require(record['schemaVersion']=='latent.java.resources.replay-materials.v1'
        and record['helpers']==historical.HELPERS and record['companionSource']==COMPILED
        and record['companionArtifact']==ARTIFACT and record['companionArchiveDigest']==DIGEST
        and record['helpersOriginalDotnetReceipt']==file_identity(prepared/'qualification.json')
        and host.validate(prepared/'selected-host')['binary']==record['selectedHost']['binary'],
        'java-resources-selected-material-recheck')
    binaries={('latent' if name=='latent' else 'examples/'+name):prepared/'native'/name for name in historical.HELPERS}
    require(all(file_identity(path,256*1024**2)==historical.HELPERS[('latent' if name=='latent' else name.split('/')[1])]
        for name,path in binaries.items()), 'java-resources-selected-helper-drift')
    binaries['latentd']=prepared/'selected-host/latentd'
    companions={name:prepared/'companions'/name/'build' for name in TEMPLATES if name!='greeting'}
    require(all(package_identity(path,read_json(path/'BUILD-COMPLETE.json'))==record['companions'][name]['signerInputs']
        for name,path in companions.items()), 'java-resources-selected-companion-drift')
    return binaries,companions,record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    for name in ('output','prepared','wasi-sdk'): parser.add_argument('--'+name,type=Path,required=name=='output')
    args=parser.parse_args()
    require(sys.platform=='linux' and os.geteuid()!=0, 'java-resources-unprivileged-host')
    if args.prepare:
        require(args.prepared is None and args.wasi_sdk is None,'java-resources-prepare-only')
        prepare(args.output.resolve())
    else:
        require(args.prepared is not None and args.wasi_sdk is not None,'java-resources-explicit-inputs')
        before=source(); binaries,companions,ancestry=verify(args.prepared.resolve(strict=True))
        result=campaign(args.output,binaries,companions,ancestry,args.wasi_sdk.resolve(strict=True))
        require(source()==before and verify(args.prepared)[2]==ancestry,'java-resources-observed-source-product-drift')
        write_json(args.output/'replay.json',{'source':before,'qualification':file_identity(args.output/'qualified.json'),
            'status':result['status'],'nativeRebuilt':False,'companionComponentsRecompiled':False})
        print(result['status'])
