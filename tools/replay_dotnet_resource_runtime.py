"""Re-sign one authenticated fresh AOT component after a controller-only repair."""
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
from tools import java_phase_native_products as products
from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_dotnet_resource_runtime import build_evidence, execute, MATERIALS
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

SOURCE='b168a7c0f1327b188a07f01be893826f9582d42e'
RUN=39450403865
JOB=118723386663
ARTIFACT={'id':12279271833,'size_in_bytes':8274454,
    'digest':'sha256:6cf7f9c63108aed40db612fab7c815f9d6ed97ef34f69c9f39eb0271140d7a0c'}
COMPONENT={'sha256':'sha256:8b9949a3378ffc450bce9a08b4110f8e1ef30a2a8819fb2cdfc66cd072d288da','bytes':2759390}
PREFIX='dotnet-resource-runtime/'
WIT=('wit/deps/activation-runtime/package.wit','wit/deps/clock/package.wit',
     'wit/deps/log/package.wit','wit/deps/random/package.wit','wit/world.wit')
NODE='tools/dotnet_resource_runtime_node.py'


def validate_origin(metadata,job):
    require(all(metadata.get(key)==value for key,value in ARTIFACT.items()) and metadata.get('expired') is False
        and metadata.get('workflow_run',{}).get('id')==RUN
        and metadata['workflow_run'].get('head_sha')==SOURCE
        and job.get('run_id')==RUN and job.get('id')==JOB and job.get('head_sha')==SOURCE
        and job.get('status')=='completed' and job.get('conclusion')=='failure',
        'resource-dotnet-replay-exact-failed-producer')


def unpack(raw,output):
    total=0;copied=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows=archive.infolist()
        require(0<len(rows)<=512 and len({row.filename for row in rows})==len(rows),
            'resource-dotnet-replay-archive-members')
        for row in rows:
            path=PurePosixPath(row.filename)
            require(row.orig_filename==row.filename and not path.is_absolute() and '..' not in path.parts and '\\' not in row.filename
                and ':' not in row.filename and path.as_posix()==row.filename and not row.is_dir()
                and stat.S_IFMT(row.external_attr>>16)!=stat.S_IFLNK and not row.flag_bits&1
                and 0<=row.file_size<=64*1024**2,'resource-dotnet-replay-regular-public-member')
            total+=row.file_size
            require(total<=192*1024**2,'resource-dotnet-replay-archive-byte-bound')
            # Read every member for CRC; materialize only the fixed public build
            # and original failure observations needed to authenticate ancestry.
            data=archive.read(row)
            require(len(data)==row.file_size,'resource-dotnet-replay-member-length')
            if row.filename.startswith(PREFIX+'build/') or row.filename in (
                PREFIX+'FAILED.json',PREFIX+'node/FAILED.json',PREFIX+'node/examples-controls/024.json'):
                target=output.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data);copied.append(row.filename)
    return {'crcCheckedMembers':len(rows),'uncompressedBytes':total,'materializedPublicMembers':copied}


def restore_layers(artifact):
    """Copy the original raw WIT layers; never recreate a build observation."""
    inputs=read_json(artifact/'package-inputs.json');restored=[]
    for name,expected in inputs.items():
        path=PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and path.as_posix()==name
            and '\\' not in name and ':' not in name,'resource-dotnet-replay-package-layer-path')
        target=artifact/name
        if not target.exists():
            require(name in WIT,'resource-dotnet-replay-only-original-wit-layer')
            raw=read_file(artifact/'package/layers'/name,256*1024)
            require({'digest':digest(raw),'size':len(raw)}==expected,'resource-dotnet-replay-original-wit-layer-bytes')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);restored.append(name)
    return restored


def acquire(output):
    metadata=api(f'actions/artifacts/{ARTIFACT["id"]}');job=api(f'actions/jobs/{JOB}')
    validate_origin(metadata,job)
    token=os.environ.get('GH_TOKEN');require(bool(token),'resource-dotnet-replay-explicit-actions-token')
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization':'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code==302,'resource-dotnet-replay-redirect');url=error.headers['Location']
    else:raise ValueError('resource-dotnet-replay-redirect-required')
    require(url.startswith('https://'),'resource-dotnet-replay-public-https')
    source=Ranges(url,ARTIFACT['size_in_bytes']);raw=source.read(ARTIFACT['size_in_bytes'])
    require(len(raw)==ARTIFACT['size_in_bytes'] and digest(raw)==ARTIFACT['digest'],
        'resource-dotnet-replay-whole-archive-sha256')
    record=unpack(raw,output);record.update(artifact=metadata,job=job)
    original=output/PREFIX;artifact=original/'build'
    record['originalWitLayersMaterialized']=restore_layers(artifact)
    return artifact,read_json(original/'FAILED.json'),record


def original_materials(record):
    materials=record.get('materials')
    require(type(materials) is dict and set(materials)==set(MATERIALS),
        'resource-dotnet-replay-original-material-set')
    for name,expected in materials.items():
        raw=subprocess.check_output(['git','show',SOURCE+':'+name],cwd=ROOT,timeout=15)
        require({'sha256':digest(raw),'bytes':len(raw)}==expected,'resource-dotnet-replay-original-git-material')
        if name!=NODE:require(file_identity(ROOT/name)==expected,'resource-dotnet-replay-unchanged-build-input')


def replay(native_directory,output):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'resource-dotnet-replay-linux-python313')
    output=Path(output).absolute();native_directory=Path(native_directory).resolve(strict=True)
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and output!=native_directory and native_directory not in output.parents and output not in native_directory.parents,
        'resource-dotnet-replay-separated-inputs')
    output=fresh(output)
    compiled=products.verify_prepared(native_directory);native=products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    current_source=source_identity(ROOT);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    current_materials={name:file_identity(ROOT/name) for name in (*MATERIALS,'tools/replay_dotnet_resource_runtime.py')}
    record={'schemaVersion':'latent.dotnet.resource-runtime-replay.v1','status':'incomplete',
        'source':source,'compiledGuestSource':SOURCE,'nativeAotCompilationRepeated':False,
        'guestComponentsCompiled':0,'nativeProductsBuilt':0,'engineRebuilt':False,
        'compiledNative':compiled,'consumerNativeSource':current_source,'materials':current_materials,
        'fullTicketQualification':False,'historicalQualificationRelabelled':False}
    try:
        artifact,original,record['acquisition']=acquire(fresh(output/'retained'))
        original_materials(original)
        require(original['source']==SOURCE and original['status']=='failed'
            and original['stage']=='normal-sign-admit-and-joined-runtime-programme'
            and original['nativeAotCompilationSucceeded'] is True and original['guestComponentsCompiled']==1
            and original['compiledNative']==compiled and original['consumerNativeSource']==current_source,
            'resource-dotnet-replay-genuine-aot-and-original-native-ancestry')
        before=build_evidence(artifact)
        require(before==original['freshBuild'] and before['component']==COMPONENT,
            'resource-dotnet-replay-exact-original-component-and-observations')
        record['freshOriginalBuild']=before
        observed=execute(artifact,native,output/'node')
        require(observed['status']=='passed' and build_evidence(artifact)==before
            and source_identity(ROOT)==current_source and products.verify_prepared(native_directory)==compiled
            and current_materials=={name:file_identity(ROOT/name) for name in current_materials}
            and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()==source,
            'resource-dotnet-replay-final-source-build-and-native-identity')
        record.update(status='passed',outcomes=15,signedAndAdmitted=True,
            nodeReceipt=file_identity(output/'node/qualified.json'))
        write_json(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',errorCategory=type(error).__name__)
        write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(replay(args.native,args.output)['status'])
