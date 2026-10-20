"""Fresh signing/runtime execution around one authenticated original Java build."""
from __future__ import annotations
import argparse
from pathlib import Path,PurePosixPath
import subprocess
import sys
import time

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import qualify_java_resource_runtime as qualification
from tools import wait_runtime_native_products as products
from tools.java_replay_materials import api
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity,source_identity
from tools.rust_capsule_project import ROOT,digest,fresh,read_file,read_json,write_json

SPEC='tools/fixtures/java-resource-runtime/c277-retained-public-inventory.json'
ALLOWED_DRIFT={'tools/qualify_java_resource_runtime.py','.github/workflows/java-resource-runtime.yml'}
WIT=('wit/world.wit','wit/deps/clock/package.wit','wit/deps/random/package.wit',
    'wit/deps/log/package.wit','wit/deps/activation-runtime/package.wit')


def verify_origin(spec,run,job,artifact):
    require(spec['schemaVersion']=='latent.java.resource-runtime-retained.v1'
        and run['id']==spec['run']==job['run_id'] and run['head_sha']==job['head_sha']==spec['source']
        and run['path']=='.github/workflows/java-resource-runtime.yml' and run['event']=='push'
        and run['head_branch']=='feat/java-resource-runtime-20261020'
        and run['conclusion']==job['conclusion']=='failure' and run['status']==job['status']=='completed'
        and job['id']==spec['job'] and artifact['workflow_run']['id']==spec['run']
        and artifact['workflow_run']['head_sha']==spec['source'] and not artifact['expired']
        and all(artifact[k]==v for k,v in spec['artifact'].items()),'java-resource-replay-official-original-origin')


def verify_members(directory,spec,restored=()):
    rows=spec['members'];require(len(rows)==105,'java-resource-replay-fixed-public-inventory')
    expected={row['path']:row for row in rows};require(len(expected)==len(rows),'java-resource-replay-distinct-inventory')
    pending=[directory];found=set();entries=0;total=0
    while pending:
        for path in pending.pop().iterdir():
            entries+=1;require(entries<=512 and not path.is_symlink(),'java-resource-replay-entry-or-link-bound')
            if path.is_dir():pending.append(path);continue
            name=path.relative_to(directory).as_posix();found.add(name)
            require(name in expected or name in restored,'java-resource-replay-foreign-public-member')
            if name in expected:
                row=expected[name];logical=PurePosixPath(name)
                require(logical.as_posix()==name and not logical.is_absolute() and '..' not in logical.parts
                    and ':' not in name and '\\' not in name,'java-resource-replay-public-member-path')
                require(file_identity(path,8*1024**2)=={'sha256':row['sha256'],'bytes':row['bytes']},
                    'java-resource-replay-original-member-preimage')
                total+=row['bytes'];require(total<=16*1024**2,'java-resource-replay-public-byte-bound')
    require(found==set(expected)|set(restored),'java-resource-replay-missing-original-member')


def restore_original_layers(build):
    objects={'resources/objects/'+digest(raw)[7:] for raw in qualification.fixture.DATA.values()}
    allowed=set(WIT)|objects;restored=[]
    for name,expected in read_json(build/'package-inputs.json').items():
        target=build/name
        if target.exists():continue
        require(name in allowed,'java-resource-replay-only-original-public-layer')
        raw=read_file(build/'package/layers'/name,1024**2)
        require({'digest':digest(raw),'size':len(raw)}==expected,'java-resource-replay-original-layer-preimage')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);restored.append(name)
    require(set(restored)==allowed,'java-resource-replay-exact-eight-original-layers')
    return restored


def original_materials(record,spec):
    require(record['source']==spec['source'] and record['status']=='failed'
        and record['stage']=='one-fresh-offline-fiber-io-component' and record['errorCategory']=='WorkflowError'
        and record['guestComponentsCompiled']==2 and record['unsignedCompilerControlComponents']==1
        and record['engineRebuilt'] is False and record['nativeProductsBuilt']==0
        and set(record['materials'])==set(qualification.MATERIALS),'java-resource-replay-genuine-original-build')
    for name,expected in record['materials'].items():
        raw=subprocess.check_output(['git','show',spec['source']+':'+name],cwd=ROOT,timeout=15)
        require({'sha256':digest(raw),'bytes':len(raw)}==expected,'java-resource-replay-original-git-material')
        if name not in ALLOWED_DRIFT:
            require(file_identity(ROOT/name)==expected,'java-resource-replay-unchanged-exercised-source')


def replay(native_directory,retained,output):
    require(sys.platform=='linux' and sys.version_info>=(3,13),'java-resource-replay-linux-python313')
    retained,native_directory=(Path(path).resolve(strict=True) for path in (retained,native_directory))
    output=Path(output).absolute()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=p and output not in p.parents and p not in output.parents for p in (retained,native_directory)),
        'java-resource-replay-separated-inputs')
    spec=read_json(ROOT/SPEC);verify_origin(spec,api(f'actions/runs/{spec["run"]}'),
        api(f'actions/jobs/{spec["job"]}'),api(f'actions/artifacts/{spec["artifact"]["id"]}'))
    verify_members(retained,spec)
    original=read_json(retained/'java-resource-runtime/FAILED.json');original_materials(original,spec)
    build=retained/'java-resource-runtime/build';restored=restore_original_layers(build)
    restored_paths=['java-resource-runtime/build/'+name for name in restored]
    verify_members(retained,spec,restored_paths);before=qualification.build_evidence(build)
    compiled=products.verify_prepared(native_directory);binaries=products.native_products(native_directory)
    require(compiled==original['compiledNative'],'java-resource-replay-identical-original-native-producer')
    for path in binaries.values():path.chmod(0o700)
    output=fresh(output);source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip()
    names=(*qualification.MATERIALS,SPEC,'tools/replay_java_resource_runtime.py')
    materials={name:file_identity(ROOT/name) for name in names};consumer=source_identity(ROOT)
    record={'schemaVersion':'latent.java.resource-runtime-replay.v1','status':'incomplete','source':source,
        'compiledGuestSource':spec['source'],'originalArtifact':spec['artifact'],'originalMembersVerified':105,
        'originalCompiledGuestComponents':2,'originalUnsignedCompilerControlComponents':1,
        'guestCompilationRepeated':False,'guestComponentsCompiled':0,'nativeProductsBuilt':0,'engineRebuilt':False,
        'historicalQualificationRelabelled':False,'originalBuild':before,'compiledNative':compiled,
        'archiveDigestVerification':'official-metadata-and-all105-member-preimages',
        'restoredOriginalPublicLayers':restored,'materials':materials,'consumerNativeSource':consumer,
        'fullTicketQualification':False}
    try:
        record['node']=qualification.execute(build,binaries,output/'node',time.monotonic()+600)
        verify_members(retained,spec,restored_paths)
        require(qualification.build_evidence(build)==before and products.verify_prepared(native_directory)==compiled
            and materials=={name:file_identity(ROOT/name) for name in materials} and source_identity(ROOT)==consumer
            and subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip()==source,
            'java-resource-replay-final-source-build-products')
        record.update(status='passed',outcomes=13,signedAndAdmitted=True)
        write_json(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',errorCategory=type(error).__name__)
        write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','retained','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(replay(args.native,args.retained,args.output)['status'])
